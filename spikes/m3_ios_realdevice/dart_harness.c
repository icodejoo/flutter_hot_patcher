#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include "dart_api.h"
#include "dart_harness.h"

extern const uint8_t kDartIsolateSnapshotData[];
extern const uint8_t kDartIsolateSnapshotInstructions[];
extern const uint8_t kDartVmSnapshotData[];
extern const uint8_t kDartVmSnapshotInstructions[];

extern Dart_NativeFunction builtin_native_lookup_shim(Dart_Handle name, int argument_count, bool* auto_setup_scope);
extern const uint8_t* builtin_native_symbol_shim(Dart_NativeFunction nf);
extern Dart_NativeEntryResolver get_bootstrap_resolver(void);

#define CHK(h) do { \
    if (Dart_IsError(h)) { \
        fprintf(stderr, "[DART ERR] %s\n", Dart_GetError(h)); \
        Dart_ExitScope(); \
        Dart_ShutdownIsolate(); \
        return "ERROR"; \
    } \
} while(0)

static bool g_initialized = false;
static char g_result[256] = "UNKNOWN";

static Dart_Handle setup_print(void) {
    Dart_Handle builtin = Dart_LookupLibrary(Dart_NewStringFromCString("dart:_builtin"));
    if (Dart_IsError(builtin)) return builtin;
    Dart_Handle err = Dart_SetNativeResolver(builtin, builtin_native_lookup_shim, builtin_native_symbol_shim);
    if (Dart_IsError(err)) return err;
    Dart_Handle print_closure = Dart_Invoke(builtin, Dart_NewStringFromCString("_getPrintClosure"), 0, NULL);
    if (Dart_IsError(print_closure)) return print_closure;
    Dart_Handle internal = Dart_LookupLibrary(Dart_NewStringFromCString("dart:_internal"));
    if (Dart_IsError(internal)) return internal;
    return Dart_SetField(internal, Dart_NewStringFromCString("_printClosure"), print_closure);
}

const char* dart_run(int use_patch) {
    if (!g_initialized) {
        const char* vflags[] = {"--precompiled_mode=true"};
        char* fe = Dart_SetVMFlags(1, vflags);
        if (fe) { fprintf(stderr, "[ERR] flags: %s\n", fe); free(fe); return "ERROR"; }

        Dart_InitializeParams p; memset(&p, 0, sizeof(p));
        p.version = DART_INITIALIZE_PARAMS_CURRENT_VERSION;
        p.vm_snapshot_data = kDartVmSnapshotData;
        p.vm_snapshot_instructions = kDartVmSnapshotInstructions;
        char* ie = Dart_Initialize(&p);
        if (ie) { fprintf(stderr, "[ERR] Init: %s\n", ie); free(ie); return "ERROR"; }
        g_initialized = true;
    }

    char* err = NULL;
    Dart_Isolate iso = Dart_CreateIsolateGroup(
        "vm://hotpatch", "main",
        kDartIsolateSnapshotData, kDartIsolateSnapshotInstructions,
        NULL, NULL, NULL, &err);
    if (!iso) { fprintf(stderr, "[ERR] CreateIsolate: %s\n", err ? err : "null"); free(err); return "ERROR"; }

    Dart_EnterScope();
    Dart_Handle setup_r = setup_print();
    CHK(setup_r);

    Dart_Handle root_lib = Dart_RootLibrary();
    CHK(root_lib);

    /* Set BootstrapNatives::Lookup directly as the resolver for the root library.
       This makes IsBootstrapResolver() return true, so native calls go through
       BootstrapNativeCallWrapper (correct calling convention for DN_* functions). */
    Dart_SetNativeResolver(root_lib, get_bootstrap_resolver(), NULL);

    /* Call setup([] or ['--patch']) */
    Dart_Handle arg_list = Dart_NewList(use_patch ? 1 : 0);
    CHK(arg_list);
    if (use_patch) {
        Dart_ListSetAt(arg_list, 0, Dart_NewStringFromCString("--patch"));
    }
    Dart_Handle setup_args[1] = {arg_list};
    Dart_Handle setup_fn = Dart_GetField(root_lib, Dart_NewStringFromCString("setup"));
    CHK(setup_fn);
    Dart_Handle setup_res = Dart_InvokeClosure(setup_fn, 1, setup_args);
    CHK(setup_res);

    /* Call getResult() -> string */
    Dart_Handle get_fn = Dart_GetField(root_lib, Dart_NewStringFromCString("getResult"));
    CHK(get_fn);
    Dart_Handle result_h = Dart_InvokeClosure(get_fn, 0, NULL);
    CHK(result_h);

    const char* result_str = NULL;
    Dart_StringToCString(result_h, &result_str);
    strncpy(g_result, result_str ? result_str : "NULL", 255);

    Dart_ExitScope();
    Dart_ShutdownIsolate();
    return g_result;
}

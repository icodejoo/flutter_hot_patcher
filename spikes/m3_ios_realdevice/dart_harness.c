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

const char* dart_run(int use_patch, const char* patch_dill_path) {
    FILE* dbg = fopen("/private/var/tmp/dart_debug.txt", "w");
    if (!dbg) dbg = stderr;

#define CHK(h, label) do { \
    if (Dart_IsError(h)) { \
        fprintf(dbg, "[ERR %s] %s\n", label, Dart_GetError(h)); \
        fflush(dbg); fclose(dbg); \
        Dart_ExitScope(); Dart_ShutdownIsolate(); return "ERROR_" label; \
    } \
} while(0)

    fprintf(dbg, "dart_run: use_patch=%d path=%s\n", use_patch,
            patch_dill_path ? patch_dill_path : "(null)");
    fflush(dbg);

    if (!g_initialized) {
        const char* vflags[] = {"--precompiled_mode=true"};
        char* fe = Dart_SetVMFlags(1, vflags);
        if (fe) { fprintf(dbg, "flags err: %s\n", fe); fclose(dbg); free(fe); return "ERROR"; }
        Dart_InitializeParams p; memset(&p, 0, sizeof(p));
        p.version = DART_INITIALIZE_PARAMS_CURRENT_VERSION;
        p.vm_snapshot_data = kDartVmSnapshotData;
        p.vm_snapshot_instructions = kDartVmSnapshotInstructions;
        char* ie = Dart_Initialize(&p);
        if (ie) { fprintf(dbg, "init err: %s\n", ie); fclose(dbg); free(ie); return "ERROR"; }
        g_initialized = true;
    }

    char* err = NULL;
    Dart_Isolate iso = Dart_CreateIsolateGroup("vm://hotpatch", "main",
        kDartIsolateSnapshotData, kDartIsolateSnapshotInstructions,
        NULL, NULL, NULL, &err);
    if (!iso) { fprintf(dbg, "iso err: %s\n", err ? err : "null"); fclose(dbg); free(err); return "ERROR"; }

    Dart_EnterScope();
    CHK(setup_print(), "print");
    fprintf(dbg, "print OK\n"); fflush(dbg);

    Dart_Handle root_lib = Dart_RootLibrary(); CHK(root_lib, "rootlib");
    Dart_Handle setup_fn = Dart_GetField(root_lib, Dart_NewStringFromCString("setup")); CHK(setup_fn, "setup_get");
    Dart_Handle empty = Dart_NewList(0); CHK(empty, "newlist");
    Dart_Handle sa[1] = {empty};
    CHK(Dart_InvokeClosure(setup_fn, 1, sa), "setup_call");
    fprintf(dbg, "setup OK\n"); fflush(dbg);

    const char* result_str = NULL;

    if (use_patch && patch_dill_path) {
        /* Read patch.dill */
        FILE* f = fopen(patch_dill_path, "rb");
        if (!f) { fprintf(dbg, "fopen fail: %s\n", patch_dill_path); fclose(dbg); Dart_ExitScope(); Dart_ShutdownIsolate(); return "ERR_OPEN"; }
        fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
        uint8_t* buf = (uint8_t*)malloc(sz);
        fread(buf, 1, sz, f); fclose(f);
        fprintf(dbg, "read %ld bytes\n", sz); fflush(dbg);

        /* Load bytecode as a library */
        Dart_Handle td = Dart_NewExternalTypedData(Dart_TypedData_kUint8, buf, sz);
        CHK(td, "typeddata");
        Dart_Handle patch_lib = Dart_LoadLibraryFromBytecode(td);
        CHK(patch_lib, "loadlib");
        fprintf(dbg, "LoadLibraryFromBytecode OK\n"); fflush(dbg);

        /* Invoke greet() directly from the patch library */
        Dart_Handle patch_result = Dart_Invoke(patch_lib,
            Dart_NewStringFromCString("greet"), 0, NULL);
        CHK(patch_result, "invoke_greet");
        Dart_StringToCString(patch_result, &result_str);
        fprintf(dbg, "Dart_Invoke greet = %s\n", result_str ? result_str : "(null)"); fflush(dbg);
        free(buf);
    } else {
        /* Baseline: call getResult() from AOT snapshot */
        Dart_Handle get_fn = Dart_GetField(root_lib, Dart_NewStringFromCString("getResult")); CHK(get_fn, "getresult_get");
        Dart_Handle res = Dart_InvokeClosure(get_fn, 0, NULL); CHK(res, "getresult_call");
        Dart_StringToCString(res, &result_str);
        fprintf(dbg, "getResult = %s\n", result_str ? result_str : "(null)"); fflush(dbg);
    }

    strncpy(g_result, result_str ? result_str : "NULL", 255);
    Dart_ExitScope(); Dart_ShutdownIsolate();
    fclose(dbg);
    return g_result;
#undef CHK
}

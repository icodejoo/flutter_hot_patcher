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

const char* dart_run(int use_patch, const char* patch_dill_path) {
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

    /* Call setup(['--alt']) to initialize greetVar with two possible targets (prevents CHA devirtualization) */
    Dart_Handle arg_list = Dart_NewList(1);
    CHK(arg_list);
    Dart_ListSetAt(arg_list, 0, Dart_NewStringFromCString("--alt"));
    Dart_Handle setup_fn = Dart_GetField(root_lib, Dart_NewStringFromCString("setup"));
    CHK(setup_fn);
    Dart_Handle setup_args[1] = {arg_list};
    Dart_Handle setup_res = Dart_InvokeClosure(setup_fn, 1, setup_args);
    CHK(setup_res);

    /* Then reset greetVar to greet (the actual baseline) */
    Dart_Handle greet_fn = Dart_GetField(root_lib, Dart_NewStringFromCString("greet"));
    CHK(greet_fn);
    Dart_Handle set_greetvar = Dart_SetField(root_lib, Dart_NewStringFromCString("greetVar"), greet_fn);
    CHK(set_greetvar);

    if (use_patch && patch_dill_path) {
        /* Read patch.dill from file */
        FILE* f = fopen(patch_dill_path, "rb");
        if (!f) {
            fprintf(stderr, "[ERR] Cannot open patch.dill: %s\n", patch_dill_path);
            Dart_ExitScope();
            Dart_ShutdownIsolate();
            return "ERROR_NO_PATCH";
        }
        fseek(f, 0, SEEK_END);
        long patch_size = ftell(f);
        fseek(f, 0, SEEK_SET);
        uint8_t* patch_bytes = (uint8_t*)malloc(patch_size);
        fread(patch_bytes, 1, patch_size, f);
        fclose(f);
        fprintf(stderr, "[M3] Loading patch.dill (%ld bytes) from %s\n", patch_size, patch_dill_path);

        /* Create external typed data pointing to patch bytes */
        Dart_Handle td = Dart_NewExternalTypedData(Dart_TypedData_kUint8, patch_bytes, patch_size);
        CHK(td);

        /* Load bytecode library — returns handle to the patch library */
        Dart_Handle patch_lib = Dart_LoadLibraryFromBytecode(td);
        if (Dart_IsError(patch_lib)) {
            fprintf(stderr, "[ERR] LoadLibraryFromBytecode: %s\n", Dart_GetError(patch_lib));
            free(patch_bytes);
            Dart_ExitScope();
            Dart_ShutdownIsolate();
            return "ERROR_LOAD_BYTECODE";
        }
        fprintf(stderr, "[M3] patch.dill loaded successfully\n");

        /* Get the 'greet' entry-point function from the patch library */
        Dart_Handle patch_greet = Dart_GetField(patch_lib, Dart_NewStringFromCString("greet"));
        CHK(patch_greet);
        fprintf(stderr, "[M3] Got patch greet function from bytecode library\n");

        /* Call redirectToPatch(patch_greet) to redirect greetVar's entry_point */
        Dart_Handle redirect_fn = Dart_GetField(root_lib, Dart_NewStringFromCString("redirectToPatch"));
        CHK(redirect_fn);
        Dart_Handle redirect_args[1] = {patch_greet};
        Dart_Handle redirect_res = Dart_InvokeClosure(redirect_fn, 1, redirect_args);
        CHK(redirect_res);
        fprintf(stderr, "[M3] redirect applied — greetVar now points to bytecode greet\n");

        free(patch_bytes);
    }

    /* Call getResult() → string */
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

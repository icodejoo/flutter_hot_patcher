#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include "dart_api.h"

extern const uint8_t kDartIsolateSnapshotData[];
extern const uint8_t kDartIsolateSnapshotInstructions[];
extern const uint8_t kDartVmSnapshotData[];
extern const uint8_t kDartVmSnapshotInstructions[];

/* From builtin_shim.cpp */
extern Dart_NativeFunction builtin_native_lookup_shim(Dart_Handle name, int argument_count, bool* auto_setup_scope);
extern const uint8_t* builtin_native_symbol_shim(Dart_NativeFunction nf);

#define CHK(h) do { if (Dart_IsError(h)) { printf("[ERR] %s\n", Dart_GetError(h)); fflush(stdout); Dart_ExitScope(); Dart_ShutdownIsolate(); return 1; } } while(0)

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

int main(int argc, char** argv) {
    printf("[1] Starting\n"); fflush(stdout);
    const char* vflags[] = {"--precompiled_mode=true"};
    char* fe = Dart_SetVMFlags(1, vflags);
    if (fe) { printf("[FAIL] flags: %s\n", fe); free(fe); return 1; }
    printf("[2] SetVMFlags OK\n"); fflush(stdout);
    Dart_InitializeParams p; memset(&p,0,sizeof(p));
    p.version = DART_INITIALIZE_PARAMS_CURRENT_VERSION;
    p.vm_snapshot_data = kDartVmSnapshotData;
    p.vm_snapshot_instructions = kDartVmSnapshotInstructions;
    char* ie = Dart_Initialize(&p);
    if (ie) { printf("[FAIL] Init: %s\n", ie); free(ie); return 1; }
    printf("[3] Initialize OK\n"); fflush(stdout);
    char* err = NULL;
    Dart_Isolate iso = Dart_CreateIsolateGroup("vm://demo","main",
        kDartIsolateSnapshotData,kDartIsolateSnapshotInstructions,
        NULL,NULL,NULL,&err);
    if (!iso) { printf("[FAIL] CreateIsolate: %s\n",err?err:"null"); free(err); return 1; }
    printf("[4] CreateIsolateGroup OK\n"); fflush(stdout);
    Dart_EnterScope();
    Dart_Handle setup_r = setup_print();
    CHK(setup_r);
    printf("[5] print setup OK\n"); fflush(stdout);
    Dart_Handle root_lib = Dart_RootLibrary();
    CHK(root_lib);
    Dart_Handle main_fn = Dart_GetField(root_lib, Dart_NewStringFromCString("main"));
    CHK(main_fn);
    printf("[6] Got main closure\n"); fflush(stdout);
    printf("[7] Calling main([])\n"); fflush(stdout);
    Dart_Handle args0 = Dart_NewList(0);
    Dart_Handle inv_args0[1] = {args0};
    Dart_Handle r0 = Dart_InvokeClosure(main_fn, 1, inv_args0);
    if (Dart_IsError(r0)) printf("  baseline err: %s\n", Dart_GetError(r0));
    printf("[8] Calling main([--patch])\n"); fflush(stdout);
    Dart_Handle args1 = Dart_NewList(1);
    Dart_ListSetAt(args1, 0, Dart_NewStringFromCString("--patch"));
    Dart_Handle inv_args1[1] = {args1};
    Dart_Handle r1 = Dart_InvokeClosure(main_fn, 1, inv_args1);
    if (Dart_IsError(r1)) printf("  patch err: %s\n", Dart_GetError(r1));
    Dart_ExitScope();
    Dart_ShutdownIsolate();
    printf("[DONE]\n"); fflush(stdout);
    return 0;
}

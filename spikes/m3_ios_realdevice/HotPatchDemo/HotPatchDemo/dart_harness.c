#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include "dart_api.h"
#include "dart_harness.h"

extern const uint8_t kDartIsolateSnapshotData[];
extern const uint8_t kDartIsolateSnapshotInstructions[];
extern const uint8_t kDartVmSnapshotData[];
extern const uint8_t kDartVmSnapshotInstructions[];

/* B-route: pointer to mmap'd patched IsolateSnapshotData (NULL = use baseline) */
static const uint8_t* g_vmcode_isolate_data = NULL;
static size_t         g_vmcode_isolate_data_len = 0;
static void*          g_vmcode_mmap_addr = NULL;

/**
 * Load a staged vmcode patch (patched IsolateSnapshotData) from disk into
 * read-only memory.  Call before dart_run().
 * Returns 1 if patch was loaded, 0 if no patch exists, -1 on error.
 */
int dart_load_vmcode_patch(const char* staged_path) {
    int fd = open(staged_path, O_RDONLY);
    if (fd < 0) return 0;  /* no patch staged yet */

    struct stat st;
    if (fstat(fd, &st) != 0) { close(fd); return -1; }
    size_t len = (size_t)st.st_size;

    /* mmap PROT_READ — data section, no PROT_EXEC needed */
    void* addr = mmap(NULL, len, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (addr == MAP_FAILED) return -1;

    g_vmcode_mmap_addr      = addr;
    g_vmcode_isolate_data     = (const uint8_t*)addr;
    g_vmcode_isolate_data_len = len;
    return 1;
}

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

const char* dart_run(const char* patch_bundle_dir) {
    FILE* dbg = fopen("/private/var/tmp/dart_debug.txt", "w");
    if (!dbg) dbg = stderr;

#define CHK(h, label) do { \
    if (Dart_IsError(h)) { \
        fprintf(dbg, "[ERR %s] %s\n", label, Dart_GetError(h)); \
        fflush(dbg); fclose(dbg); \
        Dart_ExitScope(); Dart_ShutdownIsolate(); return "ERROR"; \
    } \
} while(0)

    fprintf(dbg, "dart_run: bundle_dir=%s\n", patch_bundle_dir ? patch_bundle_dir : "(null)");
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

    /* B-route: use patched data section if available, otherwise baseline */
    const uint8_t* iso_data = g_vmcode_isolate_data
                              ? g_vmcode_isolate_data
                              : kDartIsolateSnapshotData;
    fprintf(dbg, "dart_run: using %s IsolateSnapshotData (%zu bytes)\n",
            g_vmcode_isolate_data ? "VMCODE-PATCHED" : "baseline",
            g_vmcode_isolate_data ? g_vmcode_isolate_data_len : (size_t)0);
    fflush(dbg);

    char* err = NULL;
    Dart_Isolate iso = Dart_CreateIsolateGroup("vm://hotpatch", "main",
        iso_data, kDartIsolateSnapshotInstructions,
        NULL, NULL, NULL, &err);
    if (!iso) { fprintf(dbg, "iso err: %s\n", err ? err : "null"); fclose(dbg); free(err); return "ERROR"; }

    Dart_EnterScope();
    CHK(setup_print(), "print");

    Dart_Handle root_lib = Dart_RootLibrary(); CHK(root_lib, "rootlib");
    Dart_Handle setup_fn = Dart_GetField(root_lib, Dart_NewStringFromCString("setup")); CHK(setup_fn, "setup");
    Dart_Handle empty = Dart_NewList(0); CHK(empty, "newlist");
    Dart_Handle sa[1] = {empty};
    CHK(Dart_InvokeClosure(setup_fn, 1, sa), "setup_call");
    fprintf(dbg, "setup OK\n"); fflush(dbg);

    const char* result_str = NULL;

    if (patch_bundle_dir) {
        /* Derive patch.dill path from bundle dir */
        char dill_path[512];
        snprintf(dill_path, sizeof(dill_path), "%s/bytecode/patch.dill", patch_bundle_dir);

        FILE* f = fopen(dill_path, "rb");
        if (!f) {
            fprintf(dbg, "patch.dill not found: %s\n", dill_path);
            fclose(dbg); Dart_ExitScope(); Dart_ShutdownIsolate();
            return "ERR_NO_PATCH";
        }
        fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
        uint8_t* buf = (uint8_t*)malloc(sz);
        fread(buf, 1, sz, f); fclose(f);
        fprintf(dbg, "patch.dill: %ld bytes from %s\n", sz, dill_path); fflush(dbg);

        Dart_Handle td = Dart_NewExternalTypedData(Dart_TypedData_kUint8, buf, sz);
        CHK(td, "typeddata");
        Dart_Handle patch_lib = Dart_LoadLibraryFromBytecode(td);
        CHK(patch_lib, "loadlib");
        fprintf(dbg, "LoadLibraryFromBytecode OK\n"); fflush(dbg);

        Dart_Handle patch_result = Dart_Invoke(patch_lib, Dart_NewStringFromCString("greet"), 0, NULL);
        CHK(patch_result, "invoke_greet");
        Dart_StringToCString(patch_result, &result_str);
        fprintf(dbg, "patch greet = %s\n", result_str ? result_str : "(null)"); fflush(dbg);
        free(buf);
    } else {
        Dart_Handle get_fn = Dart_GetField(root_lib, Dart_NewStringFromCString("getResult")); CHK(get_fn, "getresult");
        Dart_Handle res = Dart_InvokeClosure(get_fn, 0, NULL); CHK(res, "getresult_call");
        Dart_StringToCString(res, &result_str);
        fprintf(dbg, "baseline result = %s\n", result_str ? result_str : "(null)"); fflush(dbg);
    }

    strncpy(g_result, result_str ? result_str : "NULL", 255);
    Dart_ExitScope();
    /* NOTE: Do not call Dart_ShutdownIsolate() — it crashes the app on iOS. Keep isolate alive. */
    fclose(dbg);
    return g_result;
#undef CHK
}

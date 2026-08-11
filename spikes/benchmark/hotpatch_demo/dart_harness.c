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

/* flutter_hot_patcher OTA: PATCH snapshot sections loaded from vmcode_ota_patch.vmcode */
static const uint8_t* g_patch_instr = NULL;      /* PATCH kDartIsolateSnapshotInstructions */
static size_t         g_patch_instr_len = 0;
static const uint8_t* g_patch_data = NULL;       /* PATCH kDartIsolateSnapshotData */
static size_t         g_patch_data_len = 0;
static void*          g_patch_mmap_addr = NULL;  /* single mmap covering both sections */
static size_t         g_patch_mmap_len = 0;

/* C-linkage shims from simulator_arm64.cc (B4 + OTA) */
extern bool fhp_shorebird_load_vmcode(const char* path);
extern void fhp_set_base_instructions(const void* base_ptr);

/**
 * flutter_hot_patcher OTA: Load PATCH instructions + data + link table from
 * a vmcode_ota_patch.vmcode file.
 * Format: [uint32 N][uint32 instr_size][uint32 data_size]
 *         [N×8 link entries][pad to 16384]
 *         [instr_size bytes: patch instructions]
 *         [data_size bytes: patch data]
 * Returns: N (>0 = success), 0 = not found, -1 = error.
 */
int dart_load_ota_patch(const char* vmcode_path) {
    int fd = open(vmcode_path, O_RDONLY);
    if (fd < 0) return 0;  /* not found */

    struct stat st;
    if (fstat(fd, &st) != 0) { close(fd); return -1; }
    size_t total = (size_t)st.st_size;

    if (total < 16384 + 4) { close(fd); return -1; }  /* too small */

    /* Read header: N, instr_size, data_size */
    uint32_t hdr[3] = {0, 0, 0};
    if (read(fd, hdr, 12) != 12) { close(fd); return -1; }
    uint32_t n_entries  = hdr[0];
    uint32_t instr_size = hdr[1];
    uint32_t data_size  = hdr[2];

    if (n_entries > 65536 || instr_size == 0 || data_size == 0) {
        close(fd); return -1;  /* not OTA format */
    }

    size_t expected = 16384 + instr_size + data_size;
    if (total < expected) { close(fd); return -1; }

    /* mmap the entire file to get instructions + data sections */
    void* mapped = mmap(NULL, total, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (mapped == MAP_FAILED) return -1;

    /* Store BASE instructions pointer BEFORE patching (for cpu_off resolution) */
    fhp_set_base_instructions(kDartIsolateSnapshotInstructions);

    g_patch_mmap_addr = mapped;
    g_patch_mmap_len  = total;

    /* PATCH instructions start at offset 16384 */
    g_patch_instr     = (const uint8_t*)mapped + 16384;
    g_patch_instr_len = instr_size;

    /* PATCH data immediately follows */
    g_patch_data      = (const uint8_t*)mapped + 16384 + instr_size;
    g_patch_data_len  = data_size;

    /* Register link table in the Simulator */
    fhp_shorebird_load_vmcode(vmcode_path);

    fprintf(stderr, "[dart_harness] OTA patch loaded: %u entries, instr=%u, data=%u\n",
            n_entries, instr_size, data_size);
    return (int)n_entries;
}

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
    // flutter_hot_patcher B4 re-verify: write to app tmp dir so devicectl can read it
    char dart_log_path[512] = "/private/var/tmp/dart_debug.txt";
    const char* tmpdir = getenv("TMPDIR");
    if (tmpdir && strlen(tmpdir) + 20 < sizeof(dart_log_path)) {
        snprintf(dart_log_path, sizeof(dart_log_path), "%sdart_debug.txt", tmpdir);
    }
    FILE* dbg = fopen(dart_log_path, "w");
    fprintf(stderr, "[dart_harness] log path: %s\n", dart_log_path);
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

    /* flutter_hot_patcher OTA: prefer PATCH sections; fallback to B-route data; else baseline */
    const uint8_t* iso_data  = g_patch_data  ? g_patch_data
                             : g_vmcode_isolate_data ? g_vmcode_isolate_data
                             : kDartIsolateSnapshotData;
    const uint8_t* iso_instr = g_patch_instr ? g_patch_instr
                             : kDartIsolateSnapshotInstructions;

    const char* mode = g_patch_instr    ? "OTA-PATCH"
                     : g_vmcode_isolate_data ? "VMCODE-PATCHED"
                     : "baseline";
    fprintf(dbg, "dart_run: using %s IsolateSnapshotData (%zu bytes)\n",
            mode, g_patch_data ? g_patch_data_len
                : g_vmcode_isolate_data ? g_vmcode_isolate_data_len : (size_t)0);
    fprintf(dbg, "dart_run: using %s IsolateSnapshotInstructions (%zu bytes)\n",
            g_patch_instr ? "OTA-PATCH" : "baseline",
            g_patch_instr ? g_patch_instr_len : (size_t)0);
    fflush(dbg);

    char* err = NULL;
    Dart_Isolate iso = Dart_CreateIsolateGroup("vm://hotpatch", "main",
        iso_data, iso_instr,
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
            /* Return path for diagnosis via result.txt */
            static char err_path[600];
            snprintf(err_path, sizeof(err_path), "ERR_NO_PATCH:%s", dill_path);
            return err_path;
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

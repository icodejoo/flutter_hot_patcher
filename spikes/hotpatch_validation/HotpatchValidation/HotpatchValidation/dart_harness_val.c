#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <signal.h>
#include <setjmp.h>
#include "dart_api.h"
#include "dart_harness_val.h"

extern const uint8_t kDartIsolateSnapshotData[];
extern const uint8_t kDartIsolateSnapshotInstructions[];
extern const uint8_t kDartVmSnapshotData[];
extern const uint8_t kDartVmSnapshotInstructions[];

extern Dart_NativeFunction builtin_native_lookup_shim(Dart_Handle name, int argc, bool* auto_setup_scope);
extern const uint8_t* builtin_native_symbol_shim(Dart_NativeFunction nf);

static bool g_vm_initialized = false;
static sigjmp_buf g_abort_jmp;
static volatile bool g_in_dart = false;

static Dart_Isolate g_current_iso = NULL;
static void abort_handler(int sig) {
    if (g_in_dart) {
        g_in_dart = false;
        siglongjmp(g_abort_jmp, 1);
    }
    // restore default and re-raise
    signal(SIGABRT, SIG_DFL);
    raise(SIGABRT);
}

static Dart_Handle setup_print(void) {
    Dart_Handle builtin = Dart_LookupLibrary(Dart_NewStringFromCString("dart:_builtin"));
    if (Dart_IsError(builtin)) return builtin;
    Dart_Handle err = Dart_SetNativeResolver(builtin, builtin_native_lookup_shim, builtin_native_symbol_shim);
    if (Dart_IsError(err)) return err;
    Dart_Handle pc = Dart_Invoke(builtin, Dart_NewStringFromCString("_getPrintClosure"), 0, NULL);
    if (Dart_IsError(pc)) return pc;
    Dart_Handle internal = Dart_LookupLibrary(Dart_NewStringFromCString("dart:_internal"));
    if (Dart_IsError(internal)) return internal;
    return Dart_SetField(internal, Dart_NewStringFromCString("_printClosure"), pc);
}

static const char* run_one_case(
    const char* case_id,
    const char* patch_dill_path,
    const char* fn_name,
    char* errbuf, int errsz,
    FILE* dbg)
{
    if (!g_vm_initialized) {
        const char* vflags[] = {"--precompiled_mode=true"};
        char* fe = Dart_SetVMFlags(1, vflags);
        if (fe) { snprintf(errbuf, errsz, "vm_flags: %s", fe); free(fe); return NULL; }
        Dart_InitializeParams p; memset(&p, 0, sizeof(p));
        p.version = DART_INITIALIZE_PARAMS_CURRENT_VERSION;
        p.vm_snapshot_data = kDartVmSnapshotData;
        p.vm_snapshot_instructions = kDartVmSnapshotInstructions;
        char* ie = Dart_Initialize(&p);
        if (ie) { snprintf(errbuf, errsz, "dart_init: %s", ie); free(ie); return NULL; }
        g_vm_initialized = true;
    }

    // Install SIGABRT handler
    signal(SIGABRT, abort_handler);
    g_in_dart = true;
    if (sigsetjmp(g_abort_jmp, 1) != 0) {
        // Caught abort — clean up any live isolate, then continue
        snprintf(errbuf, errsz, "SIGABRT_in_%s", fn_name);
        fprintf(dbg, "[%s] CAUGHT SIGABRT in %s\n", case_id, fn_name); fflush(dbg);
        // Exit and shut down if there's still a current isolate
        if (Dart_CurrentIsolate() != NULL) {
            Dart_ExitScope();
            Dart_ShutdownIsolate();
        }
        signal(SIGABRT, abort_handler); // reinstall for next case
        g_in_dart = false;
        return NULL;
    }

    char* iso_err = NULL;
    Dart_Isolate iso = Dart_CreateIsolateGroup("vm://val", "main",
        kDartIsolateSnapshotData, kDartIsolateSnapshotInstructions,
        NULL, NULL, NULL, &iso_err);
    if (!iso) {
        snprintf(errbuf, errsz, "create_iso: %s", iso_err ? iso_err : "null");
        free(iso_err);
        g_in_dart = false;
        return NULL;
    }

    Dart_EnterScope();

    Dart_Handle sp = setup_print();
    if (Dart_IsError(sp)) {
        snprintf(errbuf, errsz, "setup_print: %s", Dart_GetError(sp));
        Dart_ExitScope(); Dart_ShutdownIsolate();
        g_in_dart = false;
        return NULL;
    }

    // Load patch dill
    FILE* f = fopen(patch_dill_path, "rb");
    if (!f) {
        snprintf(errbuf, errsz, "fopen: %s", patch_dill_path);
        Dart_ExitScope(); Dart_ShutdownIsolate();
        g_in_dart = false;
        return NULL;
    }
    fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t* buf = (uint8_t*)malloc(sz);
    fread(buf, 1, sz, f); fclose(f);
    fprintf(dbg, "[%s] loaded dill: %ld bytes\n", case_id, sz); fflush(dbg);

    Dart_Handle td = Dart_NewExternalTypedData(Dart_TypedData_kUint8, buf, sz);
    if (Dart_IsError(td)) {
        snprintf(errbuf, errsz, "typed_data: %s", Dart_GetError(td));
        free(buf); Dart_ExitScope(); Dart_ShutdownIsolate();
        g_in_dart = false;
        return NULL;
    }

    Dart_Handle patch_lib = Dart_LoadLibraryFromBytecode(td);
    if (Dart_IsError(patch_lib)) {
        snprintf(errbuf, errsz, "load_lib: %s", Dart_GetError(patch_lib));
        free(buf); Dart_ExitScope(); Dart_ShutdownIsolate();
        g_in_dart = false;
        return NULL;
    }
    fprintf(dbg, "[%s] lib loaded OK\n", case_id); fflush(dbg);

    Dart_Handle fn_result = Dart_Invoke(patch_lib, Dart_NewStringFromCString(fn_name), 0, NULL);
    free(buf);

    if (Dart_IsError(fn_result)) {
        snprintf(errbuf, errsz, "invoke_%s: %s", fn_name, Dart_GetError(fn_result));
        Dart_ExitScope(); Dart_ShutdownIsolate();
        g_in_dart = false;
        return NULL;
    }

    Dart_Handle as_str = Dart_IsString(fn_result) ? fn_result : Dart_ToString(fn_result);
    if (Dart_IsError(as_str)) {
        snprintf(errbuf, errsz, "tostring: %s", Dart_GetError(as_str));
        Dart_ExitScope(); Dart_ShutdownIsolate();
        g_in_dart = false;
        return NULL;
    }
    const char* raw = NULL;
    Dart_StringToCString(as_str, &raw);
    fprintf(dbg, "[%s] result: %s\n", case_id, raw ? raw : "(null)"); fflush(dbg);

    static char result_bufs[5][512];
    static int buf_idx = 0;
    buf_idx = (buf_idx + 1) % 5;
    strncpy(result_bufs[buf_idx], raw ? raw : "", 511);
    const char* final_result = result_bufs[buf_idx];

    Dart_ExitScope();
    Dart_ShutdownIsolate();
    g_in_dart = false;
    return final_result;
}

// -----------------------------------------------------------------------
// Spot-check cases
// T01: prim_int (int 42→100)
// T03: prim_string (string 'hello'→'world')
// T26: fn_toplevel (string 'baseline'→'patched')
// T35: cls_basic_method (add→subtract, 7→-1)
// T74: prop_a_2level (transitive propagation)
// -----------------------------------------------------------------------
typedef struct {
    const char* id;
    const char* dill_name;
    const char* fn_name;
    const char* expected;
} SpotCase;

static const SpotCase kCases[] = {
    {"T01", "t01_patch.dill", "prim_int",        "100"},
    {"T03", "t01_patch.dill", "prim_string",     "world"},
    {"T26", "t05_patch.dill", "fn_toplevel",     "patched"},
    {"T35", "t06_patch.dill", "cls_basic_method", "-1"},
    {"T74", "t14_patch.dill", "prop_a_2level",   "b_patched_via_a"},
};
#define NUM_CASES 5

static char g_all_results[16384];

const char* dart_run_all_validations_with_bundle(const char* bundle_path) {
    FILE* dbg = fopen("/tmp/val_debug.txt", "w");
    if (!dbg) dbg = stderr;

    fprintf(dbg, "dart_run_all_validations: bundle=%s\n", bundle_path); fflush(dbg);

    char* p = g_all_results;
    int rem = sizeof(g_all_results);
    int n = snprintf(p, rem, "["); p += n; rem -= n;

    int pass = 0, fail = 0;
    for (int i = 0; i < NUM_CASES; i++) {
        char dill_path[1024];
        snprintf(dill_path, sizeof(dill_path), "%s/%s", bundle_path, kCases[i].dill_name);
        fprintf(dbg, "case %s: dill=%s fn=%s expected=%s\n",
            kCases[i].id, dill_path, kCases[i].fn_name, kCases[i].expected);
        fflush(dbg);

        char errbuf[512] = "";
        const char* result = run_one_case(kCases[i].id, dill_path, kCases[i].fn_name, errbuf, sizeof(errbuf), dbg);

        bool ok = result && strcmp(result, kCases[i].expected) == 0;
        if (ok) pass++; else fail++;

        // Safely escape result/error for JSON
        char safe_result[256] = "";
        char safe_error[512] = "";
        if (result) {
            int j = 0;
            for (int k = 0; result[k] && j < 250; k++) {
                if (result[k] == '"') { safe_result[j++] = '\\'; safe_result[j++] = '"'; }
                else safe_result[j++] = result[k];
            }
        }
        {
            int j = 0;
            for (int k = 0; errbuf[k] && j < 508; k++) {
                if (errbuf[k] == '"') { safe_error[j++] = '\\'; safe_error[j++] = '"'; }
                else safe_error[j++] = errbuf[k];
            }
        }

        n = snprintf(p, rem,
            "%s{\"id\":\"%s\",\"fn\":\"%s\",\"expected\":\"%s\","
            "\"got\":\"%s\",\"pass\":%s,\"error\":\"%s\"}",
            i > 0 ? "," : "",
            kCases[i].id, kCases[i].fn_name, kCases[i].expected,
            safe_result,
            ok ? "true" : "false",
            safe_error);
        p += n; rem -= n;
    }

    n = snprintf(p, rem, "]");
    p += n; rem -= n;

    fprintf(dbg, "Summary: %d pass, %d fail\nJSON: %s\n", pass, fail, g_all_results);
    fclose(dbg);
    return g_all_results;
}

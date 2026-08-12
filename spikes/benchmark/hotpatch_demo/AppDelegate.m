#import <UIKit/UIKit.h>
#import <mach/mach_time.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include "dart_harness.h"
#include "measure.h"

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property (strong) UIWindow *window;
@end

@implementation AppDelegate

- (BOOL)application:(UIApplication *)application
    didFinishLaunchingWithOptions:(NSDictionary *)options {

    NSArray *paths = NSSearchPathForDirectoriesInDomains(
        NSDocumentDirectory, NSUserDomainMask, YES);
    NSString *docs = paths.firstObject;

    // Read metadata injected by push script
    NSString *patchSizePath = [docs stringByAppendingPathComponent:@"patch_size.txt"];
    NSString *patchTypePath = [docs stringByAppendingPathComponent:@"patch_type.txt"];
    NSString *patchModePath = [docs stringByAppendingPathComponent:@"patch_mode.txt"];

    long patchSizeBytes = 0;
    NSString *patchType = @"none";
    NSString *patchMode = @"bytecode";   // "bytecode" | "aot"

    if ([[NSFileManager defaultManager] fileExistsAtPath:patchSizePath]) {
        patchSizeBytes = [[[NSString stringWithContentsOfFile:patchSizePath
                            encoding:NSUTF8StringEncoding error:nil]
                           stringByTrimmingCharactersInSet:
                               [NSCharacterSet whitespaceAndNewlineCharacterSet]]
                          integerValue];
    }
    if ([[NSFileManager defaultManager] fileExistsAtPath:patchTypePath]) {
        patchType = [[NSString stringWithContentsOfFile:patchTypePath
                      encoding:NSUTF8StringEncoding error:nil]
                     stringByTrimmingCharactersInSet:
                         [NSCharacterSet whitespaceAndNewlineCharacterSet]];
    }
    if ([[NSFileManager defaultManager] fileExistsAtPath:patchModePath]) {
        patchMode = [[NSString stringWithContentsOfFile:patchModePath
                      encoding:NSUTF8StringEncoding error:nil]
                     stringByTrimmingCharactersInSet:
                         [NSCharacterSet whitespaceAndNewlineCharacterSet]];
    }

    // ── Cold start measurement ────────────────────────────────────────────
    // In AOT mode: pass NULL so dart_run() uses the baseline snapshot path
    // (no bytecode loading). Passing the docs dir in AOT mode would trigger
    // the ERR_NO_PATCH path which calls Dart_ShutdownIsolate(), preventing
    // subsequent dart_apply_aot_patch() calls.
    uint64_t t0 = mach_absolute_time();
    BOOL isAOT = [patchMode isEqualToString:@"aot"];
    const char *bundle_dir_arg = isAOT ? NULL : [docs UTF8String];
    const char *result = dart_run(bundle_dir_arg);
    uint64_t t1 = mach_absolute_time();

    mach_timebase_info_data_t tb;
    mach_timebase_info(&tb);
    double cold_start_ms = (double)(t1 - t0) * tb.numer / tb.denom / 1e6;

    // ── AOT patch activation + benchmark ─────────────────────────────────
    long long greet_call_ns = 0;
    NSString *variantStr = @"hotpatch_bytecode";

    if (isAOT) {
        variantStr = @"hotpatch_aot";

        // Apply AOT patch variant (pure Dart pointer update — no bytecode loading).
        int aot_variant = 0;
        if ([patchType isEqualToString:@"normal"])   aot_variant = 1;
        else if ([patchType isEqualToString:@"cpu"]) aot_variant = 2;

        if (aot_variant > 0) {
            result = dart_apply_aot_patch(aot_variant);
            NSLog(@"[BENCH/AOT] applyAOTPatch(%d) -> %s", aot_variant, result);
        }

        // Benchmark: 1000 calls (Dart-side loop), get mean microseconds
        const char *bench_us_str = dart_benchmark_greet(1000);
        double bench_us = atof(bench_us_str);
        greet_call_ns = (long long)(bench_us * 1000.0);
        NSLog(@"[BENCH/AOT] greet() Dart-side mean = %s us = %lld ns", bench_us_str, greet_call_ns);

        // C-API benchmark: N Dart_Invoke calls to AOT getResult() (same overhead as bytecode path)
        dart_benchmark_aot_capi(3);
        long long aot_capi_ns = dart_get_aot_capi_bench_ns();
        NSLog(@"[BENCH/AOT-CAPI] getResult() C-API mean = %lld ns", aot_capi_ns);
    } else {
        // Bytecode OTA path: dart_run() already ran 3-call benchmark
        greet_call_ns = dart_get_bytecode_bench_ns();
        NSLog(@"[BENCH/BYTECODE] greet() mean = %lld ns", greet_call_ns);
    }

    // ── Memory ────────────────────────────────────────────────────────────
    int64_t rss_kb = measure_rss_kb();

    // ── CPU peak (cpu patch only) ─────────────────────────────────────────
    double cpu_peak = 0.0;
    if ([patchType isEqualToString:@"cpu"]) {
        cpu_peak = measure_cpu_sample_pct();
    }

    long long aot_capi_bench_ns = isAOT ? dart_get_aot_capi_bench_ns() : 0;
    // ── Write benchmark.json ─────────────────────────────────────────────
    NSString *json = [NSString stringWithFormat:
        @"{"
         "\"variant\":\"%@\","
         "\"platform\":\"ios\","
         "\"patch_type\":\"%@\","
         "\"patch_mode\":\"%@\","
         "\"patch_size_bytes\":%ld,"
         "\"cold_start_ms\":%.3f,"
         "\"greet_call_ns\":%lld,\"aot_capi_bench_ns\":%lld,"
         "\"memory_rss_kb\":%lld,"
         "\"cpu_percent_peak\":%.1f"
         "}",
        variantStr, patchType, patchMode,
        patchSizeBytes, cold_start_ms, greet_call_ns, aot_capi_bench_ns, rss_kb, cpu_peak];

    NSString *jsonPath = [docs stringByAppendingPathComponent:@"benchmark.json"];
    [json writeToFile:jsonPath atomically:YES
             encoding:NSUTF8StringEncoding error:nil];

    NSLog(@"[BENCH] variant=%@ mode=%@ type=%@ cold=%.2fms greet=%lldns rss=%lldKB cpu=%.0f%%",
          variantStr, patchMode, patchType,
          cold_start_ms, greet_call_ns, rss_kb, cpu_peak);
    NSLog(@"[BENCH] JSON -> %@", jsonPath);

    // ── UI ───────────────────────────────────────────────────────────────
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *vc = [UIViewController new];
    vc.view.backgroundColor = [UIColor systemBackgroundColor];
    UILabel *lbl = [[UILabel alloc]
        initWithFrame:CGRectMake(20, 80,
            UIScreen.mainScreen.bounds.size.width - 40, 400)];
    lbl.text = [NSString stringWithFormat:
        @"Result: %s\nMode: %@\nType: %@\nCold: %.2f ms\ngreet: %lld ns\nRSS: %lld KB",
        result, patchMode, patchType, cold_start_ms, greet_call_ns, rss_kb];
    lbl.numberOfLines = 0;
    lbl.font = [UIFont monospacedSystemFontOfSize:14 weight:UIFontWeightRegular];
    [vc.view addSubview:lbl];
    self.window.rootViewController = vc;
    [self.window makeKeyAndVisible];
    return YES;
}

@end

int main(int argc, char *argv[]) {
    return UIApplicationMain(argc, argv, nil,
                             NSStringFromClass([AppDelegate class]));
}

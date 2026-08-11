#import <UIKit/UIKit.h>
#import <mach/mach_time.h>
#include <stdio.h>
#include "dart_harness.h"
#include "measure.h"

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property (strong) UIWindow *window;
@end

@implementation AppDelegate

- (BOOL)application:(UIApplication *)application
    didFinishLaunchingWithOptions:(NSDictionary *)options {

    NSArray *paths = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES);
    NSString *docs = paths.firstObject;

    NSString *patchSizePath = [docs stringByAppendingPathComponent:@"patch_size.txt"];
    NSString *patchTypePath = [docs stringByAppendingPathComponent:@"patch_type.txt"];

    long patchSizeBytes = 0;
    NSString *patchType = @"none";
    if ([[NSFileManager defaultManager] fileExistsAtPath:patchSizePath]) {
        patchSizeBytes = [[[NSString stringWithContentsOfFile:patchSizePath
                            encoding:NSUTF8StringEncoding error:nil]
                           stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]]
                          integerValue];
    }
    if ([[NSFileManager defaultManager] fileExistsAtPath:patchTypePath]) {
        patchType = [[NSString stringWithContentsOfFile:patchTypePath
                      encoding:NSUTF8StringEncoding error:nil]
                     stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    }

    // Cold start timer
    uint64_t t0 = mach_absolute_time();
    const char *bundle_dir = [docs UTF8String];
    const char *result = dart_run(bundle_dir);
    uint64_t t1 = mach_absolute_time();

    mach_timebase_info_data_t tb;
    mach_timebase_info(&tb);
    double cold_start_ms = (double)(t1 - t0) * tb.numer / tb.denom / 1e6;

    int64_t rss_kb = measure_rss_kb();

    double cpu_peak = 0.0;
    if ([patchType isEqualToString:@"cpu"]) {
        double peak = 0.0;
        for (int s = 0; s < 10; s++) {
            double sample = measure_cpu_sample_pct();
            if (sample > peak) peak = sample;
        }
        cpu_peak = peak;
    }

    // greet_call_us: dart_harness is single-shot, no repeated-call API → 0
    int64_t greet_call_us = 0;

    NSString *json = [NSString stringWithFormat:
        @"{"
         "\"variant\":\"hotpatch\","
         "\"platform\":\"ios\","
         "\"patch_type\":\"%@\","
         "\"patch_size_bytes\":%ld,"
         "\"cold_start_ms\":%.1f,"
         "\"greet_call_us\":%lld,"
         "\"memory_rss_kb\":%lld,"
         "\"cpu_percent_peak\":%.1f"
         "}",
        patchType, patchSizeBytes, cold_start_ms, greet_call_us, rss_kb, cpu_peak];

    NSString *jsonPath = [docs stringByAppendingPathComponent:@"benchmark.json"];
    [json writeToFile:jsonPath atomically:YES encoding:NSUTF8StringEncoding error:nil];

    NSLog(@"[BENCH] result=%s cold=%.1fms rss=%lldKB cpu=%.1f%%",
          result, cold_start_ms, rss_kb, cpu_peak);

    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *vc = [UIViewController new];
    vc.view.backgroundColor = [UIColor systemBackgroundColor];
    UILabel *lbl = [[UILabel alloc] initWithFrame:CGRectMake(20, 100,
        UIScreen.mainScreen.bounds.size.width - 40, 300)];
    lbl.text = [NSString stringWithFormat:
        @"Result: %s\nCold: %.0f ms\nRSS: %lld KB\nCPU: %.0f%%",
        result, cold_start_ms, rss_kb, cpu_peak];
    lbl.numberOfLines = 0;
    lbl.font = [UIFont monospacedSystemFontOfSize:16 weight:UIFontWeightRegular];
    [vc.view addSubview:lbl];
    self.window.rootViewController = vc;
    [self.window makeKeyAndVisible];
    return YES;
}

@end

int main(int argc, char *argv[]) {
    return UIApplicationMain(argc, argv, nil, NSStringFromClass([AppDelegate class]));
}

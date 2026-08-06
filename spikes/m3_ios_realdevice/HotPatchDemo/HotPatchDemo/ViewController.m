#import <UIKit/UIKit.h>
#include "dart_harness.h"
#include "flutter_hotpatch_updater.h"

static const char* kPatchPublicKeyHex =
    "9d2550fb40571238ee6bd8459ffa60bb2c121249abf44bebe0c1218faec9e82f";
static const char* kBuildFingerprint = "1.0+1";
/* 5-B: telemetry endpoint. Empty string = disabled. */
static NSString* const kTelemetryURL = @"";  /* set to @"http://your-server:8765/telemetry" in production */

/* 5-B: report patch health to server (anonymous, no device ID) */
static void report_telemetry(NSString* patch_id, BOOL success) {
    if (!kTelemetryURL || kTelemetryURL.length == 0) return;
    NSURL *url = [NSURL URLWithString:kTelemetryURL];
    if (!url) return;
    NSMutableURLRequest *req = [NSMutableURLRequest requestWithURL:url];
    req.HTTPMethod = @"POST";
    [req setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    NSDictionary *body = @{@"patch_id": patch_id, @"success": @(success)};
    req.HTTPBody = [NSJSONSerialization dataWithJSONObject:body options:0 error:nil];
    /* Fire-and-forget: no retry, no error handling -- telemetry is best-effort */
    [[NSURLSession.sharedSession dataTaskWithRequest:req] resume];
    NSLog(@"[5B] telemetry: patch_id=%@ success=%d", patch_id, (int)success);
}

@interface ViewController : UIViewController
@end

@implementation ViewController

- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.systemBackgroundColor;

    /* fhp_init was moved to AppDelegate.didFinishLaunchingWithOptions (Shorebird-aligned).
       Boot-loop watchdog and blacklist check already ran before this point. */

    /* 5-B: if Updater auto-rolled-back (boot-loop), report crash */
    const char* stateJson = fhp_state_json();
    NSString *stateStr = stateJson ? @(stateJson) : @"{}";
    fhp_free_string(stateJson);
    NSDictionary *state = [NSJSONSerialization JSONObjectWithData:
        [stateStr dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil] ?: @{};
    NSArray *blacklist = state[@"blacklist"] ?: @[];
    if (blacklist.count > 0) {
        /* Last patch was blacklisted -- report crash for the most recently blacklisted id */
        report_telemetry(blacklist.lastObject, NO);
    }

    /* Stage bundled patch if not already staged */
    const char* nextBootDir = fhp_get_next_boot_patch_dir();
    if (!nextBootDir) {
        NSString *bundlePatchDir = [[[NSBundle mainBundle] bundlePath]
            stringByAppendingPathComponent:@"patch_bundle"];
        if ([[NSFileManager defaultManager] fileExistsAtPath:bundlePatchDir]) {
            fhp_stage_patch([bundlePatchDir UTF8String], kPatchPublicKeyHex);
            nextBootDir = fhp_get_next_boot_patch_dir();
        }
    }
    NSLog(@"[ViewController] next_boot_patch: %s", nextBootDir ? nextBootDir : "(null — baseline)");

    /* Run Dart */
    const char *cResult = dart_run(nextBootDir);
    NSLog(@"[ViewController] Dart result: %s", cResult ? cResult : "(nil)");

    /* Confirm health + report success telemetry */
    fhp_confirm_health();

    /* 5-B: report success for active patch (if any) */
    if (nextBootDir) {
        NSString *manifestPath = [NSString stringWithFormat:@"%s/manifest.json", nextBootDir];
        NSData *mData = [NSData dataWithContentsOfFile:manifestPath];
        if (mData) {
            NSDictionary *manifest = [NSJSONSerialization JSONObjectWithData:mData
                options:0 error:nil];
            NSString *patchId = manifest[@"patch_id"] ?: @"unknown";
            report_telemetry(patchId, YES);
        }
        fhp_free_string(nextBootDir);
    }

    NSString *result = [NSString stringWithUTF8String:cResult ? cResult : "ERROR"];
    UILabel *label = [[UILabel alloc] initWithFrame:CGRectInset(self.view.bounds, 20, 0)];
    label.text = result;
    label.font = [UIFont systemFontOfSize:28 weight:UIFontWeightMedium];
    label.textAlignment = NSTextAlignmentCenter;
    label.numberOfLines = 0;
    label.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    [self.view addSubview:label];

    /* Write result for devicectl retrieval */
    NSArray *docPaths = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES);
    NSString *docDir = [docPaths firstObject];
    NSString *diagContent = [NSString stringWithFormat:@"result=%s\nbuild_fp=%s",
        cResult ? cResult : "nil", kBuildFingerprint];
    [diagContent writeToFile:[docDir stringByAppendingPathComponent:@"result.txt"]
        atomically:YES encoding:NSUTF8StringEncoding error:nil];
}

@end

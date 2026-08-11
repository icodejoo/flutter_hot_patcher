#import <UIKit/UIKit.h>
#include <stdint.h>
#include "flutter_hotpatch_updater.h"
#include "dart_harness.h"

/* B-route: base snapshot symbols (defined in snapshot.S) */
extern const uint8_t kDartIsolateSnapshotData[];

static NSString* kBuildFingerprint = @"1.0+1";
static NSString* _serverURLFromPlist(void) {
    NSDictionary *info = [[NSBundle mainBundle] infoDictionary];
    NSString *url = info[@"HotPatchServerURL"];
    return url.length ? url : @"http://localhost:8765";
}
#define kServerURL _serverURLFromPlist()
/* kAppId and kChannel reserved for fhp_check_update / fhp_download_and_stage (Task 1) */
static NSString* kAppId = @"com.hotpatch.demo";
static NSString* kChannel = @"stable";

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property (strong, nonatomic) UIWindow *window;
@end

@implementation AppDelegate

- (BOOL)application:(UIApplication*)app didFinishLaunchingWithOptions:(NSDictionary*)opts {
    /* STEP 1: Init updater BEFORE Dart VM (Shorebird-aligned boot sequence) */
    NSArray *dataPaths = NSSearchPathForDirectoriesInDomains(
        NSApplicationSupportDirectory, NSUserDomainMask, YES);
    NSString *dataDir = [[dataPaths firstObject]
        stringByAppendingPathComponent:@"HotPatchUpdater"];
    NSError *dirError = nil;
    [[NSFileManager defaultManager] createDirectoryAtPath:dataDir
        withIntermediateDirectories:YES attributes:nil error:&dirError];
    if (dirError) {
        NSLog(@"[AppDelegate] WARNING: failed to create data dir: %@", dirError.localizedDescription);
    }

    _logPath = [dataDir stringByAppendingPathComponent:@"ota_debug.log"];
    [[NSFileManager defaultManager] removeItemAtPath:_logPath error:nil]; // 每次启动清空

    fhp_init([dataDir UTF8String], [kBuildFingerprint UTF8String]);
    fhpLog([NSString stringWithFormat:@"[AppDelegate] fhp_init complete (dataDir=%@)", dataDir]);
    const char* _nextBootDir = fhp_get_next_boot_patch_dir();
    fhpLog([NSString stringWithFormat:@"[AppDelegate] next_boot_dir: %s", _nextBootDir ? _nextBootDir : "(null)"]);
    if (_nextBootDir) fhp_free_string(_nextBootDir);

    /* STEP 2: Background patch check (non-blocking) */
    [self _checkForUpdatesInBackground];

    /* STEP 3: Launch UI (ViewController will read next_boot_patch and start Dart) */
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *rootVC = [[NSClassFromString(@"ViewController") alloc] init];
    self.window.rootViewController = rootVC;
    [self.window makeKeyAndVisible];
    return YES;
}

static NSString* _logPath = nil;
static void fhpLog(NSString* msg) {
    NSString *line = [NSString stringWithFormat:@"%@  %@\n", [NSDate date], msg];
    NSLog(@"%@", msg);
    if (_logPath) {
        NSFileHandle *fh = [NSFileHandle fileHandleForWritingAtPath:_logPath];
        if (!fh) {
            [@"" writeToFile:_logPath atomically:NO encoding:NSUTF8StringEncoding error:nil];
            fh = [NSFileHandle fileHandleForWritingAtPath:_logPath];
        }
        [fh seekToEndOfFile];
        [fh writeData:[line dataUsingEncoding:NSUTF8StringEncoding]];
        [fh closeFile];
    }
}

- (void)_checkForUpdatesInBackground {
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0), ^{
        NSString *url = kServerURL;
        fhpLog([NSString stringWithFormat:@"[Updater] START checking %@", url]);

        // Flush queued crash events
        fhpLog(@"[Updater] calling fhp_flush_events...");
        fhp_flush_events([url UTF8String]);
        fhpLog(@"[Updater] fhp_flush_events done");

        fhpLog(@"[Updater] calling fhp_check_update...");
        const char* responseJson = fhp_check_update(
            [url UTF8String],
            [kAppId UTF8String],
            [kBuildFingerprint UTF8String],
            [kChannel UTF8String]
        );
        fhpLog(@"[Updater] fhp_check_update returned");
        if (!responseJson) {
            fhpLog(@"[Updater] Check failed (null response)");
            return;
        }

        NSString *jsonStr = @(responseJson);
        fhpLog([NSString stringWithFormat:@"[Updater] raw response: %.200@", jsonStr]);
        NSData *data = [jsonStr dataUsingEncoding:NSUTF8StringEncoding];
        fhp_free_string(responseJson);

        NSError *jsonErr = nil;
        NSDictionary *resp = [NSJSONSerialization JSONObjectWithData:data options:0 error:&jsonErr];
        if (!resp) {
            NSLog(@"[Updater] JSON parse error: %@", jsonErr.localizedDescription);
            return;
        }
        fhpLog([NSString stringWithFormat:@"[Updater] patch_available=%@", resp[@"patch_available"]]);
        if (![resp[@"patch_available"] boolValue]) return;

        NSDictionary *patch = resp[@"patch"];
        NSString *downloadUrl = patch[@"download_url"];
        NSString *hash = patch[@"hash"] ?: @"";
        NSNumber *patchNumber = patch[@"number"];
        if (!downloadUrl || !patchNumber) return;

        NSString *patchType = patch[@"patch_type"] ?: @"bytecode";
        fhpLog([NSString stringWithFormat:@"[Updater] Patch #%@ type=%@ url=%@", patchNumber, patchType, downloadUrl]);

        static const char* kPubKeyHex = "70fe9e96bec44e7a6ab78f98fd6e931cd550b615fab4cd501053e80c72f8ef55";

        if ([patchType isEqualToString:@"vmcode"]) {
            /* B-route: download .vmdiff and apply with bipatch */
            [self _stageVmcodePatch:patch serverUrl:url];
        } else {
            /* A-route: download full bundle.zst */
            int result = fhp_download_and_stage(
                [downloadUrl UTF8String],
                [hash UTF8String],
                "",
                [patchNumber intValue],
                kPubKeyHex
            );
            if (result == 0) {
                fhpLog([NSString stringWithFormat:@"[Updater] Patch #%@ staged OK. Cold restart to apply.", patchNumber]);
            } else {
                fhpLog([NSString stringWithFormat:@"[Updater] Stage failed: %d", result]);
            }
        }
    });
}

- (void)_stageVmcodePatch:(NSDictionary*)patch serverUrl:(NSString*)serverUrl {
    NSString *downloadUrl  = patch[@"download_url"];
    NSNumber *patchNumber  = patch[@"number"];
    NSNumber *isoDataSize  = patch[@"isolate_data_size"];
    if (!downloadUrl || !patchNumber || !isoDataSize) {
        fhpLog(@"[Vmcode] missing required fields in patch manifest");
        return;
    }

    // Temp path for downloaded diff
    NSArray *dataPaths = NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSUserDomainMask, YES);
    NSString *dataDir  = [[dataPaths firstObject] stringByAppendingPathComponent:@"HotPatchUpdater"];
    NSString *diffPath = [dataDir stringByAppendingPathComponent:@"vmcode_download.vmdiff"];
    NSString *stagedPath = [dataDir stringByAppendingPathComponent:
                            [NSString stringWithFormat:@"vmcode_%@_isolate_data.bin", patchNumber]];

    // Download .vmdiff
    fhpLog([NSString stringWithFormat:@"[Vmcode] downloading diff from %@", downloadUrl]);
    NSData *diffData = [NSData dataWithContentsOfURL:[NSURL URLWithString:downloadUrl]];
    if (!diffData) {
        fhpLog(@"[Vmcode] download failed");
        return;
    }
    [diffData writeToFile:diffPath atomically:YES];
    fhpLog([NSString stringWithFormat:@"[Vmcode] downloaded %lu bytes", (unsigned long)diffData.length]);

    // Apply bipatch: base = kDartIsolateSnapshotData (in-memory from snapshot.S)
    unsigned long baseLen = [isoDataSize unsignedLongValue];
    int result = fhp_vmcode_stage(
        kDartIsolateSnapshotData,
        baseLen,
        [diffPath UTF8String],
        [stagedPath UTF8String]
    );
    if (result != 0) {
        fhpLog([NSString stringWithFormat:@"[Vmcode] fhp_vmcode_stage failed: %d", result]);
        return;
    }

    // Write metadata for boot-time loading
    NSString *metaPath = [dataDir stringByAppendingPathComponent:@"vmcode_staged.json"];
    NSDictionary *meta = @{
        @"patch_number": patchNumber,
        @"staged_path":  stagedPath,
        @"patch_type":   @"vmcode"
    };
    NSData *metaData = [NSJSONSerialization dataWithJSONObject:meta options:0 error:nil];
    [metaData writeToFile:metaPath atomically:YES];
    fhpLog([NSString stringWithFormat:@"[Vmcode] patch #%@ staged → %@. Cold restart to apply.", patchNumber, stagedPath]);
}

@end

int main(int argc, char *argv[]) {
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil, NSStringFromClass([AppDelegate class]));
    }
}

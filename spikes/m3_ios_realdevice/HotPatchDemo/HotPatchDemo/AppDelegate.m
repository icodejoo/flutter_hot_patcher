#import <UIKit/UIKit.h>
#include "flutter_hotpatch_updater.h"

static NSString* kBuildFingerprint = @"1.0+1";
static NSString* kServerURL = @"https://stock-honey-multimedia-sea.trycloudflare.com"; // Cloudflare tunnel // USB en7 IPv4 // TODO: replace hardcoded IP with plist config
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

    fhp_init([dataDir UTF8String], [kBuildFingerprint UTF8String]);
    NSLog(@"[AppDelegate] fhp_init complete (dataDir=%@)", dataDir);

    /* STEP 2: Background patch check (non-blocking) */
    [self _checkForUpdatesInBackground];

    /* STEP 3: Launch UI (ViewController will read next_boot_patch and start Dart) */
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *rootVC = [[NSClassFromString(@"ViewController") alloc] init];
    self.window.rootViewController = rootVC;
    [self.window makeKeyAndVisible];
    return YES;
}

- (void)_checkForUpdatesInBackground {
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_BACKGROUND, 0), ^{
        NSLog(@"[Updater] Checking %@ for updates...", kServerURL);

        const char* responseJson = fhp_check_update(
            [kServerURL UTF8String],
            [kAppId UTF8String],
            [kBuildFingerprint UTF8String],
            [kChannel UTF8String]
        );
        if (!responseJson) {
            NSLog(@"[Updater] Check failed (null response)");
            return;
        }

        NSString *jsonStr = @(responseJson);
        NSLog(@"[Updater] raw response: %.200@", jsonStr);
        NSData *data = [jsonStr dataUsingEncoding:NSUTF8StringEncoding];
        fhp_free_string(responseJson);

        NSError *jsonErr = nil;
        NSDictionary *resp = [NSJSONSerialization JSONObjectWithData:data options:0 error:&jsonErr];
        if (!resp) {
            NSLog(@"[Updater] JSON parse error: %@", jsonErr.localizedDescription);
            return;
        }
        NSLog(@"[Updater] patch_available=%@", resp[@"patch_available"]);
        if (![resp[@"patch_available"] boolValue]) return;

        NSDictionary *patch = resp[@"patch"];
        NSString *downloadUrl = patch[@"download_url"];
        NSString *hash = patch[@"hash"] ?: @"";
        NSNumber *patchNumber = patch[@"number"];
        if (!downloadUrl || !patchNumber) return;

        NSLog(@"[Updater] Downloading patch #%@ ...", patchNumber);

        static const char* kPubKeyHex = "70fe9e96bec44e7a6ab78f98fd6e931cd550b615fab4cd501053e80c72f8ef55";

        int result = fhp_download_and_stage(
            [downloadUrl UTF8String],
            [hash UTF8String],
            "",
            [patchNumber intValue],
            kPubKeyHex
        );
        if (result == 0) {
            NSLog(@"[Updater] Patch #%@ staged. Cold restart to apply.", patchNumber);
        } else {
            NSLog(@"[Updater] Stage failed: %d", result);
        }
    });
}

@end

int main(int argc, char *argv[]) {
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil, NSStringFromClass([AppDelegate class]));
    }
}

#import <UIKit/UIKit.h>
#include "flutter_hotpatch_updater.h"

static NSString* kBuildFingerprint = @"1.0+1";
static NSString* kServerURL = @"http://192.168.1.100:8765";
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
    [[NSFileManager defaultManager] createDirectoryAtPath:dataDir
        withIntermediateDirectories:YES attributes:nil error:nil];

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
        NSLog(@"[Updater] Background patch check starting (server: %@)", kServerURL);
        /* TODO(Task 1): call fhp_check_update(kServerURL, kAppId, kChannel) then
           fhp_download_and_stage() once those FFI functions are integrated via
           libflutter_hotpatch_updater.a -- not yet declared in flutter_hotpatch_updater.h */
        (void)kAppId; (void)kChannel; /* suppress unused-variable warnings until Task 1 */
    });
}

@end

int main(int argc, char *argv[]) {
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil, NSStringFromClass([AppDelegate class]));
    }
}

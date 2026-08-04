#import <UIKit/UIKit.h>
#include "dart_harness.h"

@interface ViewController : UIViewController
@end

@implementation ViewController

- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.systemBackgroundColor;

    NSUserDefaults *ud = NSUserDefaults.standardUserDefaults;
    NSString *status = [ud stringForKey:@"patch_status"];
    BOOL patchBad = [status isEqualToString:@"loading"];
    if (patchBad) {
        [ud setObject:@"bad" forKey:@"patch_status"];
        [ud synchronize];
    }
    BOOL usePatch = !patchBad && ![status isEqualToString:@"bad"];

    NSLog(@"[M3] patch_status=%@ patchBad=%d usePatch=%d", status, (int)patchBad, (int)usePatch);

    [ud setObject:@"loading" forKey:@"patch_status"];
    [ud synchronize];

    NSString *patchPath = nil;
    if (usePatch) {
        patchPath = [[NSBundle mainBundle] pathForResource:@"patch" ofType:@"dill"];
        if (!patchPath) NSLog(@"[M3] WARNING: patch.dill not found in bundle");
    }
    const char *cResult = dart_run(usePatch ? 1 : 0, patchPath ? patchPath.UTF8String : NULL);

    [ud setObject:@"ok" forKey:@"patch_status"];
    [ud synchronize];

    NSString *result = [NSString stringWithUTF8String:cResult];
    NSLog(@"[M3] Dart result: %@", result);

    UILabel *label = [[UILabel alloc] initWithFrame:CGRectInset(self.view.bounds, 20, 0)];
    label.text = result;
    label.font = [UIFont systemFontOfSize:28 weight:UIFontWeightMedium];
    label.textAlignment = NSTextAlignmentCenter;
    label.numberOfLines = 0;
    label.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    [self.view addSubview:label];
}

@end

#import <UIKit/UIKit.h>
#include "dart_harness.h"

@interface ViewController : UIViewController
@end

@implementation ViewController

- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.systemBackgroundColor;

    /* --- Crash guard --- */
    NSUserDefaults *ud = NSUserDefaults.standardUserDefaults;
    NSString *status = [ud stringForKey:@"patch_status"];
    BOOL patchBad = [status isEqualToString:@"loading"];
    if (patchBad) {
        [ud setObject:@"bad" forKey:@"patch_status"];
        [ud synchronize];
    }
    BOOL usePatch = !patchBad && ![status isEqualToString:@"bad"];

    /* Mark "loading" before touching Dart VM */
    [ud setObject:@"loading" forKey:@"patch_status"];
    [ud synchronize];

    /* Run Dart */
    const char *cResult = dart_run(usePatch ? 1 : 0);

    /* Mark "ok" — survived */
    [ud setObject:@"ok" forKey:@"patch_status"];
    [ud synchronize];

    /* Show result */
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

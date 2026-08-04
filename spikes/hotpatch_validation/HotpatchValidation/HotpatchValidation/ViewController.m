#import <UIKit/UIKit.h>

extern const char* dart_run_all_validations_with_bundle(const char* bundle_path);

@interface ViewController : UIViewController
@end

@implementation ViewController

- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = [UIColor systemBackgroundColor];

    NSArray* docPaths = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES);
    NSString* docDir = [docPaths firstObject];

    NSLog(@"[VAL] Starting validation, bundle=%@", [[NSBundle mainBundle] bundlePath]);
    NSLog(@"[VAL] Documents dir=%@", docDir);

    NSString* bundlePath = [[NSBundle mainBundle] bundlePath];

    // Write start marker before Dart runs
    [@"starting" writeToFile:[docDir stringByAppendingPathComponent:@"val_status.txt"]
        atomically:YES encoding:NSUTF8StringEncoding error:nil];

    const char* results_json = dart_run_all_validations_with_bundle([bundlePath UTF8String]);
    NSString* json = results_json ? @(results_json) : @"[{\"error\":\"null_return\"}]";

    NSLog(@"[VAL] Results JSON: %@", json);

    // Write results
    NSString* outPath = [docDir stringByAppendingPathComponent:@"val_results.json"];
    [[json dataUsingEncoding:NSUTF8StringEncoding] writeToFile:outPath atomically:YES];
    [@"done" writeToFile:[docDir stringByAppendingPathComponent:@"val_status.txt"]
        atomically:YES encoding:NSUTF8StringEncoding error:nil];

    NSLog(@"[VAL] Written to: %@", outPath);

    // Copy debug log from /tmp to Documents if it exists
    NSString* tmpDbg = @"/tmp/val_debug.txt";
    if ([[NSFileManager defaultManager] fileExistsAtPath:tmpDbg]) {
        NSString* docDbg = [docDir stringByAppendingPathComponent:@"val_debug.txt"];
        [[NSFileManager defaultManager] copyItemAtPath:tmpDbg toPath:docDbg error:nil];
        NSLog(@"[VAL] Debug log copied to Documents");
    }

    // Parse for display
    NSArray* cases = [NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding]
        options:0 error:nil] ?: @[];
    int pass = 0, fail = 0;
    for (NSDictionary* c in cases) {
        if ([c[@"pass"] boolValue]) pass++; else fail++;
    }
    NSString* summary = [NSString stringWithFormat:@"Validation: %d/5 pass, %d fail\n%@", pass, fail, json];

    UILabel* label = [[UILabel alloc] initWithFrame:CGRectInset(self.view.bounds, 16, 60)];
    label.text = summary;
    label.font = [UIFont monospacedSystemFontOfSize:11 weight:UIFontWeightRegular];
    label.textAlignment = NSTextAlignmentLeft;
    label.numberOfLines = 0;
    label.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    [self.view addSubview:label];
}

@end

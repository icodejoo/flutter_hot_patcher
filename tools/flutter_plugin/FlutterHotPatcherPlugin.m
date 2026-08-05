#import "FlutterHotPatcherPlugin.h"
#include "flutter_hotpatch_updater.h"

@implementation FlutterHotPatcherPlugin
+ (void)registerWithRegistrar:(NSObject<FlutterPluginRegistrar>*)registrar {
  FlutterMethodChannel* channel = [FlutterMethodChannel
      methodChannelWithName:@"flutter_hot_patcher_plugin"
            binaryMessenger:[registrar messenger]];
  FlutterHotPatcherPlugin* instance = [[FlutterHotPatcherPlugin alloc] init];
  [registrar addMethodCallDelegate:instance channel:channel];
}

- (void)handleMethodCall:(FlutterMethodCall*)call result:(FlutterResult)result {
  if ([@"init" isEqualToString:call.method]) {
    NSString *dataDir = call.arguments[@"dataDir"];
    NSString *fingerprint = call.arguments[@"fingerprint"];
    int r = fhp_init([dataDir UTF8String], [fingerprint UTF8String]);
    result(@(r));

  } else if ([@"stagePatch" isEqualToString:call.method]) {
    NSString *bundleDir = call.arguments[@"bundleDir"];
    NSString *pubkeyHex = call.arguments[@"pubkeyHex"];
    int r = fhp_stage_patch([bundleDir UTF8String], [pubkeyHex UTF8String]);
    result(@(r));

  } else if ([@"getNextBootPatchDir" isEqualToString:call.method]) {
    const char *dir = fhp_get_next_boot_patch_dir();
    if (dir) {
      NSString *s = [NSString stringWithUTF8String:dir];
      fhp_free_string(dir);
      result(s);
    } else {
      result([NSNull null]);
    }

  } else if ([@"confirmHealth" isEqualToString:call.method]) {
    fhp_confirm_health();
    result(@YES);

  } else if ([@"getStateJson" isEqualToString:call.method]) {
    const char *json = fhp_state_json();
    NSString *s = json ? [NSString stringWithUTF8String:json] : @"{}";
    fhp_free_string(json);
    result(s);

  } else {
    result(FlutterMethodNotImplemented);
  }
}
@end

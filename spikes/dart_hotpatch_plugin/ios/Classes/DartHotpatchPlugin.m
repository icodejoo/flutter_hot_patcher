#import "DartHotpatchPlugin.h"
#include <dlfcn.h>

// Dart C API types (from dart_api.h)
typedef void* Dart_Handle;
typedef Dart_Handle (*Dart_LoadLibraryFromBytecodeFn)(const uint8_t*, intptr_t);
typedef bool (*Dart_IsErrorFn)(Dart_Handle);
typedef const char* (*Dart_GetErrorFn)(Dart_Handle);

@implementation DartHotpatchPlugin

+ (void)registerWithRegistrar:(NSObject<FlutterPluginRegistrar>*)registrar {
    FlutterMethodChannel* channel = [FlutterMethodChannel
        methodChannelWithName:@"dart_hotpatch_plugin"
              binaryMessenger:[registrar messenger]];
    DartHotpatchPlugin* instance = [[DartHotpatchPlugin alloc] init];
    [registrar addMethodCallDelegate:instance channel:channel];
}

- (void)handleMethodCall:(FlutterMethodCall*)call result:(FlutterResult)result {
    if ([@"getEngineCapabilities" isEqualToString:call.method]) {
        void* loadLibSym = dlsym(RTLD_DEFAULT, "Dart_LoadLibraryFromBytecode");
        void* loadDynSym = dlsym(RTLD_DEFAULT, "Dart_DynamicModuleLoader_LoadModule");
        
        NSMutableString* info = [NSMutableString string];
        [info appendString:@"=== Flutter Engine Capabilities ===\n"];
        [info appendFormat:@"Dart_LoadLibraryFromBytecode: %@\n",
            loadLibSym ? @"✅ PRESENT" : @"❌ MISSING"];
        [info appendFormat:@"Build date: %s %s\n", __DATE__, __TIME__];
        
        result(info);
        
    } else if ([@"testLoadBytecode" isEqualToString:call.method]) {
        FlutterStandardTypedData* data = call.arguments[@"bytecode"];
        if (!data) {
            result([FlutterError errorWithCode:@"INVALID_ARGUMENT"
                                       message:@"bytecode argument required"
                                       details:nil]);
            return;
        }
        
        Dart_LoadLibraryFromBytecodeFn loadLib = 
            (Dart_LoadLibraryFromBytecodeFn)dlsym(RTLD_DEFAULT, "Dart_LoadLibraryFromBytecode");
        
        if (!loadLib) {
            result([FlutterError errorWithCode:@"NOT_AVAILABLE"
                                       message:@"Dart_LoadLibraryFromBytecode not found. "
                                               @"Is dart_dynamic_modules=true engine used?"
                                       details:nil]);
            return;
        }
        
        Dart_IsErrorFn isError = (Dart_IsErrorFn)dlsym(RTLD_DEFAULT, "Dart_IsError");
        Dart_GetErrorFn getError = (Dart_GetErrorFn)dlsym(RTLD_DEFAULT, "Dart_GetError");
        
        NSLog(@"[HotpatchPlugin] Calling Dart_LoadLibraryFromBytecode with %lu bytes",
              (unsigned long)data.data.length);
        
        Dart_Handle handle = loadLib(
            (const uint8_t*)data.data.bytes,
            (intptr_t)data.data.length
        );
        
        if (isError && isError(handle)) {
            const char* errMsg = getError ? getError(handle) : "unknown error";
            NSString* msg = [NSString stringWithUTF8String:errMsg ?: "null"];
            NSLog(@"[HotpatchPlugin] Error: %@", msg);
            // Note: Error is EXPECTED for dummy/invalid bytecode
            // But the API being callable means our engine has dart_dynamic_modules!
            result([NSString stringWithFormat:@"API_CALLABLE:ERROR:%@", msg]);
        } else {
            NSLog(@"[HotpatchPlugin] Success!");
            result(@"API_CALLABLE:SUCCESS");
        }
        
    } else {
        result(FlutterMethodNotImplemented);
    }
}

@end

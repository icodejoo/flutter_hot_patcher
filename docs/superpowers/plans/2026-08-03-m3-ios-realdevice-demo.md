# M3 iOS 真机 Demo 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 iOS 真机上跑通 V2 redirect hotpatch demo——app 显示 ORIGINAL 或 PATCHED，支持 crash-guard 回滚。

**Architecture:** 基于 Sim demo 的 C 嵌入模型（dart_harness.c + builtin_shim.cpp + snapshot.S），换 iphoneos SDK 编译，打包成签名 iOS App，UILabel 显示 Dart greet() 返回值。snapshot 用 host ReleaseARM64 gen_snapshot_product 生成（相同 arm64 ISA），VM .o 文件用 ninja 重新编译。

**Tech Stack:** Dart SDK（~/dart/sdk @ 1aa7d7321fb），Xcode 26.6，iOS 26.5 SDK，xcrun devicectl，ObjC/C/C++

---

## 环境常量（全文复用）

```
DART_SDK=~/dart/sdk
HOST_OUT=$DART_SDK/xcodebuild/ReleaseARM64
IOS_OUT=$DART_SDK/xcodebuild/ReleaseIosARM64
SPIKE=~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice
TEAM_ID=28VANPL49P          # iPhone Developer: you Shaw
BUNDLE_ID=org.hotpatch.m3demo
DEVICE_ID=040F89ED-E7CC-54B0-A7BB-908EE82C0224  # iPhone 14, available+paired
```

---

## Task 1: 创建 spike 目录和 Dart 源码

**Files:**
- Create: `spikes/m3_ios_realdevice/greet.dart`
- Create: `spikes/m3_ios_realdevice/patch_greet.dart`

- [ ] **Step 1: 创建目录**

```bash
mkdir -p ~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice
cd ~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice
```

- [ ] **Step 2: 写 greet.dart**

```bash
cat > greet.dart << 'DART_EOF'
library;

import 'dart:_internal' as internal;

@pragma('vm:never-inline')
String greet() => 'ORIGINAL';

@pragma('vm:never-inline')
String greetPatched() => 'PATCHED';

late String Function() greetVar;

@pragma('vm:never-inline')
String callGreet() => greetVar();

@pragma('vm:entry-point')
void setup(List args) {  /* List<dynamic>: Dart_NewList returns untyped List */
  greetVar = greet;
  if (args.contains('--patch')) {
    internal.redirectClosureEntryPoint(greetVar, greetPatched);
  }
}

@pragma('vm:entry-point')
String getResult() => callGreet();
DART_EOF
```

- [ ] **Step 3: 写 patch_greet.dart（供 dart2bytecode 打包，M4 后实际使用）**

```bash
cat > patch_greet.dart << 'DART_EOF'
library;

@pragma('dyn-module:entry-point')
String greet() => 'PATCHED';
DART_EOF
```

- [ ] **Step 4: 写 builtin_shim.cpp（与 Sim demo 完全一致）**

```bash
cat > builtin_shim.cpp << 'CPP_EOF'
#include "dart_api.h"

namespace dart { namespace bin {
class Builtin {
public:
    static Dart_NativeFunction NativeLookup(Dart_Handle name, int argument_count, bool* auto_setup_scope);
    static const uint8_t* NativeSymbol(Dart_NativeFunction nf);
};
} }

extern "C" {
    Dart_NativeFunction builtin_native_lookup_shim(Dart_Handle name, int argument_count, bool* auto_setup_scope) {
        return dart::bin::Builtin::NativeLookup(name, argument_count, auto_setup_scope);
    }
    const uint8_t* builtin_native_symbol_shim(Dart_NativeFunction nf) {
        return dart::bin::Builtin::NativeSymbol(nf);
    }
}
CPP_EOF
```

- [ ] **Step 5: 写 dart_harness.h**

```bash
cat > dart_harness.h << 'H_EOF'
#pragma once
#ifdef __cplusplus
extern "C" {
#endif

/* Returns "ORIGINAL" or "PATCHED". Caller must not free. */
const char* dart_run(int use_patch);

#ifdef __cplusplus
}
#endif
H_EOF
```

- [ ] **Step 6: 写 dart_harness.c**

```bash
cat > dart_harness.c << 'C_EOF'
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include "dart_api.h"
#include "dart_harness.h"

extern const uint8_t kDartIsolateSnapshotData[];
extern const uint8_t kDartIsolateSnapshotInstructions[];
extern const uint8_t kDartVmSnapshotData[];
extern const uint8_t kDartVmSnapshotInstructions[];

extern Dart_NativeFunction builtin_native_lookup_shim(Dart_Handle name, int argument_count, bool* auto_setup_scope);
extern const uint8_t* builtin_native_symbol_shim(Dart_NativeFunction nf);

#define CHK(h) do { \
    if (Dart_IsError(h)) { \
        fprintf(stderr, "[DART ERR] %s\n", Dart_GetError(h)); \
        Dart_ExitScope(); \
        Dart_ShutdownIsolate(); \
        return "ERROR"; \
    } \
} while(0)

static bool g_initialized = false;
static char g_result[256] = "UNKNOWN";

static Dart_Handle setup_print(void) {
    Dart_Handle builtin = Dart_LookupLibrary(Dart_NewStringFromCString("dart:_builtin"));
    if (Dart_IsError(builtin)) return builtin;
    Dart_Handle err = Dart_SetNativeResolver(builtin, builtin_native_lookup_shim, builtin_native_symbol_shim);
    if (Dart_IsError(err)) return err;
    Dart_Handle print_closure = Dart_Invoke(builtin, Dart_NewStringFromCString("_getPrintClosure"), 0, NULL);
    if (Dart_IsError(print_closure)) return print_closure;
    Dart_Handle internal = Dart_LookupLibrary(Dart_NewStringFromCString("dart:_internal"));
    if (Dart_IsError(internal)) return internal;
    return Dart_SetField(internal, Dart_NewStringFromCString("_printClosure"), print_closure);
}

const char* dart_run(int use_patch) {
    if (!g_initialized) {
        const char* vflags[] = {"--precompiled_mode=true"};
        char* fe = Dart_SetVMFlags(1, vflags);
        if (fe) { fprintf(stderr, "[ERR] flags: %s\n", fe); free(fe); return "ERROR"; }

        Dart_InitializeParams p; memset(&p, 0, sizeof(p));
        p.version = DART_INITIALIZE_PARAMS_CURRENT_VERSION;
        p.vm_snapshot_data = kDartVmSnapshotData;
        p.vm_snapshot_instructions = kDartVmSnapshotInstructions;
        char* ie = Dart_Initialize(&p);
        if (ie) { fprintf(stderr, "[ERR] Init: %s\n", ie); free(ie); return "ERROR"; }
        g_initialized = true;
    }

    char* err = NULL;
    Dart_Isolate iso = Dart_CreateIsolateGroup(
        "vm://hotpatch", "main",
        kDartIsolateSnapshotData, kDartIsolateSnapshotInstructions,
        NULL, NULL, NULL, &err);
    if (!iso) { fprintf(stderr, "[ERR] CreateIsolate: %s\n", err ? err : "null"); free(err); return "ERROR"; }

    Dart_EnterScope();
    Dart_Handle setup_r = setup_print();
    CHK(setup_r);

    Dart_Handle root_lib = Dart_RootLibrary();
    CHK(root_lib);

    /* Call setup([] or ['--patch']) */
    Dart_Handle arg_list = Dart_NewList(use_patch ? 1 : 0);
    CHK(arg_list);
    if (use_patch) {
        Dart_ListSetAt(arg_list, 0, Dart_NewStringFromCString("--patch"));
    }
    Dart_Handle setup_args[1] = {arg_list};
    Dart_Handle setup_fn = Dart_GetField(root_lib, Dart_NewStringFromCString("setup"));
    CHK(setup_fn);
    Dart_Handle setup_res = Dart_InvokeClosure(setup_fn, 1, setup_args);
    CHK(setup_res);

    /* Call getResult() → string */
    Dart_Handle get_fn = Dart_GetField(root_lib, Dart_NewStringFromCString("getResult"));
    CHK(get_fn);
    Dart_Handle result_h = Dart_InvokeClosure(get_fn, 0, NULL);
    CHK(result_h);

    const char* result_str = NULL;
    Dart_StringToCString(result_h, &result_str);
    strncpy(g_result, result_str ? result_str : "NULL", 255);

    Dart_ExitScope();
    Dart_ShutdownIsolate();
    return g_result;
}
C_EOF
```

- [ ] **Step 7: 写 Info.plist**

```bash
cat > Info.plist << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>org.hotpatch.m3demo</string>
    <key>CFBundleName</key>
    <string>HotPatchDemo</string>
    <key>CFBundleExecutable</key>
    <string>HotPatchDemo</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSRequiresIPhoneOS</key>
    <true/>
    <key>UILaunchStoryboardName</key>
    <string>LaunchScreen</string>
    <key>UIRequiredDeviceCapabilities</key>
    <array>
        <string>arm64</string>
    </array>
    <key>MinimumOSVersion</key>
    <string>16.0</string>
    <key>UISupportedInterfaceOrientations</key>
    <array>
        <string>UIInterfaceOrientationPortrait</string>
    </array>
</dict>
</plist>
PLIST_EOF
```

- [ ] **Step 8: 写 AppDelegate.m**

```bash
cat > AppDelegate.m << 'OBJC_EOF'
#import <UIKit/UIKit.h>

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property (strong, nonatomic) UIWindow *window;
@end

@implementation AppDelegate
- (BOOL)application:(UIApplication*)app didFinishLaunchingWithOptions:(NSDictionary*)opts {
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    Class vcClass = NSClassFromString(@"ViewController");
    self.window.rootViewController = [[vcClass alloc] init];
    [self.window makeKeyAndVisible];
    return YES;
}
@end

int main(int argc, char *argv[]) {
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil, NSStringFromClass([AppDelegate class]));
    }
}
OBJC_EOF
```

- [ ] **Step 9: 写 ViewController.m**

```bash
cat > ViewController.m << 'OBJC_EOF'
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
    BOOL patchBad = [status isEqualToString:@"loading"];  /* survived a crash mid-patch */
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
OBJC_EOF
```

- [ ] **Step 10: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add spikes/m3_ios_realdevice/
git commit -m "feat(m3): iOS 真机 demo spike — Dart 源码 + harness + ObjC 壳"
```

---

## Task 2: Rebuild iOS arm64 VM 对象文件（ninja，约 30-60 分钟）

**Why:** `~/dart/sdk/xcodebuild/ReleaseIosARM64/` 只有最终二进制和少量 .a，中间 .o 文件需要重新编译才能用于 Xcode app 链接。

- [ ] **Step 1: 确认 ReleaseIosARM64 的 args.gn 正确**

```bash
grep "dart_dynamic_modules\|is_release\|target_os" ~/dart/sdk/xcodebuild/ReleaseIosARM64/args.gn
```

Expected output:
```
dart_dynamic_modules = true
is_release = true
target_os = "ios"
```

- [ ] **Step 2: 启动 ninja 重建（后台，可继续后续任务）**

```bash
cd ~/dart/sdk/xcodebuild/ReleaseIosARM64
ninja -j8 dartaotruntime_product 2>&1 | tee /tmp/ninja_ios_build.log &
echo "Ninja PID: $!"
```

> 注意：此步骤会重新编译约 1176 个 .o 文件，耗时约 30-60 分钟。可以继续做 Task 3。

- [ ] **Step 3: 等待 ninja 完成（后续步骤依赖此输出）**

```bash
# 轮询进度（每隔 30 秒打印一次）
tail -f /tmp/ninja_ios_build.log | grep -E "^\[|error:|warning:" &

# 等待完成
wait
echo "Exit code: $?"
```

Expected final lines of log:
```
[1176/1176] LINK ./dartaotruntime_product
```

- [ ] **Step 4: 验证 .o 文件已生成**

```bash
ls ~/dart/sdk/xcodebuild/ReleaseIosARM64/obj/runtime/bin/dartaotruntime_product_set.*.o | wc -l
```

Expected: `12` (dart_embedder_api_impl, error_exit, icu, options, snapshot_utils, vmservice_impl, gzip, loader, main, main_impl, main_options, snapshot_empty)

---

## Task 3: 编译 Dart 产物（kernel → snapshot → patch.dill）

**Files:**
- Produce: `spikes/m3_ios_realdevice/build/app.dill`
- Produce: `spikes/m3_ios_realdevice/build/snapshot.S`
- Produce: `spikes/m3_ios_realdevice/build/patch.dill`

- [ ] **Step 1: 创建 build 目录**

```bash
mkdir -p ~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/build
B=~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/build
SPIKE=~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice
HOST_OUT=~/dart/sdk/xcodebuild/ReleaseARM64
IOS_OUT=~/dart/sdk/xcodebuild/ReleaseIosARM64
```

- [ ] **Step 2: gen_kernel → app.dill**

```bash
"$HOST_OUT/dartaotruntime_product" \
  "$HOST_OUT/gen/gen_kernel_aot.dart.snapshot" \
  --platform "$HOST_OUT/vm_platform.dill" \
  --aot \
  --output "$B/app.dill" \
  "$SPIKE/greet.dart"
```

Expected: no errors, `$B/app.dill` created.

- [ ] **Step 3: gen_snapshot → snapshot.S（使用 host gen_snapshot，相同 arm64 ISA）**

```bash
"$HOST_OUT/gen_snapshot_product" \
  --snapshot-kind=app-aot-assembly \
  --assembly="$B/snapshot.S" \
  "$B/app.dill"
```

Expected: `$B/snapshot.S` created (~several MB).

- [ ] **Step 4: 验证 snapshot.S 包含正确符号**

```bash
grep "kDartVmSnapshotData\|kDartIsolateSnapshotData" "$B/snapshot.S" | head -4
```

Expected: 4 lines with `.globl kDartVmSnapshotData` etc.

- [ ] **Step 5: dart2bytecode → patch.dill**

```bash
"$HOST_OUT/dartaotruntime_product" \
  "$HOST_OUT/gen/dart2bytecode.dart.snapshot" \
  --target vm \
  -Ddart.vm.product=true \
  -Ddynamic.modules.test.mode=aot \
  --bytecode-options=source-positions \
  --output "$B/patch.dill" \
  "$SPIKE/patch_greet.dart"
```

Expected: `$B/patch.dill` created (~small file).

- [ ] **Step 6: commit 编译产物（忽略大文件，只 commit 脚本）**

```bash
cat > ~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/.gitignore << 'EOF'
build/
EOF
cd ~/Documents/flutter_hot_patcher
git add spikes/m3_ios_realdevice/.gitignore
git commit -m "feat(m3): .gitignore for build artifacts"
```

---

## Task 4: 创建 Xcode 工程（Xcode.app，手动，约 2 分钟）

**Why:** 需要 Xcode 自动签名生成 provisioning profile，无法通过纯命令行完成。

- [ ] **Step 1: 在 Xcode.app 创建新工程**

1. 打开 Xcode.app
2. File → New → Project
3. 选 **iOS → App**，点 Next
4. 设置：
   - Product Name: `HotPatchDemo`
   - Organization Identifier: `org.hotpatch`
   - Bundle Identifier（自动填充）: `org.hotpatch.HotPatchDemo`
   - Language: **Objective-C**
   - Interface: **Storyboard**
   - 不勾选 Include Tests
5. Save location: `~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/HotPatchDemo`
6. 点 Create

- [ ] **Step 2: 配置 Signing**

1. 在 Xcode 左侧选中 `HotPatchDemo` 项目
2. 选 Target → `HotPatchDemo`
3. Signing & Capabilities 标签
4. Team: 选 `you Shaw (28VANPL49P)`
5. Bundle Identifier 改为: `org.hotpatch.m3demo`
6. 确认 Automatically manage signing 已勾选
7. Xcode 应自动创建 provisioning profile

- [ ] **Step 3: 验证签名配置**

在 Signing & Capabilities 标签页确认显示：
- ✅ Provisioning Profile: (Managed by Xcode)
- Signing Certificate: iPhone Developer: you Shaw

- [ ] **Step 4: 关闭 Xcode（后续改用命令行）**

---

## Task 5: 删除 Xcode 生成文件，替换为我们的源码

- [ ] **Step 1: 删除 Xcode 生成的模板文件**

```bash
XPROJ=~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo
rm -f "$XPROJ/AppDelegate.h" "$XPROJ/AppDelegate.m" \
      "$XPROJ/ViewController.h" "$XPROJ/ViewController.m" \
      "$XPROJ/SceneDelegate.h" "$XPROJ/SceneDelegate.m" \
      "$XPROJ/main.m"
```

- [ ] **Step 2: 复制我们的源文件进 Xcode 工程目录**

```bash
SPIKE=~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice
XPROJ=$SPIKE/HotPatchDemo/HotPatchDemo

cp "$SPIKE/AppDelegate.m"     "$XPROJ/"
cp "$SPIKE/ViewController.m"  "$XPROJ/"
cp "$SPIKE/dart_harness.c"    "$XPROJ/"
cp "$SPIKE/dart_harness.h"    "$XPROJ/"
cp "$SPIKE/builtin_shim.cpp"  "$XPROJ/"
cp "$SPIKE/build/snapshot.S"  "$XPROJ/"
cp "$SPIKE/build/patch.dill"  "$XPROJ/"
cp "$SPIKE/Info.plist"        "$XPROJ/"
```

- [ ] **Step 3: 复制 dart_api.h**

```bash
cp ~/dart/sdk/runtime/include/dart_api.h "$XPROJ/"
```

- [ ] **Step 4: 验证 Xcode 工程目录内容**

```bash
ls -la "$XPROJ/"
```

Expected: `AppDelegate.m`, `ViewController.m`, `dart_harness.c`, `dart_harness.h`, `builtin_shim.cpp`, `snapshot.S`, `patch.dill`, `Info.plist`, `dart_api.h`, plus Xcode storyboard files.

---

## Task 6: 配置 Xcode build settings（命令行 sed + xcconfig）

**Why:** 需要添加链接标志、头文件路径、静态库路径，以及告诉 Xcode 把 .S 文件当汇编源码。

- [ ] **Step 1: 创建 .xcconfig 文件**

```bash
SPIKE=~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice
XCPROJ=$SPIKE/HotPatchDemo
IOS_OBJ_DIR=~/dart/sdk/xcodebuild/ReleaseIosARM64/obj

cat > "$XCPROJ/DartVM.xcconfig" << XCEOF
// DartVM embedding settings
HEADER_SEARCH_PATHS = \$(inherited) ~/dart/sdk/runtime/include
LIBRARY_SEARCH_PATHS = \$(inherited) $IOS_OBJ_DIR/runtime $IOS_OBJ_DIR/runtime/bin
OTHER_LDFLAGS = \$(inherited) -ObjC -all_load -lc++ -lpthread -ldl -framework Foundation -framework Security -framework UIKit -framework CoreFoundation

// Treat .S as assembly source (handled by Xcode build phases)
// Suppress warnings from VM headers
GCC_WARN_INHIBIT_ALL_WARNINGS = NO
CLANG_ENABLE_MODULES = NO
XCEOF
```

- [ ] **Step 2: 在 Xcode 打开工程，手动添加文件引用和配置**

打开 `HotPatchDemo.xcodeproj` 到 Xcode，执行以下操作：

**a) 添加所有源文件：**
- 右键 `HotPatchDemo` 文件夹 → Add Files to "HotPatchDemo"
- 选中 `AppDelegate.m`, `ViewController.m`, `dart_harness.c`, `builtin_shim.cpp`, `snapshot.S`
- 勾选 "Add to target: HotPatchDemo"
- 点 Add

**b) 添加 patch.dill 作为资源：**
- 右键 → Add Files
- 选中 `patch.dill`，勾选 "Add to target: HotPatchDemo"
- Target Membership: Bundle Resources（不是 Compile Sources）

**c) 添加静态库：**
- 选中 Target → Build Phases → Link Binary With Libraries
- 点 "+"
- 选 "Add Other..." → 导航到 `~/dart/sdk/xcodebuild/ReleaseIosARM64/obj/runtime/`
- 按住 Cmd 多选：`libdart_aotruntime_product.a`（实际上这个不够，见 Step 3）

**d) 设置 Build Settings：**
- Target → Build Settings
- 搜索 "Header Search Paths"：添加 `~/dart/sdk/runtime/include`
- 搜索 "Other Linker Flags"：添加 `-ObjC -all_load -lc++ -lpthread -ldl`
- 搜索 "C++ Standard Library"：设为 `Compiler Default`

- [ ] **Step 3: 创建完整 VM 静态库（需要 ninja 完成后执行）**

```bash
IOS_OBJ=~/dart/sdk/xcodebuild/ReleaseIosARM64/obj
B_LIB=~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/build

# 收集所有 .o 文件（排除 main, main_impl, snapshot_empty）
find "$IOS_OBJ/runtime" -name "*.o" \
  ! -name "dartaotruntime_product_set.main.o" \
  ! -name "dartaotruntime_product_set.main_impl.o" \
  ! -name "dartaotruntime_product_set.snapshot_empty.o" \
  > /tmp/dart_obj_list.txt

wc -l /tmp/dart_obj_list.txt  # 期望约 1173 个文件

# 打包成静态库
ar rcs "$B_LIB/libdart_vm_ios.a" $(cat /tmp/dart_obj_list.txt)
echo "libdart_vm_ios.a size: $(du -sh $B_LIB/libdart_vm_ios.a)"
```

Expected size: 40-100MB

- [ ] **Step 4: 在 Xcode 将 libdart_vm_ios.a 加入 Link phase**

- Target → Build Phases → Link Binary With Libraries
- 点 "+"，Add Other，选 `build/libdart_vm_ios.a`
- 移除之前添加的 `libdart_aotruntime_product.a`（已包含在 libdart_vm_ios.a 中）

---

## Task 7: Build + Deploy

- [ ] **Step 1: 确保 iPhone 已连接**

```bash
xcrun devicectl list devices 2>/dev/null | grep "available (paired)"
```

Expected: 显示 `iPhone 14 ... available (paired)`

- [ ] **Step 2: xcodebuild（第一次，可能失败，需要看错误）**

```bash
cd ~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/HotPatchDemo
xcodebuild \
  -scheme HotPatchDemo \
  -configuration Debug \
  -destination "id=040F89ED-E7CC-54B0-A7BB-908EE82C0224" \
  -allowProvisioningUpdates \
  CODE_SIGN_IDENTITY="iPhone Developer" \
  CODE_SIGN_STYLE="Automatic" \
  DEVELOPMENT_TEAM="28VANPL49P" \
  build 2>&1 | tee /tmp/xcodebuild.log | grep -E "error:|BUILD|FAILED|SUCCEED"
```

Expected final line: `** BUILD SUCCEEDED **`

If `** BUILD FAILED **`, run:
```bash
grep "error:" /tmp/xcodebuild.log | head -20
```

- [ ] **Step 3: 常见链接错误排查**

| 错误 | 原因 | 修法 |
|------|------|------|
| `undefined symbol: kDartVmSnapshotData` | snapshot.S 未加入 Compile Sources | Xcode → Build Phases → Compile Sources 添加 snapshot.S |
| `undefined symbol: builtin_native_lookup_shim` | builtin_shim.cpp 未加入 Compile Sources | 同上 |
| `duplicate symbol: _main` | AppDelegate.m 里有 `main()` 但 Xcode 也生成了 main | 检查 Build Phases，确保没有其他 main.m |
| `'dart_api.h' file not found` | Header Search Paths 未配置 | Build Settings → Header Search Paths 添加 `~/dart/sdk/runtime/include` |
| `ld: symbol(s) not found for architecture arm64` (VM symbols) | libdart_vm_ios.a 未链接 | Build Phases → Link Binary With Libraries 添加 libdart_vm_ios.a |

- [ ] **Step 4: 部署到设备**

```bash
# 找到 .app 路径
APP=$(find ~/Library/Developer/Xcode/DerivedData -name "HotPatchDemo.app" -not -path "*/Build/Intermediates/*" 2>/dev/null | head -1)
echo "App: $APP"

# 部署
xcrun devicectl device install app \
  --device 040F89ED-E7CC-54B0-A7BB-908EE82C0224 \
  "$APP"
```

Expected: `App installed successfully.`

- [ ] **Step 5: 启动 app**

```bash
xcrun devicectl device process launch \
  --device 040F89ED-E7CC-54B0-A7BB-908EE82C0224 \
  org.hotpatch.m3demo
```

---

## Task 8: 验证三个场景

- [ ] **Step 1: 验证基线（patch_status 为空 → usePatch=true，使用 --patch 参数）**

首次安装 app，UserDefaults 为空，`status` = nil，`patchBad` = NO，`usePatch` = YES。

启动 App → UILabel 应显示 **PATCHED**。

在 Xcode console（Devices and Simulators → iPhone 14 → 选 HotPatchDemo → Open Console）确认：
```
[M3] Dart result: PATCHED
```

- [ ] **Step 2: 验证回滚（模拟 crash-guard 触发）**

```bash
# 手动把 patch_status 设为 "loading"（模拟上次崩溃）
xcrun devicectl device process send-signal --signal 0 --device 040F89ED-E7CC-54B0-A7BB-908EE82C0224 org.hotpatch.m3demo 2>/dev/null || true

# 通过 Xcode 在 ViewController.viewDidLoad 开头设断点，或用 idevicesyslog / Console.app
# 更简单：通过 xcrun simctl 风格的 UserDefaults 写入（需要 entitlements，不支持）
# 替代方案：在 ViewController.m 临时加：
# [ud setObject:@"loading" forKey:@"patch_status"]; [ud synchronize];
# 在 "Check crash guard" 之前
```

实际操作：
1. 在 `ViewController.m` 的 `viewDidLoad` 开头临时加：
   ```objc
   NSUserDefaults *ud_pre = NSUserDefaults.standardUserDefaults;
   [ud_pre setObject:@"loading" forKey:@"patch_status"];
   [ud_pre synchronize];
   ```
2. 重新 build + deploy
3. 启动 App → UILabel 应显示 **ORIGINAL**（回滚路径）
4. 移除临时代码，恢复正常

- [ ] **Step 3: 验证回滚解除**

移除临时代码后重新 build + deploy，启动 App → UILabel 应显示 **PATCHED**。

- [ ] **Step 4: 记录截图 / console 输出**

在 `spikes/m3_ios_realdevice/` 目录存一个 `RESULTS.md`，记录：
- 三个场景的 console 输出
- Xcode build log 最后几行
- 设备型号和 iOS 版本

```bash
cat > ~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/RESULTS.md << 'EOF'
# M3 iOS 真机 Demo 结果

## 设备
- iPhone 14 (iPhone14,7), iOS [填入版本]

## 场景 1: PATCHED
```
[M3] Dart result: PATCHED
```

## 场景 2: 回滚 (patch_status=loading)
```
[M3] Dart result: ORIGINAL
```

## 场景 3: 回滚解除
```
[M3] Dart result: PATCHED
```

## 结论
V2 redirect 机制在 iOS 真机 AOT 环境下工作正常。W^X 对 closure entry_point 字段写入无约束（堆内存，非可执行页）。M3 PASS。
EOF
```

- [ ] **Step 5: 更新 GATE_STATUS.md + commit**

在 `docs/GATE_STATUS.md` 的 Gate 1 iOS arm64 行：
```
| Gate 1 iOS arm64 机制验证 | ✅ PASS（V2 机制 + 真机部署，M3 完成） | ... |
```

```bash
cd ~/Documents/flutter_hot_patcher
git add spikes/m3_ios_realdevice/
git add docs/GATE_STATUS.md
git commit -m "feat(m3): iOS 真机 demo PASS — V2 redirect + crash-guard 回滚验证"
```

---

## 已知风险速查

| 风险 | 可能性 | 处理 |
|------|--------|------|
| host gen_snapshot 生成的 snapshot.S 汇编指令与 iOS 不兼容 | 低（相同 arm64 ISA，相同 Mach-O） | 若出现 `assembler error`，改用 iOS arm64 gen_snapshot via device：先 `xcrun devicectl device process install` gen_snapshot_product 到设备，通过 ssh/instrument 运行 |
| libdart_vm_ios.a 中有 macOS 条件编译符号导致 iOS link 失败 | 低（args.gn target_os=ios） | 检查报错符号，在 IOS_OBJ find 命令中排除对应 .o |
| Xcode 26.6 / iOS 26.5 SDK 与 dart SDK 内部 C++ 标准不兼容 | 低（VM 用 C++20，Xcode 支持） | 在 Build Settings 设 `CLANG_CXX_LANGUAGE_STANDARD = c++20` |
| dart_api.h 中 `__attribute__` 用法在新 clang 报 error | 极低 | 临时加 `GCC_WARN_INHIBIT_ALL_WARNINGS = YES` |
| patch_status UserDefaults 首次启动逻辑 | 低 | status=nil 时 patchBad=NO, usePatch=YES，正确展示 PATCHED |

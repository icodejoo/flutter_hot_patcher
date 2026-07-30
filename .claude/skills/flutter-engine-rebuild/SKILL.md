---
name: flutter-engine-rebuild
description: "从零把 Flutter Engine(Android arm64,含自定义 Dart VM 补丁 + --dart-dynamic-modules)在 WSL2 里重新编译一遍、并进一步用 --local-engine 构建出真正 Flutter APK 的完整踩坑记录：gclient/DEPS 版本一致性、CRLF 污染、dart-lang/sdk 主干不稳定窗口、WSL 后台进程管理、host 引擎变体、Android SDK/JDK 配置、Gradle 网络问题。当需要重新走一遍这条流程、或在新机器上重搭这套环境时使用，避免重新踩一遍已知的坑。"
---

# Flutter Engine 重编操作手册(Android arm64 + 自定义 Dart VM 补丁)

本 skill 记录把 `C:\sdk\flutter` 拷进 WSL2、套上 Gate 1 的 Dart VM 补丁
(`spikes/gate1_mixed_execution/vm_patch/gate1_vm_patch.diff`)、编译出一份
真正可用的 `libflutter.so` 这条路上踩的坑。目的和 `gate1-vm-spike` skill 一样：
**下次再走这条流程,照着做,不用重新发现一遍**。

结论速查放最后(§8),按顺序操作看前面。

## 0. Windows 下调 WSL,一律用 PowerShell 工具,不要用 Bash 工具

这条在 `gate1-vm-spike` skill 里记过,这里再强调一次因为这次踩得更狠:
Bash 工具(Git Bash/MSYS)会把看起来像 unix 路径的**参数内容**也转换掉,不只是
路径本身。哪怕是 `wsl -d Ubuntu -- bash -c "grep ... | grep -iE \"a|b|c\""`
这种一行内联命令,双引号也可能在传递过程中被吃掉,导致 `a|b|c` 被 shell 当成
管道命令执行(报 `command not found`)。

**规避**:复杂脚本一律先用 Write 工具写成文件,通过 `\\wsl.localhost\Ubuntu\...`
这个 UNC 路径直接读写 WSL 文件系统(Read/Edit/Write 工具都能直接用这个路径,
不用先转成 wsl 命令再转义),写好后用 `wsl -d Ubuntu -- bash /root/xxx.sh` 执行。
简单的单行 `grep`/`ls` 查询可以用 PowerShell 直接调,但只用双引号包裹、内容
不含管道符号内嵌的正则 alternation 时才安全。

## 1. 后台跑长命令:必须让 `wsl.exe` 这个 Windows 进程本身留在后台

踩过两次错误方式:
- `wsl -d Ubuntu -- bash -c "cmd &disown"`:`disown` 只让 bash 不给子进程发
  `SIGHUP`,但 `wsl.exe` 这个 Windows 进程一退出,整个这次 WSL 会话就可能被
  回收,子进程照样被杀——表现为“启动成功”但日志文件从头到尾是空的。
- PowerShell `Start-Job { wsl ... }`:job 的宿主进程也是这次 PowerShell 调用
  的子进程,工具调用一结束就可能被回收,同样启动了等于没启动。

**唯一可靠的方法**:用 Bash 工具的 `run_in_background: true`,把整条
`wsl -d Ubuntu -- bash -c "cmd > log 2>&1; echo EXIT_CODE=$? >> log"`
当成一条命令直接传给 Bash 工具(不要在 Bash 工具里再单独起 `&`/`disown`)。
Bash 工具自己的后台任务管理会保持 `wsl.exe` 这个 Windows 进程存活直到命令
真正跑完,配合 `<task-notification>` 通知机制,不需要手动轮询。

配合 `ScheduleWakeup` 定长时间间隔查看进度,不要用 `Start-Sleep`/`sleep` 链式
等待(会被工具拦截或占用整个回合)。

## 2. `gclient` 相关的三个反直觉细节

### 2.1 `custom_deps: {"path": None}` 只跳过这一层,不阻止 recursedeps 往里钻

想让 gclient 完全不碰某个第三方依赖(比如我们要保留自己 apply 过补丁的 Dart
SDK checkout),在 `.gclient` 的 `custom_deps` 里把它设成 `None` 确实会跳过
**这一层**的 checkout/reset,但如果外层 DEPS 声明了 `recursedeps` 包含这个
路径,gclient 还是会进去读它自己的 DEPS 文件、按**外层看到的**版本号解析
它的子依赖——外层和内层对同一个子依赖的版本认知可能不一致,导致子依赖被
反复拉回“错误”版本。

**规避**:每一个会被这样连带牵连的子路径,都要在 `custom_deps` 里单独加一条
`"父路径/子路径": None`,不能只锁最外层。

### 2.2 `DEPS` 里 `dart_root` 这类变量隐含了 solution 的目录结构假设

Dart SDK 自己的 `DEPS` 文件硬编码 `"dart_root": "sdk"`,隐含假设是:gclient 的
solution root 设在 checkout 的**上一级目录**,solution 名字就叫 `"sdk"`
(即 `<gclient root>/sdk` 才是实际代码)。如果直接把 solution root 设在
checkout 目录本身、随便起个名字(比如 `"."`),`gclient sync` 会在拼路径时
多出一层(`sdk/sdk/build/config/...`),报 `FileNotFoundError`。

**规避**:遇到这种 `FileNotFoundError` 报的路径比预期多一层,先去 `DEPS` 里
搜对应的 root 变量定义,按它的假设摆放目录结构,不要死磕调整代码。

### 2.3 改了 `.gclient` 之后一定要删 `.gclient_entries` 缓存

`.gclient_entries` 是上次 sync 成功后生成的缓存,记录了当时的 deps 结构。
改了 `.gclient` 的 `custom_deps`(尤其是新增/删除条目)之后不删这个缓存,
会报 `Error evaluating local config entries: duplicate key in dictionary`。
`rm -f .gclient_entries` 之后再 `gclient sync` 一定干净。

## 3. Dart SDK 自己的 pubspec.yaml 是个 monorepo workspace,`third_party/pkg/*` 版本必须自洽

Dart SDK 仓库根目录的 `pubspec.yaml` 用 `path:` 依赖直接引用几十个
`third_party/pkg/<vendor-repo>/pkgs/<package>` 路径(`core`/`tools`/`test`/
`native`/`http`/`i18n`/`leak_tracker`/`protobuf`/`pub`/`shelf`/`sync_http`/
`tar`/`vector_math`/`web`/`webdriver`/`webkit_inspection_protocol` 等,每个
都是独立 vendor 到 `DEPS` 里的 meta-repo)。**这些 vendor repo 在 `DEPS`
里的 pin 版本,不保证和当前 `pubspec.yaml` 引用的包路径一致**——遇到过
两次:`DEPS` 里 `native.git` 的 pin 缺 `test_case_selector` 包、`tools.git`
的 pin 缺 `api_summary` 包,都是 pubspec.yaml 已经在引用、但 DEPS 里那个
古老 commit 还没有的新包。

表现:跑 Flutter engine 的 `gclient sync` 时,末尾 hook 阶段报
```
pub get failed
Because _ depends on <package> from path which doesn't exist (could not
find package <package> at "third_party/pkg/<repo>/pkgs/<package>")
```

**规避**(批量处理,不要一个个包去对 DEPS 版本号):
```bash
cd third_party/pkg
for d in core dart_style dartdoc ecosystem http i18n leak_tracker native \
         protobuf pub shelf sync_http tar test tools vector_math web \
         webdriver webkit_inspection_protocol; do
  (cd "$d" && git fetch origin && \
    git remote set-head origin -a && \
    branch=$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@') && \
    git checkout "origin/$branch")
done
```
然后直接跑 `python3 tools/generate_package_config.py` 验证(比走一遍完整
`gclient sync` 快很多),通过后把每个手动更新过的路径都加进 Flutter
`.gclient` 的 `custom_deps: None` 列表(参考 §2.1),防止后续 sync 把它们
拉回旧版本。

## 4. 从 Windows 拷贝过来的 checkout,CRLF 会搞坏 shebang 脚本

如果 Flutter SDK 是从 `C:\sdk\flutter` 直接拷贝(而不是在 WSL 里原生
`git clone`)进 WSL 的,Windows Git 默认 `core.autocrlf=true` 会让所有
"文本"文件带 CRLF 换行。C++/Dart 源码本身不受影响,但**shebang 脚本会
直接跑不起来**,报:
```
/usr/bin/env: 'vpython3\r': No such file or directory
```

修的时候容易漏两类文件(踩过两次才找全):
1. **无扩展名的脚本**(比如 `tools/gn` 本身就没有 `.py`/`.sh` 后缀)——按
   扩展名过滤的修复脚本会直接漏掉,必须按**文件内容前两个字节是不是
   `#!`** 来识别,不能只看扩展名。
2. **`engine/` 目录之外的脚本**(比如 `flutter/bin/internal/
   content_aware_hash.sh`)——如果修复脚本只扫了 `engine/` 子树,这类文件
   会被漏掉。**要扫整个 checkout 根目录**,只排除 `.git` 目录和 Dart SDK
   symlink 的目标(那边本来就是纯 LF,原生 WSL clone 的)。

正确的检测+修复方式:
```bash
find . -path '*/.git' -prune -o -type f -print0 | while IFS= read -r -d '' f; do
  [ "$(head -c2 "$f")" = "#!" ] || continue
  grep -qUl $'\r' "$f" && sed -i 's/\r$//' "$f"
done
```

**副作用要注意**:这个扫描如果范围设太大(比如把 `.h`/`.cc` 这类源码扩展名
也纳入按扩展名的第一轮扫描),会**误改到 vendor 第三方仓库里的生成产物**
(踩过的例子:ANGLE 的预编译 D3D shader 头文件、glslang/spirv-tools 的生成
代码、`third_party/pkg/archive`)。这些改动会让对应的 vendor 子仓库变成
"有未提交改动",导致下一次 `gclient sync` 直接报错拒绝:
```
You have uncommitted changes.
cd into <repo>, run git status to see changes, and commit, stash, or reset.
```
**规避**:CRLF 修复只需要覆盖"会被当脚本执行"的文件(靠 shebang 内容判断,
不要用扩展名白名单去猜),天然就不会碰到这些生成的二进制头文件。如果已经
误改了,批量扫描 `third_party` 下所有嵌套 git 仓库(注意要递归找,不能只看
一层目录,`third_party/pkg/archive`、`vulkan-deps/glslang/src` 这类是嵌套
两三层的),对每个报 dirty 的仓库 `git checkout -- .` 恢复干净即可(不需要
`git clean -fd`,只是文本被改了几个字节,没有新增文件)。

## 5. 最大的坑:dart-lang/sdk 主干可能处于"重构进行中"的中间不稳定状态

这个坑级别最高,花的时间也最多,值得完整记录判断过程。

**现象**:`ninja` 编译到 `bootstrap_compile_platform`(编译 Dart 平台库
kernel 快照,是几乎所有下游 AOT/字节码工具链的基础前置步骤)时报一串
`Error: Couldn't find constructor 'StaticTypeContext'`、
`Couldn't find constructor 'Name'`、`Couldn't find constructor
'TypeEnvironment'`——都是 `pkg/vm/lib/modular/transformations/ffi/*.dart`
调用 `pkg/kernel` 里的类。

**排查步骤**(不要一上来就怀疑是我们的 checkout 版本选错了,要按下面步骤
实证判断):
1. 确认 `pkg/vm`、`pkg/kernel` 不是分开管理的 DEPS 依赖(`grep 'pkg/kernel\|pkg/vm' DEPS`
   查不到就说明是跟主仓库同一个 commit,理论上该自洽)。
2. 如果原来是浅克隆(`git rev-parse --is-shallow-repository` 返回 `true`),
   **先 `git fetch --unshallow` 拿到完整历史**,浅克隆下 `git log` 只能看到
   一个 commit,没法判断这是不是暂时的中间状态。
3. 用 `git log --oneline -3 -- <报错涉及的具体文件>` 分别查每个文件的最近
   改动时间。如果这些文件**近期(几周内)刚被改过**、commit message 带类似
   `[cfe][Contexts]`/`[kernel][Contexts]` 这种系列前缀,大概率是一次
   **正在进行中的大重构**,不同文件的迁移进度不一致,HEAD 处于中间态。
4. 用 `git log --all --grep='<重构系列关键词>' --format='%ci %H %s' | sort`
   按真实提交时间排序,找到这个重构系列**最早**的一次提交,那个时间点
   往前退几天,就是一个安全的、重构开始前的稳定基线。
5. `git checkout <重构开始前的 commit>`,`git stash pop` 把我们的 VM 补丁
   apply 回去(git 的三方合并能跨几个月的历史正常工作,只要改动的文件本身
   没有被大规模重写)。

**关键教训**:遇到"上游内部 API 不一致"报错时,第一反应不是"我们的 checkout
版本选错了、要重新配对哪个 pin",而是先判断这**到底是不是一个稳定态**——
用完整历史查最近改动记录,分清"我们踩到了一个正在进行中的重构窗口"和
"我们的环境配置本身有问题",这两者的修法完全不同。前者的修法是往前退到重构
开始前的稳定点,后者才是去对 DEPS pin。

## 6. 换 Dart SDK commit 时,用 `git stash` 保护补丁,不要用备份文件糊弄自己

```bash
cd third_party/dart   # 实际是我们 symlink 过去的独立 Dart SDK checkout
git diff > /root/patch_backup.diff   # 保险起见留一份文本备份
git stash -u -m 'vm patch backup before switching commit'
git fetch --unshallow origin          # 如果需要
git checkout <target-commit>
git stash pop                          # git 的 3-way merge 会自动处理大部分场景
git status --short                     # 确认 5 个补丁文件都是 modified,没有冲突标记
```
`git stash pop` 比"记下 diff、切 commit、重新 apply diff 文件"更可靠,因为
stash 保留了原始 blob 内容用于三方合并,`git apply`/`patch` 只有文本上下文,
换了几个月历史后更容易因为周边代码变了而 apply 失败。

## 7. 实际构建命令(跑通的版本)

```bash
# 1. gclient 配置(.gclient 的 custom_deps 需要把 third_party/dart 和所有手动
#    更新过版本的 third_party/pkg/* 子路径都设成 None,见 §2.1 §3)
rm -f .gclient_entries
PATH=/opt/depot_tools:$PATH GCLIENT_SUPPRESS_GIT_VERSION_WARNING=1 \
    DEPOT_TOOLS_UPDATE=0 gclient sync --no-history

# 2. gn 配置(--no-prebuilt-dart-sdk 是关键,不加这个会下载官方预编译 Dart SDK,
#    完全绕过我们改过的 VM 源码;--dart-dynamic-modules 打开动态模块解释器)
cd engine/src/flutter
PATH=/opt/depot_tools:$PATH ./tools/gn --android --android-cpu arm64 \
    --runtime-mode release --no-prebuilt-dart-sdk --dart-dynamic-modules

# 3. 编译(输出目录名规律见 tools/gn 的 get_out_dir():
#    <target_os>_<runtime_mode>[_<android_cpu>如果不是默认arm])
PATH=/opt/depot_tools:$PATH ninja -C ../out/android_release_arm64 -j4
```

产物在 `engine/src/out/android_release_arm64/libflutter.so`。验证补丁的
4 个自定义 native 函数真的链接进去了:
```bash
strings libflutter.so | grep -i 'redirectDispatchTableEntry\|redirectClosureEntryPoint\|loadDynamicModuleClosure'
```

## 9. 用 `--local-engine` 构建真正的 APK,还需要一份 **host 变体**引擎

`flutter build apk --local-engine=<target>` 不是只需要 target 变体
(比如 `android_release_arm64`)——`flutter_tools` 会用**另一套 host 端工具链**
(`frontend_server`、`gen_snapshot` 等)来做 kernel 编译/AOT 编译,这套工具链
要另外单独构建一次:

```bash
cd engine/src/flutter
PATH=/opt/depot_tools:$PATH ./tools/gn --runtime-mode release \
    --no-prebuilt-dart-sdk --dart-dynamic-modules   # 不加 --android,生成 out/host_release
PATH=/opt/depot_tools:$PATH ninja -C ../out/host_release -j<N>
```
target 数量比 `android_release_arm64` 多不少(host 变体会连带编译大量
unittest/benchmark 目标),这是正常的,不是配置错了。构建命令里三个参数要
配套传全:
```bash
flutter build apk --target=<入口文件> \
    --local-engine=android_release_arm64 \
    --local-engine-host=host_release \
    --local-engine-src-path=<engine/src 绝对路径> --release
```

## 10. vendor 包被强制更新到"最新版"后,可能比同一批次的其他包更新——版本又不自洽了

§3 里为了绕过"DEPS pin 太旧、缺某个包"这个问题,把几个 vendor 仓库
(`dart_style`/`dartdoc`/`native`/`tools` 等)都强制切到了各自上游的**默认
分支最新提交**。这个做法本身没错,但会引入一个新风险:如果被更新的包
(比如 `dart_style`)本身依赖另一个包(比如 `analyzer`,它在 dart-sdk 自己的
`pkg/analyzer` 目录里,跟着 sdk 主仓库一起被我们锁定在§5的稳定 commit 上,
**没有**被强制更新),那么"最新版 dart_style" vs "旧版 analyzer" 之间可能
出现同样性质的 API 不一致——比如 `dart_style` 用到了 analyzer AST 里某个新
getter(`ExtensionTypeDeclaration.namePart`),但我们固定的 analyzer 版本里
还没有这个 getter,报:
```
Error: The getter 'namePart' isn't defined for the type 'ExtensionTypeDeclaration'.
```

**规避**:不要把这些 vendor 包无脑更新到"绝对最新",而是更新到**和 dart-sdk
主仓库锁定的那个稳定 commit 日期相近**的版本:
```bash
cd third_party/pkg/<vendor>
git log --before='<sdk稳定commit的日期,比如2026-05-08>' -1 --format='%H %ci %s' --all
git checkout <该commit>
```
`dartdoc` 也高度依赖 analyzer,遇到 `dart_style` 这个问题时**顺手把 dartdoc
也退到同一时间点**,能避免它稍后在别的编译阶段暴露同一类问题。

## 11. Gradle/Java 的 TLS 握手失败是同一个 WSL2 网络问题的另一种表现形式,别误判成新坑

装好 Android SDK/JDK 后跑 `flutter build apk`,可能报:
```
Could not GET '.../kotlin-gradle-plugins-bom-2.2.20.pom'.
   > (handshake_failure) Received fatal alert: handshake_failure
```
或者
```
Could not download startup-runtime-1.1.1.aar ...
   > (bad_record_mac) Tag mismatch
```
这两个报错文本和 `curl`/`git` 遇到的证书类报错完全不一样,**容易被误判成一个
新的、需要单独排查的问题**。实际上：用 `curl` 并发测同一个域名(如
`repo.maven.apache.org`、`plugins.gradle.org`)大概率是 100% 成功的——因为
这不是证书链缺失,而是 [[wsl2-tls-offload-bug]] 那个 WSL2 网卡 offload 随机
corrupt 数据包的老问题,只是在 **Java 自己的网络栈**(不是 curl 用的
libcurl/OpenSSL)上表现成 `handshake_failure`/`bad_record_mac` 这两种更底层
的 TLS 错误,而不是"证书验证失败"。

**规避**:遇到 Gradle 报这类底层 TLS 错误,不要去改 JVM 的 TLS 协议版本参数
瞎试,**先直接重试一次构建命令**——Gradle 自带下载失败重试机制
(`Retrying Gradle Build: #1`),大概率第二次就过了(这次实测：第一次编译
到一半失败,加一次完全重跑就直接成功,零改动)。真要根治,应该是重新确认
offload 关闭状态,而不是针对 Java 单独找修法。

## 12. Android APK 构建的两个环境依赖:`ANDROID_HOME` 和 `JAVA_HOME`

- **Android SDK**:不用额外装,`engine/src/flutter/third_party/android_tools/sdk`
  下就有一份 gclient 拉下来的现成 SDK(含 platform-tools),设
  `ANDROID_HOME`/`ANDROID_SDK_ROOT` 指过去即可。
- **JDK**:必须是 **Linux 原生**的 JDK,装在 WSL 里(`apt-get install
  openjdk-21-jdk-headless`),**不能复用 Windows 上的 JDK**——即使 WSL2 能
  透明调用 Windows `.exe`(interop),Gradle 需要装载 Android SDK 里的 Linux
  原生组件(如 `aapt2`),混用 Windows JVM 会在这一步直接失败,不是能凑合用
  的组合。

## 14. 真机验证:现代 AGP 直接从 APK zip 里 mmap native 库,`libapp.so` 不是独立文件

demo app 装到真机上,基线(无补丁)正常显示 `ORIGINAL`,但推了补丁字节码重启后
报 `could not find libapp.so mapping in /proc/self/maps` ——V1 那套机制原本靠
"在 `/proc/self/maps` 里找路径以 `libapp.so` 结尾的 `r-xp` 段"来算 load bias
(桌面/Gate 1b 都是这样,当时 `libapp.so` 确实是文件系统上一个独立文件)。

**根因**:现代 Android Gradle Plugin(AGP)默认 `extractNativeLibs=false`——
把 native 库**不解压、按 4KB 页对齐存进 APK 的 zip 里**,运行时直接
`mmap(fd=apk, offset=zip里的字节偏移)`,不再解压到文件系统。表现是
`/proc/self/maps` 里所有 native 库(`libflutter.so`、`libapp.so` 等)的路径
都显示成 `.../base.apk`,**不会**出现 `libapp.so` 这个文件名——而且好几个库
都从**同一个 APK 文件**映射,只是字节偏移不同,不能只靠路径名区分是哪一个。

**规避**(在 build_manifest 阶段,而不是运行时,解决"是哪个库"的问题):
```python
import zipfile, struct
z = zipfile.ZipFile(apk_path)
info = z.getinfo('lib/arm64-v8a/libapp.so')
with open(apk_path, 'rb') as f:
    f.seek(info.header_offset)
    header = f.read(30)
    fname_len, extra_len = struct.unpack('<HH', header[26:30])
    data_offset = info.header_offset + 30 + fname_len + extra_len  # 页对齐
```
把这个 `data_offset`(以及 `info.file_size`)也写进 manifest.txt。运行时不再
按路径名匹配 `.so`,改成:遍历所有路径以 `.apk` 结尾的 `r-xp` 段,找**文件偏移
落在 `[data_offset, data_offset+file_size)` 区间内**的那一段,再按
`loadBias = segStart - segOffset + data_offset` 算出真正的 load bias(这里
`segOffset` 是这段映射对应的 APK 文件字节偏移,不是 `.so` 内部偏移,两者要通过
`data_offset` 换算)。

调试方法论：真机上普通 app 进程读不了别的进程的 `/proc/pid/maps`
(`Permission denied`,连 adb shell 都不行,除非 root)。遇到"外部查不了目标
进程内存映射"这种情况,最快的办法是让**目标进程自己**在失败分支里把
`/proc/self/maps` 里可疑的行 print 出来,通过 logcat 间接观察，不用折腾 root
或额外的调试工具。

## 15. 结论速查

- Flutter Engine(Android arm64,`--dart-dynamic-modules` + 我们的 VM 补丁)
  **编译成功**,产物 `libflutter.so`(~165MB)确认含 4 个自定义 native 函数。
- 用这份自编译引擎(target `android_release_arm64` + host `host_release`)
  通过 `flutter build apk --local-engine=...` 构建出了一份可安装的
  Flutter APK(`app-release.apk`,15.4MB)。
- **真机端到端验证通过**:装 APK → 显示基线 `g() got: ORIGINAL` → 推补丁
  字节码 → 重启 app → 显示 `g() got: PATCHED-APK-HOTFIX`。这是第一次在**真正
  的 Flutter APK**(不是 Gate 1b 那种独立可执行文件模拟)里验证整套热修复
  机制,是 Gate 2(linker)开工前的最后一块拼图,已经完整拼上。
- 全程踩的坑几乎都是**环境/版本一致性**问题(gclient/CRLF/vendor版本/JDK/
  AGP native库打包方式),和 VM 补丁本身的正确性无关(补丁能一路顺利
  `git stash pop` 应用到相差近 3 个月的另一个 commit 上,没有冲突;地址解析
  逻辑改成按 APK 内字节偏移匹配后一次成功,侧面印证核心的"改写调用点 + 加载
  字节码"机制本身没有问题,问题都出在"怎么找到正确的内存地址"这类外围工程
  细节上)。
- 最大的风险点是 §5 那类"追 HEAD 追到了别人正在重构的窗口"——生产环境下
  这套 Engine 重编流程应该**锁定一个明确的稳定 commit/tag**(比如某个
  Dart/Flutter 正式 release 对应的 revision),而不是每次都拉最新
  `origin/main`,避免反复撞上这类中间态问题。
- 下一步:Gate 2(linker,per-function diffing 不破坏整程序优化)。

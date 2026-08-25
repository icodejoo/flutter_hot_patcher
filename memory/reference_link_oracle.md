---
name: reference-link-oracle
description: LinkOracle — Shorebird 私有 runtime/vm/shorebird/shorebird.h 里的类，.vmcode link table 的运行期读取方；DWARF 给了整份头文件；wrapper 的真正调用点在引擎不在 gen_snapshot
metadata:
  type: reference
---

2026-08-24 发现。追「WrapperAllocator 没有调用点」时一直在 **错的二进制** 里找：
它是**运行期**设施，本来就不该出现在 `gen_snapshot`（那里只有两个 stub *生成器*）。

**真正的调用链**（引擎 `Flutter.framework/Flutter`，`__TEXT` vmaddr 0，dSYM 地址直接对应）：

```
Deserializer::WrapperForRunTarget(LinkOracle::RunTarget) const
   → 每个方向一个 std::function<uword(uword)> lambda
      → WrapperAllocator::AllocateMetadata()   @ 0x7d0728
```
反汇编实测**只有 2 处**分支指向它（0x733328 / 0x7333cc），正好两个方向。
兄弟方法 `Deserializer::WrapFunction(long, unsigned long) const` @ 0x732d4c。
两者都是 Shorebird 加在上游 `Deserializer` 上的。

**LinkOracle 头文件（DWARF 直给，含声明行号，不是推测）**
`runtime/vm/shorebird/shorebird.h:27`，0x60 字节 —— 这是**第 14 个**私有源文件，
⚠️ 别和公开的 `flutter/shell/common/shorebird/shorebird.{h,cc}`（规则 2 那份）搞混。

```c++
std::unique_ptr<uint8_t[]> backing_;                        // :28 @0x00
size_t header_size_;                                        // :29 @0x08
static int32_t int32_in(const uint8_t*, size_t);            // :31
int32_t int32_at(size_t) const;                             // :35
void BuildCaches();                                         // :39
std::unordered_map<int,int> patch_to_cpu_offset_;           // :44 @0x10
std::unordered_map<int,int> cpu_to_patch_offset_;           // :50 @0x38
LinkOracle(std::unique_ptr<uint8_t[]>, size_t header_size); // :53
bool HasPatch() const;                                      // :56
static LinkOracle* shared();                                // :58
static std::unique_ptr<LinkOracle> fromBuffer(const uint8_t*, size_t); // :59
static size_t ReadHeaderSize(const uint8_t*, size_t);       // :63
size_t header_size() const;                                 // :75
enum RunTarget : unsigned { cpu = 0, sim = 1 };             // :77
struct RunTargetOffset { const int64_t offset; /*@0x00*/    // :79, 0x10 字节
                         RunTarget target;   /*@0x08*/
                         bool is_cpu() const; bool is_sim() const; };
RunTargetOffset RunTargetFromPatchOffset(int64_t) const;    // :97
RunTargetOffset RunTargetFromBaseOffset(int64_t) const;     // :104
```

**它是什么**：`.vmcode` link table 的运行期读取方。两个 map 双向翻译偏移，
`RunTargetFrom*Offset` 回答「这个偏移上的代码跑在 CPU 上还是模拟器里」，
反序列化据此包装 entry point。`shared()` 与 `ShorebirdLinker::shared()` 同一套单例写法。
`fromBuffer`+`ReadHeaderSize` 说明输入就是 `tools/linker.py` 写出的那份 link table
—— 两者是同一份契约的两端（另一端见 `GROUND_TRUTH.md`）。

**方法论教训**：spike 里的符号计数表只量 `gen_snapshot`，所以它对一个
「本来就不该在那里」的子系统报 0 是正常的，不是缺口。问 wrapper / LinkOracle
要去查**引擎二进制**。

## 已实现（2026-08-24，commit `94ee77c3624`）

`runtime/vm/shorebird/shorebird.h` + `runtime/vm/shorebird.cc`（文件路径配对照抄他们的，为了让 dSYM 行表差分还能用）。13 条单测全过，全部 69 条 shorebird 单测全过，product `gen_snapshot` 仍链接、`.ddid` 仍逐字节相同。**负控制做了**：把 `RunTargetFromPatchOffset` 命中分支从 `cpu` 改成 `sim`，恰好 2 条变红。

`Dart_ShorebirdLoadVmcode` 已改成读完整 header → `fromBuffer` → `Install()`，所以不是死代码；原来的 `Simulator::SetPendingVmcodeFile` 路径保留未动。

**两处刻意偏差（头文件里已标注，别当成已验证）**：
1. `Install()` 是我们加的——他们的安装方在还没还原的代码里，而一个没法填充的单例没法测；
2. `RunTargetFromBaseOffset` 在他们引擎里是**死方法**（DWARF 只有声明，全engine零内联实例、零外联符号），与 `print_dispatch_table_debug_info_to` 同型。我们写的是对称读法，**无法对他们验证**。

相关：[[project-wrapper-upstream-ancestor]]、[[project-dart-sdk-fork]]、[[project-b-route-phase2]]

# diff_linker ARM64 移植 —— 修复 REVIEW Tier A2 红线发现

**背景**：`REVIEW_diff_linker.md` Tier A2 指出 diff_linker 是纯 x86-64 工具，在 arm64（真实
部署目标之一）上会**静默漏判**：`call` 提取正则匹配不到 `bl`/`blr` → 条件2传播整体失效；
`%r15` 池通配写死 x86 语法 → arm64 池漂移零归一化 → 闭包爆炸。用户明确表态"宁可不用也不能
出问题"，且项目已有 **Gate1b Android arm64** 构建环境（不需要 Mac），是当前最高性价比的
硬缺口修复项。

跑：跟 x86-64 版一样的 `diff_linker.py` 调用，传 arm64 的 `.snapshot`/`.debug`；架构**自动探测**
（`readelf -h` 的 Machine 字段），不需要额外参数。

## 移植内容

新增 `ARCH_CONFIG` 表（`x64`/`arm64` 两项），把此前写死在正则里的架构相关部分参数化：

| 项 | x86-64 | arm64（本次实测确认，非猜测） |
|---|---|---|
| 直调助记符 | `call`/`callq` | `bl` |
| 对象池寄存器 | `%r15` | `x27` |
| 池访问语法 | `0xNN(%r15)`（十六进制） | `[x27, #NN]`（**十进制**） |
| 线程寄存器（栈溢出检查，不通配） | `%r14` | `x26`（模式一致：`ldr x16,[x26,#72]` == x86 `cmp %rsp,0x48(%r14)`） |
| 函数间填充助记符 | `int3`/`nop` | `udf`/`.inst`/`andeq`（防御性，未在样本里实测触发） |
| 反汇编工具 | `objdump`（原生） | `aarch64-linux-gnu-objdump`（需 `apt-get install binutils-aarch64-linux-gnu`，原生 objdump 报"can't disassemble for architecture UNKNOWN"） |
| DWARF 解析 | `readelf` | `readelf`（原生即可，格式与指令集无关，两个架构通用） |

**架构自动探测**（`detect_arch()`，读 `readelf -h` 的 Machine 字段）而非要求手动传参——遵循
"绝不静默"原则：探测不到/不认识的架构直接硬失败，不会猜一个错的正则表默默跑下去；
base/patch 架构不一致同样硬失败（跨架构比较没有意义）。

## 验证数据（实测，非估算）

用现有的 Gate1b Android arm64 构建产物（`ReleaseAndroidARM64/clang_x64/exe.stripped/
gen_snapshot_product`，支持 `--save-debugging-info`）编译 P1 大样本和 v6/v7/v8 用例：

| 用例 | 结果 |
|---|---|
| P1 大样本（3124 函数，294 撞名） | **PASS — closure == ground truth (sound + precise)**，漏判0/误报0，与 x86-64 结果完全一致 |
| v8_realfix | byte-changed=2, 闭包=5，与 x86-64 结果完全一致 |
| x86-64 全语料回归（P1/v6/v7/v8） | 无回归，改造未破坏原有路径 |

`bl` 提取、`x27` 池通配、CanonicalName DWARF 对齐、多重集精化、条件2级联——在真实 arm64
反汇编上全部正确工作，和 x86-64 是同一套逻辑、同一个结果。

## 诚实边界

- 只在 **Android arm64**（Gate1b 已有构建环境）上验证，**iOS arm64 尚未验证**（iOS 是 Mach-O
  不是 ELF，`objdump`/`readelf` 这套工具链在 iOS 上完全不适用，需要另一套基于
  `otool`/`dsymutil` 的解析逻辑——这是等 Mac 到位后的独立移植工作，不在本次范围内）。
- 函数间 padding 的 `udf`/`.inst`/`andeq` 过滤是防御性加的，**样本里没有实际触发这条路径**
  （这次测的函数都紧密排列，没有函数间空隙），如果真机上出现说明覆盖到了，但没有专门验证。
- 沿用 x86-64 版所有已知局限（池通配是近似、multiset 在置换下不 sound 等，见 diff_linker.py
  docstring 和 REVIEW_diff_linker.md）——arm64 移植没有引入新的这类问题，也没有解决旧的。

## 对 PRODUCTION_LINKER_SPEC 的更新

R6（多架构）从"待办"更新为"Android arm64 spike 级已验证、iOS arm64 待 Mac 后移植"——这是
生产 linker 需求清单里第一个从"纯设想"变成"有实测数据支撑"的多架构条目。

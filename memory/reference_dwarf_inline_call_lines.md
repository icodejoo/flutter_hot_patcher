---
name: reference-dwarf-inline-call-lines
description: 用 DWARF 的 DW_AT_call_line 逐行还原被完全内联、无符号的函数——解开 WrapCode 的就是它
metadata:
  type: reference
---

# `DW_AT_call_line`：内联函数的逐行还原

**问题**：某个函数在他们的产物里**只有内联副本**，`nm` 为 0，dSYM 只有
`DW_AT_declaration`（形参有类型、没名字）。读它就是读一大段没有边界的机器码。
`Deserializer::WrapCode` 卡在这里**四轮**（1588 字节，四段不连续 range）。

**方法**：内联**不会**丢掉行号归属——行表就是干这个的。
每一个被内联进目标函数的 callee 都会留下一条
`DW_TAG_inlined_subroutine`，带三样东西：

- `DW_AT_abstract_origin` → 被内联的是**谁**
- `DW_AT_call_file` + `DW_AT_call_line` → 它是在目标函数的**哪一行**被调用的
- `DW_AT_ranges` / `DW_AT_low_pc` → 它占哪段**地址**

把目标函数地址范围内的这些条目按 `call_line` 排序，就得到**逐行的操作清单**，
每行还附带地址区间 —— 于是反汇编从「盲读 1588 字节」变成「定点读 180 字节」。

## 怎么做

```bash
# 1. 一次性 dump（很慢、很大，27M 行，存下来复用）
xcrun dwarfdump --debug-info <dSYM>/Contents/Resources/DWARF/<Bin> > /tmp/dw.txt

# 2. 单点探路（快，先确认范围对不对）
xcrun dwarfdump --lookup=0x73ab00 --arch=arm64 <dSYM binary>
```

然后流式 parse `/tmp/dw.txt`：遇到 `DW_TAG_inlined_subroutine` 开一条记录，
收集 `abstract_origin` / `low_pc` / `[0x.., 0x..)` / `call_file` / `call_line`，
遇到 `NULL` 收尾；只保留地址落在目标范围**且** `call_file` 是目标文件的。

⚠️ **必须同时过滤 `call_file`**。`call_line` 是相对 `call_file` 的，
不过滤就会混进 `object.h:16493` 这种，看起来像目标函数有一万多行。

⚠️ **`call_line` 也能给出调用方**：`WrapCode` 自己那条 `inlined_subroutine`
的 `call_line=10214` 直接指出 `ReadInstructions` 在哪一行调它，
顺手把调用方也还原了（10204/10205/10208/10214/10225/10227）。

## 它给什么、不给什么

**给**：完整的操作序列、每个操作的源码行号与地址区间、分支数量
（`WrapCode` 有四个 `EntryPoints::Code` 返回点 = 四条路径）。

**不给**：**局部变量和形参的名字**。声明条目里形参只有类型。
所以 `WrapCode` 两个出参（`uint32_t&` / `uword&`）的含义**仍然读不到**，
最终按规则 3 **刻意不实现**并在头文件标注，而不是编一个自洽的解释。

→ **它把「整个函数读不到」缩小成「两个出参读不到」。** 缩小到能落地就够了。

## 什么时候想起它

- `nm` 为 0 且 dSYM 只有 declaration
- [[reference-differential-flag-oracle]] 用不上（那个要能从外部开关行为）
- 已经在同一段机器码上卡过两轮以上

⚠️ 与 [[reference-differential-flag-oracle]] 互补：差分 oracle 对**能从 CLI 触发**的
代码有效，这个对**运行期、无开关、纯内联**的代码有效。两个都失败时才谈规则 4 停止。

⚠️ **工具陷阱**：`xcrun llvm-symbolizer` 在本机**不存在**，
`xcrun` 会把错误写 stderr 然后返回空 —— 我第一次就把空输出读成了「没有行号信息」。
**用 `dwarfdump --lookup` 或直接 parse `--debug-info`**；
任何「输出为空」先确认工具真的跑了（见 [[feedback-false-green-traps]]）。

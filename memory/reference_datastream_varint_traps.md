---
name: reference-datastream-varint-traps
description: Dart runtime/vm/datastream.h 的 varint 读取在 Release/Product 无边界强制；0x00 是延续字节不能用作填充哨兵，要用 0xFF
metadata: 
  node_type: memory
  type: reference
  originSessionId: de13fb95-54ec-4a86-a27b-1ad12342445f
---

`runtime/vm/datastream.h`（我们的 `*LinkInfo` reader 与他们的格式都用它）有两个实测踩到的坑。

## 1. `0x00` 是**延续**字节，不能用作填充哨兵

读循环是 `while (b <= 127)`（`datastream.h:247`）——终止条件是字节 **≥ 128**。
所以用 `0x00` 给缓冲区尾部填充「安全余量」**恰好邀请越界读**，是最坏的选择。

实测（4 字节文件 + 16 字节 slack）：
```
0x00 填充 → decoded count=4504424529526783  PendingBytes=-4831   ← 越界 4831 字节
0xFF 哨兵 → decoded count=34359738367        PendingBytes=-1      ← 越界 1 字节
```
用 `0xFF`：任何 ≥128 的字节对**有符号与无符号两种形式**都终止。

## 2. `ReadStream` 的边界检查是 `ASSERT`，Release/Product 全部编译掉

→ 接用户提供的文件（如 `--base_ct_link_data`）时：
- 截断文件 = 越界堆读
- 损坏的 `count` = 无界 `reserve()`

实测：4 字节文件解出 count=34359738367 → `reserve()` 做 **1.92 TB** 虚拟保留。
**macOS 懒提交，RSS 只有 17 MB，不崩溃** —— 所以**没有任何测试能抓到它**，
只能靠直接测量 capacity。这类「不崩但错」的缺陷是测试盲区。

必需的守卫：拒绝零长度文件 + 用 `PendingBytes()` 给 `count` 做合理性检查（在 `reserve()` 之前）。

## ⚠️ 守卫互相冗余 → 单守卫变异无法失败任何测试

实测：三层守卫（`PlausibleCount` / 字符串长度上界 / `AtEnd`）**逐个禁用都 exit 0**，
因为每种畸形输入都被另一层兜住。
→ 测试套实际验证的是「畸形输入会被某种方式拒绝」，**不是「每个守卫都有效」**。
外层守卫的独特贡献（限制越界字节数、阻止 1.9TB 保留）**只能靠测量证明，不能靠测试覆盖声称**。
判断守卫有效性时别用单守卫变异分数。

## 长期正解（未做）

在 `ReadStream` 之上做一个**带边界检查的 varint 包装器**，一次性结构性解决。
否则这一族每个未来的 reader（如 `ObjectPoolLinkInfo`）都会重新继承同一个问题。
未做原因：超出当时 task 范围，且触及共享 VM 代码。

相关：[[feedback-false-green-traps]]、[[project-dart-sdk-fork]]、[[feedback-verify-by-running]]

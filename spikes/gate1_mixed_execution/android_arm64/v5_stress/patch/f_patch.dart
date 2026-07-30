// Copyright / 版权: spike code for flutter_hot_patcher Gate 1 (V5 stress).
//
// Deliberately trivial — V5 is about calling this many times / from many
// isolates, not about what it does. Per V4's finding, stick to symbols the
// host already exercises (string interpolation) to avoid bytecode-load-time
// "Unable to find function/class" failures from closed-world AOT tree-shaking.
//
// 故意写得很简单——V5 测的是"调很多次/从很多 isolate 调"，不是这个函数本身做
// 什么。按 V4 的发现，只用宿主已经在用的符号(字符串插值)，避免闭世界 AOT 树摇
// 导致字节码加载阶段的 "Unable to find function/class" 报错。
library;

@pragma('dyn-module:entry-point')
String fPatched() => 'PATCHED';

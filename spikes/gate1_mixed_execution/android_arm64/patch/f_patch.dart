// Copyright / 版权: spike code for flutter_hot_patcher Gate 1b (Android arm64 repro).
// Same trivial patch body as V1 — this case is about proving the arm64
// call-site-rewrite mechanism, not about patch content.
// 和 V1 一样的简单补丁体——这个用例要证的是 arm64 调用点改写机制本身，
// 不是补丁内容。
library;

@pragma('dyn-module:entry-point')
String fPatched() => 'PATCHED';

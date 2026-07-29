// Copyright / 版权: spike code for flutter_hot_patcher Gate 1 (V1 replacement).
//
// The CORE thesis: can an already-AOT-compiled, existing call site (g -> f) be
// redirected at runtime to reach an interpreted, behaviorally-different f'?
// This is the unprecedented part. Interop (adding new functions) is NOT the target.
//
// 核心命题：已经 AOT 编译的既有调用点（g -> f）能否在运行时被重定向到解释执行、
// 行为不同的 f'？这才是无公开先例的部分。"新增函数的互操作"不是目标。
library;

import 'dart:io';

/// Existing function to be replaced. Marked never-inline so it keeps a real,
/// separate entry point that a redirect can target.
///
/// 待替换的既有函数。标记 never-inline，使其保留独立入口以便重定向。
///
/// Returns "ORIGINAL" in the baseline build. The patch f' must make g() observe "PATCHED".
/// 基线构建返回 "ORIGINAL"；补丁 f' 须让 g() 观测到 "PATCHED"。
@pragma('vm:never-inline')
String f() => 'ORIGINAL';

/// Existing caller. Its call to f() is compiled by AOT (static direct call).
/// After activation, this same call must land in the interpreted f'.
///
/// 既有调用方。它对 f() 的调用被 AOT 编译（静态直调）。激活补丁后，
/// 这个调用必须落进解释执行的 f'。
@pragma('vm:never-inline')
String g() => 'g() got: ${f()}';

/// V1 spike host entry.
/// Prints g() before and after patch activation; PASS iff the AFTER call
/// observably reflects the interpreted f' ("PATCHED").
///
/// V1 spike 宿主入口。补丁激活前后各调一次 g()；当 AFTER 调用可观测地反映
/// 解释执行的 f'（"PATCHED"）时判 PASS。
void main(List<String> args) {
  print('BEFORE: ${g()}'); // 期望 ORIGINAL

  // ── 待验证的核心机制（见 NOTES.md）─────────────────────────────
  // 把 f 的入口切到解释器里的 f'。公共 API loadModuleFromBytes 只做"新增"，
  // 不做"替换既有函数入口"，因此这一步很可能需要 VM 层改动来实现/探索。
  // Redirect f's entry to the interpreted f'. The public loadModuleFromBytes
  // only ADDS; replacing an existing function's entry likely needs VM-level work.
  final activated = _tryActivatePatch(args);
  // ──────────────────────────────────────────────────────────────

  final after = g();
  print('AFTER: $after');

  if (!activated) {
    print('V1 INCONCLUSIVE: patch activation mechanism not wired yet');
    exit(3);
  }
  if (after.contains('PATCHED')) {
    print('V1 PASS: existing call site g()->f() reached interpreted f\'');
    exit(0);
  }
  print('V1 FAIL: call site still reaches ORIGINAL after activation');
  exit(1);
}

/// Placeholder for the entry-redirection mechanism under investigation.
/// Returns true once a real activation path is wired in (VM hook / internal API).
///
/// 待研究的入口重定向机制的占位。当接入真正的激活路径（VM 钩子/内部 API）后返回 true。
bool _tryActivatePatch(List<String> args) {
  // TODO(gate1): wire the entry-point switch. See NOTES.md for candidate approaches.
  return false;
}

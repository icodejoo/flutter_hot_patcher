// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// Dart_SnapshotDataSize / Dart_SnapshotInstrSize 由 Shorebird 的**私有**
// dart-sdk (shorebirdtech/dart-sdk) 提供，本项目的 dart-sdk 没有。
// 按 CLAUDE.md 规则 3 就地实现，并沿用上游函数名，使引用它们的上游源文件
// （runtime/shorebird/patch_mapping.cc、shell/common/shorebird/shorebird.cc、
// shell/common/shorebird/snapshots_data_handle.cc）无需修改。

#ifndef FLUTTER_SHELL_COMMON_SHOREBIRD_FHP_SNAPSHOT_SIZE_H_
#define FLUTTER_SHELL_COMMON_SHOREBIRD_FHP_SNAPSHOT_SIZE_H_

#include <cstdint>
#include <cstring>

// Dart 快照头是公开布局（third_party/dart/runtime/vm/snapshot.h:36-40）：
//   offset 0   int32  magic = 0xdcdcf5f5
//   offset 4   int64  length
//   offset 12  int64  kind
// 因此 data 段长度可直接读出。
inline size_t Dart_SnapshotDataSize(const uint8_t* data) {
  if (data == nullptr) {
    return 0;
  }
  int32_t magic = 0;
  memcpy(&magic, data, sizeof(magic));
  if (magic != static_cast<int32_t>(0xdcdcf5f5)) {
    // 不是带头的快照，交给 VM 自行推断（与静态链接路径一致）。
    return 0;
  }
  int64_t length = 0;
  memcpy(&length, data + sizeof(magic), sizeof(length));
  return length > 0 ? static_cast<size_t>(length) : 0;
}

// instructions 段没有长度头。引擎在 DART_SNAPSHOT_STATIC_LINK 路径上对
// isolate data/instructions 一律传 size = 0（见 runtime/dart_snapshot.cc 的
// NonOwnedMapping 构造），VM 自行确定范围，这里沿用同一约定。
inline size_t Dart_SnapshotInstrSize(const uint8_t* /*data*/) {
  return 0;
}

// Shorebird_SetBaseSnapshots 同样只存在于私有 shorebirdtech/dart-sdk。
//
// 两边的 VM 设计不同：Shorebird 把四个 base 快照指针交给 VM；本项目的 Simulator
// （dart/sdk runtime/vm/simulator_arm64.cc）只需要 base **instructions** 的地址，
// 因为 .vmcode link table 的 cpu_offset 正是相对它的偏移
// （见 simulator_arm64.cc:72 与 :2063 的 shorebird_base_instructions_base_）。
// 我们的 dart-sdk 已导出 fhp_set_base_instructions 承担这件事，故在此适配：
// 只转发 isolate instructions，其余三个在本设计中未被使用。
extern "C" void fhp_set_base_instructions(const void* base_ptr);

inline void Shorebird_SetBaseSnapshots(const uint8_t* isolate_data,
                                       const uint8_t* isolate_instructions,
                                       const uint8_t* vm_data,
                                       const uint8_t* vm_instructions) {
  (void)isolate_data;
  (void)vm_data;
  (void)vm_instructions;
  fhp_set_base_instructions(isolate_instructions);
}

#endif  // FLUTTER_SHELL_COMMON_SHOREBIRD_FHP_SNAPSHOT_SIZE_H_

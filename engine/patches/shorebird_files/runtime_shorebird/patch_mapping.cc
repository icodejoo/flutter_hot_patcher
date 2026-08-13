// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "flutter/runtime/shorebird/patch_mapping.h"

#include <cstring>

#include "third_party/dart/runtime/include/dart_native_api.h"

namespace flutter {

namespace {

// Shorebird 的私有 dart-sdk 提供 Dart_SnapshotDataSize / Dart_SnapshotInstrSize；
// 我们的 dart-sdk 没有，按规则 3 就地实现。
//
// Dart 快照头是公开布局（runtime/vm/snapshot.h）：
//   offset 0  int32  magic = 0xdcdcf5f5
//   offset 4  int64  length
//   offset 12 int64  kind
// 因此 data 段尺寸可直接读出。
size_t FhpSnapshotDataSize(const uint8_t* data) {
  if (data == nullptr) {
    return 0;
  }
  int32_t magic = 0;
  memcpy(&magic, data, sizeof(magic));
  // Snapshot::kMagicValue（runtime/vm/snapshot.h:36）本身声明为 int32_t
  if (magic != static_cast<int32_t>(0xdcdcf5f5)) {
    // 不是带头的快照；交给 VM 自行推断（与静态链接路径一致）。
    return 0;
  }
  int64_t length = 0;
  memcpy(&length, data + 4, sizeof(length));
  return length > 0 ? static_cast<size_t>(length) : 0;
}

// instructions 段没有这样的长度头。引擎在 DART_SNAPSHOT_STATIC_LINK 路径上
// 对这两段一律传 size = 0（见 dart_snapshot.cc 的 NonOwnedMapping 构造），
// VM 会自行确定范围，所以这里沿用同一约定。
size_t FhpSnapshotInstrSize(const uint8_t* /*data*/) {
  return 0;
}

}  // namespace

std::shared_ptr<PatchMapping> PatchMapping::CreateIsolateData(
    std::shared_ptr<PatchCacheEntry> entry) {
  if (!entry) {
    return nullptr;
  }
  const uint8_t* data = entry->isolate_data();
  size_t size = FhpSnapshotDataSize(data);
  return std::shared_ptr<PatchMapping>(new PatchMapping(entry, data, size));
}

std::shared_ptr<PatchMapping> PatchMapping::CreateIsolateInstructions(
    std::shared_ptr<PatchCacheEntry> entry) {
  if (!entry) {
    return nullptr;
  }
  const uint8_t* data = entry->isolate_instructions();
  size_t size = FhpSnapshotInstrSize(data);
  return std::shared_ptr<PatchMapping>(new PatchMapping(entry, data, size));
}

PatchMapping::PatchMapping(std::shared_ptr<PatchCacheEntry> entry,
                           const uint8_t* data,
                           size_t size)
    : cache_entry_(std::move(entry)), data_(data), size_(size) {}

PatchMapping::~PatchMapping() = default;

size_t PatchMapping::GetSize() const {
  return size_;
}

const uint8_t* PatchMapping::GetMapping() const {
  return data_;
}

bool PatchMapping::IsDontNeedSafe() const {
  // Patch mappings are file-backed and safe for madvise(DONTNEED).
  return true;
}

}  // namespace flutter

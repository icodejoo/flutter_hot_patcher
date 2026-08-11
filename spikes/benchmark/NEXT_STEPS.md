# Benchmark 下一步操作

基础设施已全部就绪。采集剩余数据需要以下操作：

---

## ✅ 已完成

- Shorebird iOS release 1.0.0+3 已发布
- shorebird_demo 已安装到 iPhone 14
- shorebird iOS baseline (none) 已采集：RSS=52MB，cold_start=0.21ms

---

## 🔲 需要：设备连接 WiFi

**Shorebird normal + cpu patch 测量**（设备需要能访问 Shorebird CDN）：

```bash
cd spikes/benchmark
./scripts/push_ios_shorebird.sh 040F89ED-E7CC-54B0-A7BB-908EE82C0224 normal
./scripts/push_ios_shorebird.sh 040F89ED-E7CC-54B0-A7BB-908EE82C0224 cpu
```

---

## 🔲 需要：Xcode 编译 + 安装 HotPatchBench

```bash
# 1. 编译 AOT 快照
cd spikes/benchmark/hotpatch_demo && ./build_aot.sh

# 2. 打开 Xcode，签名（Team: 7VP87G446C），Product → Run 到 iPhone 14
open spikes/benchmark/hotpatch_demo/HotPatchBench.xcodeproj

# 3. 安装后运行 hotpatch 基准测试
cd spikes/benchmark
./scripts/push_ios_hotpatch.sh 040F89ED-E7CC-54B0-A7BB-908EE82C0224 normal
./scripts/push_ios_hotpatch.sh 040F89ED-E7CC-54B0-A7BB-908EE82C0224 cpu
```

---

## 🔲 需要：Android 设备连接

```bash
adb devices  # 确认设备已识别

# Shorebird Android release（已发布 1.0.0+1）
~/.shorebird/bin/shorebird release android  # 若需重建

./scripts/push_android_shorebird.sh [DEVICE_SERIAL] normal
./scripts/push_android_shorebird.sh [DEVICE_SERIAL] cpu
```

---

## 生成报告

任意时刻运行：

```bash
python3 scripts/report.py
open results/report.html
```

当前已有数据：`results/shorebird_ios_none.json`（baseline）

---

## 关键发现（已观察到）

- **Shorebird patch 需要 WiFi**：设备必须能访问 `update.shorebird.dev` CDN
- **我们的 hotpatch 只需 USB**：直接 `devicectl device copy to` 推 .dill
- **Shorebird patch 大小**：从 CLI 输出获取（尚未实测，需 WiFi）
- **hotpatch .dill 大小**：normal=447B，这是核心优势之一

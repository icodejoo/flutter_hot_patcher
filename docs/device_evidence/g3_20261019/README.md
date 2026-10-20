# G3 与新引擎 G4 证据（2026-10-19）

范围：3 个真实 app × 两条独立 base/patch 工具链，只在 QA-iPhone-YPVYHY2D90（iPhone 14、iOS 26.6）上验证；不外推到其他 iOS 大版本。参考 Flutter 修订 `c2515c46c7fca511e39735a615f0f12f3dca6230`。我们的 SDK 最终本地提交 `41693e90584a86ca9cf5025c6021f3db3ddd5fac`，未推送。本仓库未提交或推送，`.loop/PAUSE` 保留。

`audit.py` 复核六组 G3 真机报告、对称观察窗、Installed 状态、构建与载荷哈希、签名后与自编引擎一致的 `__TEXT,__text`、本地 updater 配置和两侧链接率：96/96。四个负控制分别改坏冷启动标记、补丁状态、观察时长和设备 ID，均使检查报红。`g4_audit.py` 按原 G4 判定口径复核新引擎的有效补丁与五种坏补丁共 12 组：31/31，五个负控制均报红。坏 ELF 保留 G4-03/ELF 限定例外：参考首次 signal 6，我们首次退出码 0；两侧二次启动均回落 `BASE_V1`、标 `Bad` 且存活。

修复的 SDK 缺陷是 Mach-O `--dump_blobs` 漏计 Shorebird 附加数据块。实际 Wonderous 基底 9,396,509 字节，旧分析器只输出 6,637,789 字节。修复后的我们的分析器、参考分析器和独立 Mach-O 提取脚本逐字节相同。G1 hello/prog/base_dd 的 1428/2958/1428 个有文件字节的 ELF 符号在 SDK 新提交上与钉住产物相同，改坏一个指令符号的负控制报红。

`g2_recheck.json` 在同一 SDK 提交上比较四组完整测试：Debug C++ 3319/3119、Product C++ 3006/2806、Debug language/corelib 6921/6921、Product language/corelib 6901/6901（前数为我们，后数为原版）；四组均 `COMPARABLE`，我方更差均为 0，比较器的坏结果哈希负控制以 rc 2 拒读。首轮并行 Debug C++ 曾有 1 项采样器测试失败，单项探针随后 3/3 通过，空闲环境完整复跑通过；失败原因未确证，初轮 `REGRESSION` 记录与最终通过记录同时保留。首次 Product language/corelib 进程在完成前消失，清单停在 `RUNNING`、结果文件为空；它未进入验收，另一个完整目录用于比较。完整异常说明和原件位置见 `scratchpad/g3_20261019/RESULT.md`。

可重新打印审计读数：

```sh
python3 docs/device_evidence/g3_20261019/audit.py
python3 docs/device_evidence/g3_20261019/g4_audit.py --out docs/device_evidence/g3_20261019/g4_audit.json
python3 docs/device_evidence/g3_20261019/write_identity.py
python3 scratchpad/g3_20261019/g1_recheck.py
python3 scratchpad/g3_20261019/g2_compare_all.py
python3 -c 'import json; r=json.load(open("scratchpad/g3_20261019/g2_profiler_probe.json")); print(len(r["runs"]), sum(x["returncode"] == 0 for x in r["runs"]))'
wc -c scratchpad/g3_20261019/work/wonderous/ours/pre_fix_base.blob scratchpad/g3_20261019/work/wonderous/ours/corrected_base.blob
shasum -a 256 -c docs/device_evidence/g3_20261019/SHA256SUMS
```

`audit.json`、`g4_audit.json`、`g1_recheck.json` 和 `g2_recheck.json` 是审计结果与负控制记录，`identity.json` 是提交、工具哈希与设备身份清单。原始参考二进制、完整 app、补丁、运行日志均在被忽略的 `scratchpad/g3_20261019/`，没有进入本目录。`work/<app>/ref` 与 `work/<app>/ours` 保存两链产物；`g4_new_engine/device/runs` 保存 G4 真机报告；`device_inventory.json` 保存设备系统版本的查询原件。三份 app 的 `shorebird.yaml` 测试副本和装机配置均指向 loopback 与虚构 app_id，没有运行发布命令。

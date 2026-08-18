# flutter_hot_patcher

Flutter iOS 热修复的**自建全链路**：打包、签名、分发、回滚。

设备侧复用 Shorebird 的预编译引擎与 Rust updater；服务端一侧（linker、
补丁仓库、分发协议、签名）全部自建，可私有化部署。

```
源码改动
  ↓ frontend_server   → patch.dill
  ↓ gen_snapshot      → patch.aot（ELF）
  ↓ analyze_snapshot  → base/patch 符号表
  ↓ tools/linker.py   → out.vmcode（LinkTable + 内嵌 ELF）
  ↓ zstd bipatch      → 增量 + sha256 + RSA 签名
  ↓ 自建分发服务端
设备：引擎在 dart_snapshot.cc 的 ResolveIsolateData 处换入补丁快照
```

被替换的函数运行在 ARM64 Simulator 上，未被替换的代码仍是原生 AOT。

## 上手

```bash
python3 -m venv tools/.venv
tools/.venv/bin/pip install -r tools/requirements.txt

tools/fhpb init    --app-dir <你的工程> --base-url https://patches.example.com
tools/fhpb release --app-dir <你的工程> --repo /srv/patches --build
# 改代码后
tools/fhpb patch   --app-dir <你的工程> --repo /srv/patches \
                   --private-key tools/broute/keys/patch_private.pem
tools/fhpb serve   --repo /srv/patches --app-id <app_id>
```

完整流程、发布护栏、换钥、排障：**[docs/RUNBOOK_ROUTE_B.md](docs/RUNBOOK_ROUTE_B.md)**

## 命令

| 命令 | 作用 |
|---|---|
| `init` | app_id / 签名密钥 / `shorebird.yaml`；幂等 |
| `release` | 归档基线版本，校验 kernel 同源 |
| `patch` | 生成、签名、发布一个补丁 |
| `verify` | 按设备侧规则复核已发布的补丁 |
| `rollback` | 下线/恢复某个补丁 |
| `list` | 查看 release 与补丁状态 |
| `rotate-key` | 换签名私钥（旧钥归档） |
| `serve` | 分发服务端 |

## 前置

App 必须用 Shorebird 的 Flutter SDK 构建：

```
~/.shorebird/bin/cache/flutter/c15ef6379403a0a55531a058bdb2c8e55bc05c98
```

补丁与基线必须**同源**——同一份 `app.dill`、同一套 `gen_snapshot`。
`fhpb release` 会当场用 `gen_snapshot` 校验并归档基线，不同源当场失败。

## 实测

| | |
|---|---|
| `.vmcode` | 4,423,848 B |
| 下发增量 | 402,153 B（9.1%）|
| link% | 100.00% |
| 补丁函数 vs 原生 | 慢约 138× |

真机 OTA 已验证（iPhone 14 / iOS 26.6）：`BASELINE_V1` → `OTA_PATCHED_V2`。

## 验证

```bash
bash tools/tests/test_fhpb_lifecycle.sh   # 全生命周期 + 护栏 + 换钥，50 项
bash tools/tests/test_broute_server.sh    # 分发协议一致性，9 项
```

## 待实现

见 **[docs/ROADMAP.md](docs/ROADMAP.md)**：自建分发基础设施（服务器/云/CDN）、
设备端网络下载验证、私钥轮换、`base_url` 护栏、Android 支持。

## 已知限制

- 仅 iOS；Android 未实现
- 补丁冷启动生效
- 依赖 Shorebird 预编译引擎产物（其 dart-sdk 私有，无法自建）
- **设备经网络下载并 inflate 增量这一环尚未验证** —— 补丁应用本身已用
  USB 注入验证，但完整的网络下发链路需在可达的 HTTPS 端点上复验一次。
  详见 RUNBOOK 的「验证边界」

## 来源

本分支是单提交的生产快照，不携带研发历史。完整历史（研究记录、A/B 实验、
引擎补丁、真机验证过程）在 `route-a-research` 分支与
`route-a-research-backup-20260818` tag。

## 安全

签名私钥是端上唯一的信任根。`tools/broute/keys/` 已 gitignore。

⚠️ 研发分支的历史中曾提交并公开过一把私钥。**本分支的历史不含它**，
但那把钥匙已经公开，若你手上的 `tools/broute/keys/` 是从旧仓库带过来的，
正式发布前必须 `tools/fhpb rotate-key` 换新并重新发版（公钥编译进包）。见 RUNBOOK。

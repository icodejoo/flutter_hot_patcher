# B-Route Phase 2.0 取证 Spike

用 Shorebird 自己的 fork 二进制离线复现 `aot_tools link`，把 linker 的五项未知量实测锁死。

- **设计**：`docs/superpowers/specs/2026-08-07-b-route-phase2-groundtruth-design.md`
- **计划**：`docs/superpowers/plans/2026-08-07-b-route-phase2-groundtruth.md`（含执行期实测修正）
- **结论**：[`GROUND_TRUTH.md`](GROUND_TRUTH.md)
- **决策**：`docs/superpowers/specs/2026-08-07-b-route-phase2-ab-decision.md`

不需要 Shorebird 账号，不需要网络。所用二进制全部来自本机 `~/.shorebird` 缓存。

## 跑一遍

```bash
bash -c 'source ./env.sh && sb_env_report'        # 环境自检，任一工具缺失即硬失败
./run.sh                                           # 构建 base + 四组样本，逐个 link
bash -c 'source ./env.sh && "$PY" -m pytest tests/ -q'   # 解析器回归（239 tests）

bash -c 'source ./env.sh && "$PY" diff_matrix.py'  # 四段中间快照差分矩阵
./probe_dd.sh s3_body                              # DD table 取证
bash -c 'source ./env.sh && ./probe_hash.sh'       # subgraph hash 取证
```

产物全部落在 `out/`（已 gitignore）。

## 文件

| 文件 | 职责 |
|---|---|
| `env.sh` | 唯一的路径真相源。任一工具缺失即硬失败。所有脚本 source 它。 |
| `samples/*.dart` | 基线 + 四组受控改动（等长常量 / 变长常量 / 函数体 / 新增类） |
| `build_aot.sh` | `.dart` → `.dill` → `.aot`，并产出 `.ct/.ft/.dt.link` 侧车 |
| `run_link.sh` | 对一组 (base, patch) 驱动 `aot_tools link --dump-debug-info` |
| `run.sh` | 顶层编排 |
| `parse_vmcode.py` | `.vmcode` 头部 + LinkTable 解析器（U1/U2） |
| `parse_link_data.py` | 八种 `.link` 的 datastream varint 解析器（U4） |
| `diff_matrix.py` | 四段中间快照差分矩阵 |
| `probe_hash.sh` + `compare_hashes.py` | subgraph hash 变化面取证（U3） |
| `probe_dd.sh` | DD table 取证（U5） |
| `tests/` | 以 aot_tools 自己的文本/JSON 产物为独立 oracle |

## 环境陷阱（复现前必读）

- **本 repo 内的裸 `diff` 不可信** —— RTK 会把单行差异报成 `✅ Files are identical`
  且退出码 0。一律用 `command diff` / `cmp`；git 用 `command git`。
- 本机唯一的 bash 是 3.2.57，脚本不得用 bash 4+ 特性。
- 交互 shell 是 zsh，`env.sh` 需要 bash：`bash -c 'source ./env.sh && ...'`。
- 用 `"$PY"`（spike 内隔离 venv 的 python，带 pytest），不要用 `python3`。

## 纪律

解析失败、格式失配、样本没触发目标代码路径 —— 一律硬失败或显式告警，
不允许输出"好看的 0"。沿用 `spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md` R8。

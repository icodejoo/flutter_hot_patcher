---
name: feedback-verify-by-running
description: 在这个仓库，凡是靠读代码得出的结论都出过错；必须跑真实链路验证后才能写进文档或回话
metadata: 
  node_type: memory
  type: feedback
  originSessionId: dc4cce83-bc27-467b-8fb1-5ed4b50d62f0
  modified: 2026-08-18T05:20:22.575Z
---

**在 flutter_hot_patcher 里，读代码得出的结论不可信，必须实跑。**

用户连续四轮说「每次都发现真问题」，每一次的真问题都不是读出来的，是跑出来的：

- 测试桩件输出 `link%: 100.00`，真实脚本输出 `100.00%`（带 % 号）→
  `float()` 抛异常，**每次真实发布都在构建完成后死掉**，而测试全绿
- 文档里写 `fhpb init --force` 是换钥命令 → 实跑发现它**不换钥**，
  反而把 `app_id` 随机换掉（线上设备全失联）
- 归档的 `base.aot` 与现场重算差 654,555 字节，看着像 P0 →
  实跑完整构建两遍，`.vmcode` 逐字节相同，是虚惊
- 怀疑服务端有目录穿越 → `curl --path-as-is` 实测跑不出 repo 根

**Why**：这个项目的关键行为分散在 Shorebird 预编译二进制、Rust updater、
gen_snapshot、我们自己的 linker 之间，源码印象和实际行为经常对不上。
桩件是我按想象写的，所以它会跟着我的错误假设一起错。

- 用未加引号的 heredoc（`<<PY`）写文档 → 文中所有反引号被 shell 命令替换掉，
  内容变成空白，而命令**照常打印成功、照常推送**。写文件一律用 `<<'EOF'`，
  且写完必须回读验证内容，不能只看退出码
- **「解析器消耗了全部字节」不等于格式正确**：解 Shorebird LinkInfo 时
  「读到 EOF 为止」的循环越界后**刚好停在最后一字节**，于是
  `consumed == len` 报告 CLEAN，我据此宣布格式已破解——实际漏掉了写在末尾的标量。
  是拿他们自带的 JSON 对照才抓出来的。自证式检查会顺着错误假设一起通过；
  一定要有**独立的第二表示**（他们的 JSON / 另一个工具的输出）来对拍，
  并加**反向对照**（截断 1 字节、多 1 字节，必须报错）

- **进度/完成度也要实测，不能靠记账**（2026-08-19）：我按「已移植的文件数」把
  dart-sdk 复刻报成 15–20%，实测 `nm gen_snapshot` 后是 ~10%——
  移植进来的 sim bridge 虽然编译出了 `.o`，却因无调用点被 dead-strip，
  **一个符号都没进产物**。「改了 BUILD.gn / 提交了代码」≠「进了产物」。
  可复跑的口径：两边 `nm -a | c++filt` 数各子系统标志符号，我们为 0 即真没写。

**How to apply**：
1. 写进文档的每一条命令，**先跑一遍再写**，尤其是 `--force` 这类破坏性开关
2. 加了桩件就要确认它的输出格式与真实产物**逐字节一致**
3. 结论要拿真实链路对拍：干净检出 + 从零建 venv +
   `init→release→patch→verify`，对 `sha256` 基准（见 [[project-v1-release]]）
4. 涉及设备侧协议，去读 `~/engine_ios/src/flutter/third_party/updater/library/src/`
   的真实结构体，不要凭 `docs/` 里的转述
5. 报告时把「查了但证伪」的也写出来，不要只报找到的问题
6. 报完成度先量再说；数字下降往往是量准了，不是退步（见 [[project-dart-sdk-fork]]）

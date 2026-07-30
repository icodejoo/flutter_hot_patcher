# P2 Flutter widget 差分 harness

**目标**：把差分精确度验证从纯 Dart 抬到**真实 Flutter widget + 完整框架**，覆盖
StatelessWidget / StatefulWidget / build / setState，并对每种做改动。

跑：`./run_widget.sh`（用 WSL 里 Flutter **官方 cache 成套工具链** frontend_server +
gen_snapshot 把 `base/`、`patch/` 的 widget app 编成 host-x64 AOT ELF `libapp.so`，
再跑 CanonicalName diff_linker）。**只 objdump ELF、不运行**，故不需 Linux 桌面/GTK，也
**不需自定义 Gate-1 引擎**（用它会因快照版本不匹配报 "Wrong full snapshot version"——
P2 与解释器无关，用 stock 匹配工具链即可）。

## 样本与改动

`base/main.dart`：`layoutMetric`（被 `Tile.build` 直接调用的布局函数）、`Tile`
(StatelessWidget)、`Counter`+`CounterState`(StatefulWidget，`build` + `increment` 里
`setState`)、`App`，`runApp(App())` 保留整棵树。补丁两处改动：
`layoutMetric` `+8→+9`、`increment` 里 `_count += 1→2`（改动落在 setState 的闭包体内）。

## 结果：widget 改动被精确收敛，整个框架保持等价

| 指标 | 值 |
|---|---|
| 总函数（含完整 Flutter 框架） | **5797** |
| 撞名 key | 579（10.0%）——**全部多重集相同判等价，0 被播种** |
| byte-changed（条件1） | **2**：`CounterState.increment.<anonymous closure>`（setState 闭包，`+=2`）、`layoutMetric` |
| 传播（条件2） | 1：`Tile.build`（calls `layoutMetric`） |
| 闭包（must reinterpret） | **3（0.1%）** |
| equivalent（全速原生基线） | **5794 = 整个 Flutter 框架** |
| added / removed / SDK 噪音 | 0 / 0 / 0 |

**读数**：
- **功能覆盖**：StatelessWidget 的 `build`（经 helper 级联）、StatefulWidget 的 `setState`
  闭包改动都被正确检出。`increment` 的改动精确落在其**匿名闭包**（`setState(() {...})`
  的参数）——linker 命中的正是它，符合真实语义。`CounterState.build` 以 tearoff
  (`onTap: increment`) 间接引用，未被误拖进闭包。
- **精确度（核心）**：一处 widget 代码改动，在 5797 函数的真实框架里只牵动 **3 个函数
  （0.1%）**；**整个 Flutter 框架 5794 个函数全部判等价、跑全速签名机器码，不转解释**。
  579 处框架内跨库同名被 CanonicalName 干净解析，0 误伤。
- 这把 P1（纯 Dart 3125 函数）的精确度结论抬到了**产品级规模的真实 Flutter 框架**上，
  直接支撑 V10 的 f（解释比例）在真实 app 上极小：改 widget 业务代码 → 闭包个位数、
  框架全速原生。

## spike 边界

- 同 P1：静态精确度（objdump+DWARF+不动点），未运行时实跑；stock cache 工具链产 AOT ELF。
- 未覆盖：RenderObject 自定义 paint、平台通道、大规模状态管理；这些是后续扩样本项。
- async widget（FutureBuilder 等）未纳入（async 状态机多符号，见 P1 async 备注）。

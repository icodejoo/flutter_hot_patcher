# 🤖 SDK 复刻自动化状态机

> **⚠️ 核心协议**：当你（Claude）清空上下文并重新读取此文件时，你必须保持 /loop 状态。
> 严禁停下来等待人类确认，严禁偷懒。请直接阅读下方的【当前核心任务】，
> 立即执行【开发->验证->文档->提交->清理】闭环！

## 📋 当前核心任务

- [ ] 任务 1：实现 `ObjectPoolMappingsAggregator`（加权投票 + `GetBestMapping`），
      替换 `linker.cc:367-394` 里靠「组恰好 1 成员」过滤的 `ComputeObjectPoolLinkResults`
- [ ] 任务 2：`self_pp` / `subgraph_pp` 的 sticky `csel` 选择 + `self_hash_` 回落分支
- [ ] 任务 3：造**判别性合成 fixture**，用他们的 `gen_snapshot` 做 oracle 判定任务 1/2 真的对了
- [ ] 任务 4：`LinkedValue<T>` 模板落地（目前用裸 `PoolIndexPair`）
- [ ] 任务 5：收紧 `object_pool_editor` 的两条软断言，修 kind-1/2 在 2²⁴ 之后的计数误读
- [ ] 任务 6：把 `ObjectPoolEditor` 接进 `ImageWriter::Write`（依赖任务 1 产出 `mapping[]`）

## ⏳ 挂起池（连续失败 3 次的顽固 Bug）

- **真机 A/B 验证**（非 Bug，是**结构性不可自动化**）：需物理 iOS 设备 + 签名 + 部署，
  无人值守做不到。CLAUDE.md 里「真机零实测」这条只能由人类关闭。**不要反复尝试。**

---

# ⚙️ 环境与判据（每轮必读，别凭记忆）

## 三个工作树，别搞混

| 路径 | 分支 | 用途 |
|---|---|---|
| `~/Documents/flutter_hot_patcher` | `v1` | **本文件所在地**；生产分支 + `CLAUDE.md` + `memory/` |
| `~/dart-3122/sdk` | `shorebird-3.12.2` | **代码改动全部在这里**；主任务工作树 |
| `~/Documents/fhp-research` | `route-a-research` | 验证脚本 + 反汇编侦察文档；**他们的二进制永不入库** |

## ❗ `npm run build` / `npm run test` 在本项目**不存在**

这是 Dart SDK（C++/GN/ninja），不是 Node 项目。/loop 指令里那两条命令是模板默认值，
**照跑必然失败**。真实等价物：

```sh
# build（两个配置都要，Release 跑单测，Product 跑逐字节复现）
ninja -C ~/dart-3122/sdk/xcodebuild/ReleaseARM64 gen_snapshot run_vm_tests dartaotruntime
ninja -C ~/dart-3122/sdk/xcodebuild/ProductARM64 gen_snapshot dartaotruntime

# test（唯一权威判据，6 项检查 + 单测）
cd ~/Documents/fhp-research/spikes/shorebird_linkinfo_oracle && ./verify_all.sh
```

**新增单测后必须同步抬高 `verify_all.sh` 里的 `EXPECTED_TESTS`**，否则新测试不被
名字正则选中时连 SKIPPED 都不会打印（已踩两次）。

## 📊 基线（2026-08-25 实测，非记账）

```
verify_reproduction.sh     checked 24 artifact(s), 0 failure(s)
dd_pass_check.sh           0 failure(s)
dd_runtime_check.sh        0 failure(s)
op_link_info_check.sh      0 failure(s)
shorebird_info_check.sh    0 failure(s)
run_vm_tests               128 passed
6 ran, 0 failed, 0 skipped
```
两个 ninja 配置均 `no work to do`。工作树 clean，HEAD = `f426f46f5b0`。

## 🚨 验证纪律（本仓库的血泪，违反必出假绿）

1. **改完必须改坏看变红**。全绿只证明「没弄坏」，不证明「新代码被执行过」。
   每个任务的负控制写在任务卡里，**跑完要还原**。
2. **`ninja` 说 `no work to do` 才算构建新鲜**。时间戳会被 `mv .bak` 还原弄倒退。
3. **改 `#if defined(DART_PRECOMPILED_RUNTIME)` 里的代码必须用 `dartaotruntime` 验**，
   `run_vm_tests` 根本不编译那些块。
4. **`ASSERT` 在 release 构建里被编译掉**。要在 product 里守住的用 `RELEASE_ASSERT`。
5. **RTK 包装不可信**：`grep` / `git log` / `diff` 一律加 `command` 前缀。
6. **说某函数「已实现」之前 `grep -rn '<类名::方法名>' runtime/` 一次**。
   只搜方法名会把调用关系两端的两个函数并成一行（已发生过）。
7. **oracle 的两个输入可能是同一份文件**。用之前 `cmp` 一下。

## 🔁 /clear 的实际形态

`/clear` **不是我能调用的工具**。本循环靠 `ScheduleWakeup` 重新进入 `/loop` 协议，
上下文由 harness 自动压缩。**效果等价：每轮醒来先读本文件。**
所以本文件必须自足——**任何跨轮次的结论都要写进这里，不能只留在对话里**。

---

# 📌 任务卡（含验收判据与负控制）

## 任务 1：`ObjectPoolMappingsAggregator` — 加权投票

**为什么必须做**：`linker.cc:367-394` 当前实现**已知不是他们的算法**，
只是在当前 fixture 上碰巧给出相同的 1121。两处结构性错误：

| | 我们 | 他们 |
|---|---|---|
| 歧义组（组内 >1 成员） | `size() != 1` 直接丢弃 | **保留并投票**（§2.2c 穷举四种编码，全部 0 命中） |
| 仲裁 | `std::set<pair>` 去重 | `votes_[patch][base] += 1.0/N` + argmax + **全局单射** |

**算法全文**（`OP_AGGREGATOR_RECON.md` §(a)4/5/6/9，逐条经反汇编证实）：

```c++
struct ObjectPoolMappingsAggregator {           // 0x40 字节
  std::unordered_map<uword, std::unordered_map<uword, double>> votes_;  // +0x00, 40B
  std::vector<uword> used_;                                             // +0x28, 24B
};

// 累加（内联在调用方）：权重是 CodeInfo 记录数，不是索引数
w = 1.0 / (base_buffer.size() + patch_group.size());
votes_[pIdx[i]][bIdx[i]] += w;

intptr_t GetBestMapping(uword patch_index) {
  auto candidates = votes_[patch_index];        // ⚠️ operator[]，缺键要 default-insert
  std::vector<std::pair<uword,double>> sorted(candidates.begin(), candidates.end());
  std::sort(sorted.begin(), sorted.end(), [&patch_index](auto& a, auto& b) {
    if (a == b) return false;                   // 显式短路，是他们写的不是编译器产物
    if (a.second != b.second) return a.second > b.second;
    return a.first == patch_index;              // 平票时恒等映射胜出
  });
  for (auto& c : sorted) {
    if (std::find(used_.begin(), used_.end(), c.first) != used_.end()) continue;
    used_.push_back(c.first);                   // 全局单射，跨调用不清空
    return c.first;
  }
  return -1;
}
```

**三个不可从签名推出、必须照做的细节**：
- `used_` 是 `std::vector` 不是 `set`（8 字节步长 + 4× 展开的**线性** find + `push_back`）
- `GetBestMapping` **按 patch 索引升序**调用一次（`std::set<uword>` 驱动），这才让贪心确定
- **绝不 `reserve()`** 那个 unordered_map 的拷贝——桶宽历史决定平票时的残留顺序

**验收判据**：
- ⚠️ **`verify_all.sh` 全绿在这项任务上不是判据**（§(c)2：当前 fixture 判别不出两种算法）
- 真判据是**任务 3 的合成 fixture**。任务 1 只需保证 1121/1113/292/16 不变 + 单测覆盖
  投票/平票/单射三条路径

**负控制**（必须变红才算数）：
1. 把权重 `1.0/N` 改成常数 `1.0` → 多候选场景下 argmax 结果应变
2. 删掉 `used_` 的单射检查 → 两个 patch 索引会映射到同一 base 索引
3. 平票比较改成 `a.first != patch_index` → 恒等映射不再优先

## 任务 2：sticky `csel` 与 `self_hash_` 回落

```c++
bool use_self_pp = false;                       // 每个 patch op_subgraph_hash_ 组重置一次
for (const CodeInfo& pC : patch_group) {
  if (base_buffer.empty()) {                    // 0x10019c50c cmp x21,x24（唯一入边）
    base_buffer += base_self_hash_groups[pC.self_hash_];
    use_self_pp = true;                         // ⚠️ sticky：内层回边绕过那个写 0
  }
  const size_t off = use_self_pp ? 0x30 /*self_pp*/ : 0x48 /*subgraph_pp*/;
  ...
}
```
我们现在**无条件用 `self_pp_indices_`**，一般情况下是错的（base subgraph 组存在时该用 `subgraph_pp`）。

⚠️ **我在这里踩过假红**：曾用「全函数零个 `ldr [xN,#0x48]`」去否证 `+0x48` 的读取——
但那个偏移是**寄存器施加**的（`add x8,x20,x8`），立即数形式本就不可能存在。
**否证一个断言，判据必须可能命中它。**

## 任务 3：判别性合成 fixture（**任务 1/2 的唯一真判据**）

现有 fixture 判别不出来，因为每个匹配组都是 1:1、每个内层 map 只有一个权重 0.5 的候选，
贪心永远不拒绝。要造的输入（`op_link_info_check.sh` 已有 writer，他们的 `gen_snapshot` 读它）：
1. 某个 `op_subgraph_hash_` 组在一侧有 **2 个成员**（触发歧义组：我们丢弃、他们投票）
2. 两个 patch 索引的最佳候选是**同一个 base 索引**（触发单射拒绝与 `-1` 返回）
3. 一个 patch 的 `op_subgraph_hash_` 在 base 中**不存在**（触发 `self_hash_` 回落 + sticky）

然后 diff 我们的四行报告与他们的。**这一步做完，任务 1/2 才从「照着反汇编抄的」
升级成「行为验证过的」。**

## 任务 4：`LinkedValue<T>`

由两处 `vector::size()` 的除法常数算出 = base/patch 对：
类表 112 vs `sizeof(ClassInfo)`=56、对象池 16 vs `sizeof(uword)`=8，两个独立来源都恰好双倍。
`nm` 给出实例 `vector<LinkedValue<ClassInfo>>` / `vector<LinkedValue<unsigned long>>`。
元素序 `{base, patch}` 由 `mapping[second] = first` 证明。

## 任务 5：`object_pool_editor` 的两个软点

1. **两条断言用了 `ASSERT` 而非 `RELEASE_ASSERT`** → release 构建里被编译掉，
   `ObjectPoolEditor_CountFollowsPrepareLargeOffset` 在 product 里什么都不守。
2. **kind-1/2 在 offset 2²⁴ 之后计数分歧**：发射器 3、计数器 2，
   **这是我们自己读错了折叠 ladder**（recon 里那段），不是他们的 bug。
3. kind-3 index 62：发射器 2、计数器 3 —— 尚未定性，先查清再动。

## 任务 6：接进 `ImageWriter::Write`

唯一生产调用方是**上游** `dart::ImageWriter::Write`（`image_snapshot.cc`，我们本来就有这个文件）。
全 `__text` BL 扫描 13 处，其中 10 处在其体内。
**依赖**：那个循环要读 old→new 索引映射表 = 任务 1 产出的 `mapping[]`。**任务 1 不完成做不了。**

🎁 **他们自带 oracle**：`ImageWriter::Write` 在索引未变时会重新汇编并逐字节自校验，
打印 `"Expected:\n"` / `"Actual:\n"`（两串在二进制里各恰好 1 次，已验）。

---

# 📖 关键参考文档（别重新推导）

| 文档 | 内容 |
|---|---|
| `fhp-research/spikes/shorebird_linkinfo_oracle/OP_AGGREGATOR_RECON.md` | 任务 1/2 的算法全文 + 地址级证据 + 复现命令 |
| `fhp-research/spikes/shorebird_linkinfo_oracle/OBJECT_POOL_EDITOR_RECON.md` | 任务 5/6 |
| `memory/project_dart_sdk_fork.md` | 主任务全史（正文缺 2026-08-25 后半段，见下） |
| `memory/feedback_false_green_traps.md` | 19+ 种假绿陷阱 |
| `CLAUDE.md` | 规则 0-3，优先于本文件之外的一切 |

## ⚠️ 已知的记账不一致（待补）

`memory/project_dart_sdk_fork.md` 的 frontmatter `description` 已更新到最新
（提到 `f426f46f5b0`、加权投票聚合器），但**正文没有对应章节**——
`command grep '加权投票\|votes_\|OP_AGGREGATOR_RECON'` 在正文 0 命中。
2026-08-25 后半段的两项发现只活在 `MEMORY.md` 索引里。**任务 1 完成时顺手补进正文。**

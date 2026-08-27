# 外部触发器（launchd）

把循环的**触发权**从会话里搬到操作系统里。

## 为什么

`/loop 30m` 不建 cron（2026-08-27 实测：`CronCreate` 0 次、`ScheduleWakeup` 7 次）。
它是一条**自举链**——第 N+1 轮之所以存在，只因为第 N 轮活到了最后一步并排了下一次唤醒。
任何一轮整轮死掉（额度、API 拒绝、爆窗、网络抖动），**链条永久断开，不自愈、不报错**。
实测后果：08-26 18:41 停摆，到 09-27 09:34 才被人手动叫醒，空转 14 小时 53 分。

launchd 没有上下文窗口、没有额度、不依赖 API、开机就在跑。
**它的下一次触发不依赖上一次是否成功**——这是自举链无论怎么调都做不到的。

详见 `docs/LOOP_CONTRACT.md`。

## 装

```sh
cp tools/loop/net.tbu.fhp.loop.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/net.tbu.fhp.loop.plist
```

`RunAtLoad` 是 `false`，所以装上不会立刻开跑，第一次触发在 30 分钟后。
想立刻跑一轮：`launchctl start net.tbu.fhp.loop`。

## 停

| 目的 | 做法 |
|---|---|
| 临时暂停（保留任务） | `touch .loop/PAUSE` |
| 恢复 | `rm .loop/PAUSE` |
| 卸载 | `launchctl unload ~/Library/LaunchAgents/net.tbu.fhp.loop.plist` |
| 彻底删除 | 卸载后 `rm ~/Library/LaunchAgents/net.tbu.fhp.loop.plist` |

`PAUSE` 是硬开关，脚本里没有任何路径能绕过它。

## 看

```sh
tail -20 .loop/rounds.log
```

每轮无论成败都写一行心跳，**在派活之前就写**。这样「链断了」和「在跑但这轮没产出」
在磁盘上就不再同形——上次查清停摆时刻花了十几分钟翻 transcript 时间戳，就是因为缺这个。

## 脚本做的四件防护

| 防护 | 为什么 |
|---|---|
| **单实例锁**（`shlock`） | 一轮可能跑超 30 分钟。两轮同时动三个工作树会互相踩。`shlock` 认 pid，被杀的轮次不会把锁永久卡死 |
| **额度退避** | 撞墙后写 `.loop/blocked_until`，一小时内不再尝试。昨晚那种情况下，一天撞 48 次墙既学不到东西又烧钱 |
| **恢复前查脏树** | 被杀的子代理可能留下**打了一半的负控制**。直接接着跑会拿到一个来历不明的红，所以宁可拒绝启动。只看 tracked 文件的改动——状态仓库里未跟踪文件本来就一堆 |
| **超时看门狗** | macOS 没有 `timeout(1)`。挂死的一轮不能把锁扛过下一个周期 |

## ⚠️ 装之前必须先决定的一件事：权限模式

现在默认 `acceptEdits`，**它只自动批准文件编辑**。而每一轮真正要干的是
`ninja` 编译、`git commit`、跑 `verify_all.sh`——这些都是 Bash，
`acceptEdits` 会**停在第一次 Bash 批准上等一个不存在的人**。

也就是说：**照现在的默认值装上去，循环会挂着不动，不会报错。**

要真正无人值守，得把 plist 里的 `FHP_LOOP_PERMISSION_MODE` 改成 `bypassPermissions`。
代价说清楚：那等于**让一个 agent 在你机器上无人看管地拥有不受限的 shell，整夜运行**。
契约第七条的边界（禁止 `git add -A`、不改全局配置、外向操作要问人）届时**只剩提示词在拦**，
没有第二道机械防线。

这个取舍我不替你做。三个选项：

1. `bypassPermissions` —— 真无人值守，风险如上
2. `acceptEdits` + 人在旁边 —— 退化成「定时提醒你来按批准」，但停摆会自愈
3. 收窄授权：`--allowed-tools` 白名单（如 `Bash(ninja *) Bash(git *) Edit`）
   —— 折中，但白名单漏一条就是选项 2 的行为，且**没试过**

## 已知未验证

- `claude -p` 在 launchd 的最小环境下能否正常认证（**没跑过**）
- 一轮真实任务是否跑得完 `ROUND_TIMEOUT`（3000 秒）
- 选项 3 的白名单粒度够不够

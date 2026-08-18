---
name: project-roadmap
description: 未完成任务清单（自建分发基础设施居首）与关键架构结论：CDN 无需可信
metadata: 
  node_type: memory
  type: project
  originSessionId: dc4cce83-bc27-467b-8fb1-5ed4b50d62f0
  modified: 2026-08-18T06:21:41.250Z
---

**权威清单在 `docs/ROADMAP.md`（v1 分支），此处只记不易重新发现的结论。**

## 待办（2026-08-18 起）

1. **自建分发基础设施（服务器/云/CDN）** ← 用户 2026-08-18 指定
2. 设备经网络下载并 inflate 增量 —— 整条链路唯一从未验证的环节
3. 轮换签名私钥（`fhpb rotate-key`，见 [[project-route-b-cli]]）
4. `base_url` 缺失的护栏
5. Android 支持

## 关键架构结论：CDN 不需要可信

设备下载后独立校验 sha256 + RSA 签名（公钥编译在包里），
**所以下载源即使被篡改也会被拒绝**。分发可以干净地拆两半：

- `POST /api/v1/patches/{check,events}` → 必须是我们的服务（决定发什么）
- `GET <download_url>` → 任意 CDN / 对象存储，**无需可信**

`download_url` 由我们在 `index.json` 里指定，指向哪都行。

## 两个实测发现（别再重新推导）

- **更新器会发 `Range: bytes=N-`**（`network.rs:90`）做断点续传，
  `server.py` 忽略它一律返 200。不是正确性 bug（`network.rs:109` 写明
  「返 200 就从头来」），但每次断网都整包重下 → 选 CDN 时确认支持 Range。
- **`base_url` 缺失会静默回落 `https://api.shorebird.dev`**
  （`config.rs:21` 经 `.unwrap_or()`）。设备转去请求别人的服务器且无报错。

## `fhpb serve` 的定位

151 行 `ThreadingHTTPServer`，无 TLS / 鉴权 / 限流 / Range。
**只是协议实现，不是生产服务**。RUNBOOK 已加警告。

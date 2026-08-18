# vm_remap 真机探针

验证 iOS 真机在代码签名下是否允许 `vm_remap(copy=1, R|X)` 复制 `__TEXT`
里的可执行页并执行副本 —— 这是 `SimBridge`（C1/C2）与整条自建引擎路线的地基。

## 结果：PASS

iPhone 14 / iOS 26.6，2026-08-18：

```
FHP_PROBE=PASS remap_ok exec_ok got=41 page=16384
           src=0x100554000 dst=0x100718000 cur=5 max=5
```

- `vm_remap` 返回 `KERN_SUCCESS`
- 保护位 `cur=max=5` = `VM_PROT_READ|VM_PROT_EXECUTE`
- 副本被真实执行，`got=41`（`20*2+1`）正确
- 页大小 16384，与 `SimBridge::kPageSize` 一致

## 复现

把 `AppDelegate.probe.swift` 覆盖到某个已签名 iOS app 的
`ios/Runner/AppDelegate.swift`，构建安装后：

```bash
xcrun devicectl device process launch --device <UDID> --console <bundle-id>
```

**必须用 `--console`**：`NSLog` 的动态字符串在设备上被 os_log 按 `<private>`
屏蔽，`idevicesyslog` 抓不到；`%{public}@` 在 Swift 的 `NSLog` 里也不被解析
（会原样打印 `{public}@`）。走 `print()` 到 stdout 才拿得到。

# 4-B 补丁流水线设计规格

版本 v1.0 · 2026-08-04

---

## 0. 范围

**输入**：
- `manifest.json`（来自 4-A kernel_linker）
- `patch.dill`（来自 dart2bytecode，开发者在上游已生成）
- `private_key.pem`（Ed25519 私钥，离线保管）

**输出**：完整 `patch_bundle/`，符合 PATCH_DELIVERY_SPEC §1

**范围内**：
- Bundle 组装（bytecode/ + entry_table.bin + cid_map.bin）
- manifest.json 扩充（patch_id、artifact hashes、provenance 完整字段）
- manifest.sig 生成（Ed25519）
- 密钥对生成工具（单独 `keygen.py`）

**范围外**（暂缓）：
- dart2bytecode 自动调用（开发者手动准备 patch.dill）
- canonical_map.bin（4-D 运行时集成再加）
- 服务端上传（4-E）
- 客户端验签（4-D）

---

## 1. 文件结构

```
tools/patch_builder/
├── patch_builder.py   主工具：bundle 组装 + 签名
├── keygen.py          密钥对生成（一次性工具）
└── requirements.txt   cryptography>=42.0.0
```

---

## 2. CLI 接口

```bash
# 1. 生成密钥对（一次性）
python3 keygen.py --out keys/
# 生成 keys/private_key.pem + keys/public_key.pem

# 2. 构建 patch bundle
python3 patch_builder.py \
  --manifest   ./linker_output/manifest.json \   # 来自 4-A kernel_linker --output-dir
  --bytecode   ./patch.dill \                    # dart2bytecode 产物
  --private-key keys/private_key.pem \
  --patch-id   "patch-v7-ios-2026-08-04" \
  --app-version "1.0+3" \                        # 对应 target_build_fingerprint
  --output-dir  ./patch_bundle/

# 输出:
# patch_bundle/
# ├── manifest.json   (完整字段，含 artifact hashes)
# ├── manifest.sig    (Ed25519 分离式签名)
# ├── bytecode/
# │   └── patch.dill
# ├── entry_table.bin
# └── cid_map.bin
```

---

## 3. manifest.json 最终格式

扩充 4-A 产出的 manifest.json（保留所有 4-A 字段，新增以下）：

```json
{
  "format_version": "1",

  // ─── 4-A 字段（保留）───
  "dart_sdk_commit": "1aa7d7321fb",
  "baseline_sha256": "abc...",
  "changed_functions": ["...::greet"],
  "icf_affected": [],
  "affected_closure": ["...::callGreet"],
  "class_hierarchy_changed": false,

  // ─── 4-B 新增字段 ───
  "patch_id": "patch-v7-ios-2026-08-04",
  "patch_version": 7,
  "created_at": "2026-08-04T10:00:00Z",
  "platform": "ios",
  "payload_type": "bytecode",
  "target_build_fingerprint": "1.0+3",
  "sig_anchor_key_id": "anchor-2026-08-04",
  "sig_alg": "ed25519",
  "cert_chain": [],

  // ─── artifact hashes ───
  "artifacts": [
    {"path": "bytecode/patch.dill", "sha256": "...", "size": 439},
    {"path": "entry_table.bin", "sha256": "...", "size": 4},
    {"path": "cid_map.bin", "sha256": "...", "size": 4}
  ]
}
```

---

## 4. Ed25519 签名机制

签名对象：manifest.json 的**规范化字节**（键排序 + 无多余空白）

```python
import json, hashlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

def canonical_bytes(manifest: dict) -> bytes:
    """Deterministic JSON serialization (sorted keys, no extra whitespace)."""
    return json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode('utf-8')

def sign_manifest(manifest: dict, private_key: Ed25519PrivateKey) -> bytes:
    """Returns 64-byte Ed25519 signature."""
    return private_key.sign(canonical_bytes(manifest))
```

`manifest.sig` 文件格式：64 字节 raw Ed25519 signature（无 PEM 包装）

---

## 5. 验签伪代码（给 4-D 运行时集成的接口说明）

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

def verify_bundle(bundle_dir: str, embedded_pubkey_bytes: bytes) -> bool:
    manifest = json.load(open(f'{bundle_dir}/manifest.json'))
    sig = open(f'{bundle_dir}/manifest.sig', 'rb').read()
    pubkey = Ed25519PublicKey.from_public_bytes(embedded_pubkey_bytes)
    try:
        pubkey.verify(sig, canonical_bytes(manifest))
    except Exception:
        return False  # fail-closed

    # Verify artifact hashes
    for artifact in manifest['artifacts']:
        data = open(f'{bundle_dir}/{artifact["path"]}', 'rb').read()
        actual = hashlib.sha256(data).hexdigest()
        if actual != artifact['sha256']:
            return False
    return True
```

---

## 6. 安全要求（对齐 PATCH_DELIVERY_SPEC §2.2）

- 签名验证失败 → fail-closed，禁止部分应用
- 任一 artifact 哈希不符 → fail-closed
- `target_build_fingerprint` 不匹配 → fail-closed
- private_key.pem 不进代码库，CI 通过环境变量注入

---

## 7. 与其他里程碑接口

- **4-A kernel_linker**：提供 `manifest.json` + `entry_table.bin` + `cid_map.bin`（4-B 直接读取）
- **4-D 运行时集成**：读取 `patch_bundle/` 进行验签 + 加载
- **4-C Updater**：下载 `patch_bundle/`，触发 4-D 加载流程
- **4-E 服务端**：存储并下发 `patch_bundle/`

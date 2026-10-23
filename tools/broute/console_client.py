"""fhpb 的控制台 API 客户端：只用标准库，不引入新依赖。

配置位置：~/.fhpb/console.json（环境变量 FHPB_CONFIG 可改路径），内容 {"server": ..., "api_key": ...}。
环境变量 FHPB_SERVER + FHPB_API_KEY 优先于文件（CI 用）；FHPB_MODE=local 强制走本地仓库模式。
没有任何配置时 resolve() 返回 None，fhpb 保持原来的本地仓库行为。
"""
import hashlib
import http.client
import json
import os
import pathlib
import subprocess
import sys
import urllib.parse
import uuid
from typing import Optional

CONFIG_ENV = "FHPB_CONFIG"
SERVER_ENV = "FHPB_SERVER"
KEY_ENV = "FHPB_API_KEY"
MODE_ENV = "FHPB_MODE"
KEY_PREFIX = "sb_api_"
CHUNK = 1 << 20
TIMEOUT = 120


class ConsoleError(Exception):
    """服务端返回错误（或网络不通）。status 为 0 表示没连上。"""

    def __init__(self, status: int, code: str, message: str):
        """参数: status 为 HTTP 状态码；code 为服务端错误码；message 为说明。"""
        super().__init__(f"[{status} {code}] {message}" if status else message)
        self.status, self.code, self.message = status, code, message


def config_path() -> pathlib.Path:
    """配置文件路径。"""
    env = os.environ.get(CONFIG_ENV)
    return pathlib.Path(env) if env else pathlib.Path.home() / ".fhpb" / "console.json"


def restrict_file(path: pathlib.Path) -> None:
    """把文件收紧到只有当前用户可读写（POSIX 0600；Windows 用 icacls 去掉继承，尽力而为）。"""
    os.chmod(path, 0o600)
    if sys.platform == "win32":
        user = os.environ.get("USERNAME")
        if user:
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                           capture_output=True, check=False)


def save_config(server: str, api_key: str) -> pathlib.Path:
    """保存 server 地址与 API key，权限收紧到 0600；先建临时文件再改名，不留宽权限的窗口。"""
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"server": server.rstrip("/"), "api_key": api_key}, f, indent=2)
        f.write("\n")
    restrict_file(tmp)
    os.replace(tmp, p)
    return p


def resolve() -> Optional[tuple]:
    """取 (server, api_key)；未配置或 FHPB_MODE=local 返回 None（走本地仓库模式）。"""
    if os.environ.get(MODE_ENV) == "local":
        return None
    server, key = os.environ.get(SERVER_ENV), os.environ.get(KEY_ENV)
    if not (server and key):
        p = config_path()
        if p.exists():
            cfg = json.loads(p.read_text(encoding="utf-8"))
            server, key = server or cfg.get("server"), key or cfg.get("api_key")
    return (server.rstrip("/"), key) if server and key else None


def sha256_file(path: pathlib.Path) -> str:
    """文件的 sha256 十六进制。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


class Console:
    """控制台 API 客户端。示例: Console("http://h:8765", "sb_api_x").get_app("APP1")"""

    def __init__(self, server: str, api_key: str):
        """参数: server 为服务基址；api_key 为 sb_api_ 开头的个人 key。"""
        self.server = server.rstrip("/")
        self.api_key = api_key

    # ---------------------------------------------------------- 底层

    def _conn(self, url: str):
        """按 URL 建连接，返回 (连接, 路径加查询)。"""
        u = urllib.parse.urlsplit(url)
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        return cls(u.netloc, timeout=TIMEOUT), (u.path or "/") + (f"?{u.query}" if u.query else "")

    @staticmethod
    def _error(status: int, raw: bytes) -> ConsoleError:
        """把错误响应体（ErrorResponse）转成 ConsoleError，读不出就带原文。"""
        try:
            d = json.loads(raw)
            return ConsoleError(status, str(d.get("code", "")), str(d.get("message", "")))
        except (ValueError, AttributeError):
            return ConsoleError(status, "http_error", raw[:200].decode("utf-8", "replace"))

    def call(self, method: str, path: str, body=None, query: Optional[dict] = None, ok=(200, 201, 204)):
        """调一个 API。返回解码后的 JSON（204/304/空体返回 None）。

        参数: ok 为视为成功的状态码集合（rollback 的 304 要放行）；其余状态抛 ConsoleError。
        """
        url = self.server + path + (("?" + urllib.parse.urlencode(query)) if query else "")
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn, rel = self._conn(url)
        try:
            conn.request(method, rel, body=data, headers=headers)
            r = conn.getresponse()
            raw = r.read()
        except OSError as e:
            raise ConsoleError(0, "unreachable", f"连不上 {self.server}: {e}")
        finally:
            conn.close()
        if r.status not in ok:
            raise self._error(r.status, raw)
        return json.loads(raw) if raw and r.status not in (204, 304) else None

    def pages(self, path: str, key: str):
        """按 cursor 翻完一个列表端点，返回 key 下的全部元素。"""
        out, cursor = [], None
        while True:
            q = {"per_page": 100}
            if cursor:
                q["cursor"] = cursor
            d = self.call("GET", path, query=q)
            out += d.get(key, [])
            cursor = d.get("next_cursor")
            if not cursor:
                return out

    def upload(self, url: str, path: pathlib.Path, size: int) -> None:
        """把文件按 multipart 流式 POST 到上传 URL（令牌即凭据，不带 API key）。"""
        boundary = uuid.uuid4().hex
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        conn, rel = self._conn(url)
        try:
            conn.putrequest("POST", rel)
            conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            conn.putheader("Content-Length", str(len(head) + size + len(tail)))
            conn.endheaders()
            conn.send(head)
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(CHUNK), b""):
                    conn.send(chunk)
            conn.send(tail)
            r = conn.getresponse()
            raw = r.read()
        except OSError as e:
            raise ConsoleError(0, "unreachable", f"上传失败: {e}")
        finally:
            conn.close()
        if r.status != 204:
            raise self._error(r.status, raw)

    def download(self, url: str, dest: pathlib.Path, sha256: Optional[str] = None) -> None:
        """流式下载到 dest（先写 .part 再改名）。给了 sha256 就核对，不符删文件并抛错。"""
        conn, rel = self._conn(url)
        part = dest.with_name(dest.name + ".part")
        h = hashlib.sha256()
        try:
            conn.request("GET", rel)
            r = conn.getresponse()
            if r.status != 200:
                raise self._error(r.status, r.read())
            dest.parent.mkdir(parents=True, exist_ok=True)
            with part.open("wb") as f:
                for chunk in iter(lambda: r.read(CHUNK), b""):
                    h.update(chunk)
                    f.write(chunk)
        except OSError as e:
            raise ConsoleError(0, "unreachable", f"下载失败: {e}")
        finally:
            conn.close()
        if sha256 and h.hexdigest() != sha256:
            part.unlink(missing_ok=True)
            raise ConsoleError(0, "hash_mismatch", f"下载内容 sha256 {h.hexdigest()} 与登记的 {sha256} 不符")
        os.replace(part, dest)

    # ---------------------------------------------------------- 业务端点（路径照 spec）

    def whoami_keys(self) -> list:
        """列自己的 API key（用来验证 key 是否可用）。"""
        return self.call("GET", "/api/v1/users/me/api-keys")["keys"]

    def create_key(self, name: str, days: Optional[int]) -> dict:
        """签发新 API key，返回含明文 api_key 的响应。days 为 None 表示永不过期。"""
        return self.call("POST", "/api/v1/users/me/api-keys", {"name": name, "expires_in_days": days})

    def get_app(self, app_id: str) -> dict:
        """取 App 详情。"""
        return self.call("GET", f"/api/v1/apps/{app_id}")

    def releases(self, app_id: str) -> list:
        """某 App 的全部 release（新的在前）。"""
        return self.pages(f"/api/v1/apps/{app_id}/releases", "releases")

    def find_release(self, app_id: str, version: str) -> Optional[dict]:
        """按版本号找 release，没有返回 None。"""
        return next((r for r in self.releases(app_id) if r["version"] == version), None)

    def create_release(self, app_id: str, version: str, flutter_revision: str) -> dict:
        """新建 release，返回 Release。"""
        return self.call("POST", f"/api/v1/apps/{app_id}/releases",
                         {"version": version, "flutter_revision": flutter_revision})["release"]

    def release_artifacts(self, app_id: str, rid: int) -> list:
        """已 ready 的 release 产物（带 10 分钟有效的下载 URL）。"""
        return self.call("GET", f"/api/v1/apps/{app_id}/releases/{rid}/artifacts")["artifacts"]

    def create_release_artifact(self, app_id: str, rid: int, **body) -> dict:
        """登记 release 产物，返回含上传 url 的响应。"""
        return self.call("POST", f"/api/v1/apps/{app_id}/releases/{rid}/artifacts", body)

    def delete_release_artifacts(self, app_id: str, rid: int) -> None:
        """删 release 全部产物（还有未回滚补丁时服务端 409）。"""
        self.call("DELETE", f"/api/v1/apps/{app_id}/releases/{rid}/artifacts")

    def patches(self, app_id: str, rid: int) -> list:
        """release 的全部补丁（含已回滚，编号升序）。"""
        return self.pages(f"/api/v1/apps/{app_id}/releases/{rid}/patches", "patches")

    def channels(self, app_id: str) -> list:
        """App 的渠道列表。"""
        return self.call("GET", f"/api/v1/apps/{app_id}/channels")

    def create_channel(self, app_id: str, name: str) -> dict:
        """新建渠道。"""
        return self.call("POST", f"/api/v1/apps/{app_id}/channels", {"channel": name})

    def create_patch(self, app_id: str, rid: int, metadata: dict) -> dict:
        """新建补丁，编号由服务端分配，返回 {id, number}。"""
        return self.call("POST", f"/api/v1/apps/{app_id}/patches", {"release_id": rid, "metadata": metadata})

    def create_patch_artifact(self, app_id: str, pid: int, **body) -> dict:
        """登记补丁产物，返回含上传 url 的响应。"""
        return self.call("POST", f"/api/v1/apps/{app_id}/patches/{pid}/artifacts", body)

    def promote(self, app_id: str, pid: int, channel_id: int) -> None:
        """把补丁晋升到渠道。"""
        self.call("POST", f"/api/v1/apps/{app_id}/patches/promote", {"patch_id": pid, "channel_id": channel_id})

    def set_notes(self, app_id: str, rid: int, pid: int, notes: str) -> None:
        """改补丁备注。"""
        self.call("PATCH", f"/api/v1/apps/{app_id}/releases/{rid}/patches/{pid}", {"notes": notes})

    def rollback(self, app_id: str, rid: int, pid: int) -> bool:
        """回滚补丁；本来就已回滚（304）返回 False。"""
        return self._flip(app_id, rid, pid, "rollback")

    def rollforward(self, app_id: str, rid: int, pid: int) -> bool:
        """撤销回滚；本来就没回滚（304）返回 False。"""
        return self._flip(app_id, rid, pid, "rollforward")

    def _flip(self, app_id: str, rid: int, pid: int, verb: str) -> bool:
        """rollback / rollforward 的共同实现。"""
        path = f"/api/v1/apps/{app_id}/releases/{rid}/patches/{pid}/{verb}"
        url = self.server + path
        conn, rel = self._conn(url)
        try:
            conn.request("POST", rel, headers={"Authorization": f"Bearer {self.api_key}"})
            r = conn.getresponse()
            raw = r.read()
        except OSError as e:
            raise ConsoleError(0, "unreachable", f"连不上 {self.server}: {e}")
        finally:
            conn.close()
        if r.status == 304:
            return False
        if r.status != 204:
            raise self._error(r.status, raw)
        return True

    def device_check(self, req: dict) -> dict:
        """走设备协议 check（无需鉴权），用来复核设备实际会收到什么。"""
        conn, rel = self._conn(self.server + "/api/v1/patches/check")
        try:
            conn.request("POST", rel, body=json.dumps(req).encode(),
                         headers={"Content-Type": "application/json"})
            r = conn.getresponse()
            raw = r.read()
        except OSError as e:
            raise ConsoleError(0, "unreachable", f"连不上 {self.server}: {e}")
        finally:
            conn.close()
        if r.status != 200:
            raise self._error(r.status, raw)
        return json.loads(raw)

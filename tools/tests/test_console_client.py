#!/usr/bin/env python3
"""console_client 与 cli 控制台辅助函数的单测：只用标准库，起一个假 HTTP 服务当对端。

运行：python3 tools/tests/test_console_client.py
"""
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "broute"))
import console_client  # noqa: E402
from console_client import Console, ConsoleError  # noqa: E402

# 假服务收到的请求记录：(方法, 路径, 头, 体)
SEEN = []
# 路径 -> (状态码, 体字节)；没登记的路径答 404 错误信封
ROUTES = {}


class Fake(BaseHTTPRequestHandler):
    """按 ROUTES 答复并记录请求的假服务。"""

    def log_message(self, *a):
        """静音。"""

    def _serve(self):
        """记录请求并按 ROUTES 回答。"""
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n) if n else b""
        SEEN.append((self.command, self.path, dict(self.headers), body))
        status, data = ROUTES.get((self.command, self.path.split("?")[0]),
                                  (404, b'{"code":"not_found","message":"nope"}'))
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PATCH = do_DELETE = _serve


class ClientTests(unittest.TestCase):
    """Console 客户端的行为。"""

    @classmethod
    def setUpClass(cls):
        """起假服务。"""
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        """关假服务。"""
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        """每个用例清空记录与路由。"""
        SEEN.clear()
        ROUTES.clear()
        self.con = Console(self.url, "sb_api_testkey")
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def test_bearer_header_and_json_body(self):
        """API 调用带 Bearer key，请求体是 JSON。"""
        ROUTES[("POST", "/api/v1/apps/A/patches")] = (201, b'{"id": 5, "number": 3}')
        r = self.con.create_patch("A", 9, {"k": 1})
        self.assertEqual(r["number"], 3)
        _, _, hdr, body = SEEN[0]
        self.assertEqual(hdr["Authorization"], "Bearer sb_api_testkey")
        self.assertEqual(json.loads(body), {"release_id": 9, "metadata": {"k": 1}})

    def test_error_envelope_mapped(self):
        """错误信封转成带状态码与 code 的 ConsoleError。"""
        ROUTES[("GET", "/api/v1/apps/X")] = (404, b'{"code":"app_not_found","message":"App missing"}')
        with self.assertRaises(ConsoleError) as cm:
            self.con.get_app("X")
        self.assertEqual((cm.exception.status, cm.exception.code), (404, "app_not_found"))

    def test_non_json_error_body(self):
        """对端不是 JSON 错误体时也不崩，带出原文。"""
        ROUTES[("GET", "/api/v1/apps/X")] = (502, b"<html>bad gateway</html>")
        with self.assertRaises(ConsoleError) as cm:
            self.con.get_app("X")
        self.assertEqual(cm.exception.status, 502)
        self.assertIn("bad gateway", cm.exception.message)

    def test_unreachable(self):
        """连不上时抛 status=0 的 ConsoleError，而不是裸 OSError。"""
        with self.assertRaises(ConsoleError) as cm:
            Console("http://127.0.0.1:1", "sb_api_x").get_app("A")
        self.assertEqual(cm.exception.status, 0)

    def test_pagination_follows_cursor(self):
        """列表按 next_cursor 翻到底。"""
        path = ("GET", "/api/v1/apps/A/releases")
        calls = []

        class Pager(Fake):
            """第一页带 cursor，第二页不带。"""

            def _serve(self):
                """按 query 里有没有 cursor 回答不同页。"""
                SEEN.append((self.command, self.path, dict(self.headers), b""))
                calls.append(self.path)
                data = (b'{"releases":[{"version":"b"}]}' if "cursor=c1" in self.path
                        else b'{"releases":[{"version":"a"}],"next_cursor":"c1"}')
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            do_GET = _serve

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Pager)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            got = Console(f"http://127.0.0.1:{srv.server_address[1]}", "sb_api_x").releases("A")
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual([r["version"] for r in got], ["a", "b"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(path[0], "GET")

    def test_upload_is_multipart_without_api_key(self):
        """上传是 multipart、字节完整，且不把 API key 发给上传 URL（令牌即凭据）。"""
        ROUTES[("POST", "/api/v1/uploads/tok")] = (204, b"")
        f = self.tmp / "x.bin"
        payload = os.urandom(3 * (1 << 20) + 17)
        f.write_bytes(payload)
        self.con.upload(self.url + "/api/v1/uploads/tok", f, len(payload))
        _, _, hdr, body = SEEN[0]
        self.assertTrue(hdr["Content-Type"].startswith("multipart/form-data; boundary="))
        self.assertNotIn("Authorization", hdr)
        self.assertEqual(int(hdr["Content-Length"]), len(body))
        self.assertIn(payload, body)

    def test_upload_error_raised(self):
        """上传被拒（如大小不符 400）抛出服务端错误。"""
        ROUTES[("POST", "/api/v1/uploads/t2")] = (400, b'{"code":"size_mismatch","message":"x"}')
        f = self.tmp / "y.bin"
        f.write_bytes(b"abc")
        with self.assertRaises(ConsoleError) as cm:
            self.con.upload(self.url + "/api/v1/uploads/t2", f, 3)
        self.assertEqual(cm.exception.code, "size_mismatch")

    def test_download_checks_sha256(self):
        """下载核对 sha256：对得上落盘，对不上删临时文件并抛错。"""
        data = os.urandom(5000)
        ROUTES[("GET", "/d/ok")] = (200, data)
        dest = self.tmp / "a" / "ok.bin"
        self.con.download(self.url + "/d/ok", dest, hashlib.sha256(data).hexdigest())
        self.assertEqual(dest.read_bytes(), data)
        bad = self.tmp / "bad.bin"
        with self.assertRaises(ConsoleError) as cm:
            self.con.download(self.url + "/d/ok", bad, "0" * 64)
        self.assertEqual(cm.exception.code, "hash_mismatch")
        self.assertFalse(bad.exists())
        self.assertFalse((self.tmp / "bad.bin.part").exists())

    def test_rollback_304_is_false(self):
        """回滚/撤销回滚遇到 304（本来就是那个状态）返回 False，204 返回 True。"""
        base = "/api/v1/apps/A/releases/1/patches/2"
        ROUTES[("POST", base + "/rollback")] = (304, b"")
        ROUTES[("POST", base + "/rollforward")] = (204, b"")
        self.assertFalse(self.con.rollback("A", 1, 2))
        self.assertTrue(self.con.rollforward("A", 1, 2))

    def test_rollback_error_raised(self):
        """回滚遇到 404 抛错而不是当成功。"""
        with self.assertRaises(ConsoleError):
            self.con.rollback("A", 1, 99)


class ConfigTests(unittest.TestCase):
    """配置文件与模式选择。"""

    def setUp(self):
        """隔离环境变量与配置路径。"""
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.saved = {k: os.environ.get(k) for k in
                      (console_client.CONFIG_ENV, console_client.SERVER_ENV, console_client.KEY_ENV,
                       console_client.MODE_ENV)}
        for k in self.saved:
            os.environ.pop(k, None)
        os.environ[console_client.CONFIG_ENV] = str(self.tmp / "sub" / "console.json")

    def tearDown(self):
        """还原环境变量。"""
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_unconfigured_is_local_mode(self):
        """什么都没配时返回 None，fhpb 走本地仓库模式。"""
        self.assertIsNone(console_client.resolve())

    def test_save_and_resolve(self):
        """保存后能读回，server 去掉末尾斜杠。"""
        console_client.save_config("http://h:1/", "sb_api_k")
        self.assertEqual(console_client.resolve(), ("http://h:1", "sb_api_k"))

    @unittest.skipIf(sys.platform == "win32", "Windows 没有 POSIX 权限位")
    def test_config_file_mode_0600(self):
        """配置文件权限是 0600，且没有遗留临时文件。"""
        p = console_client.save_config("http://h:1", "sb_api_k")
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertEqual([x.name for x in p.parent.iterdir()], ["console.json"])

    def test_env_overrides_file(self):
        """环境变量优先于文件。"""
        console_client.save_config("http://file:1", "sb_api_file")
        os.environ[console_client.SERVER_ENV] = "http://env:2"
        os.environ[console_client.KEY_ENV] = "sb_api_env"
        self.assertEqual(console_client.resolve(), ("http://env:2", "sb_api_env"))

    def test_mode_local_forces_local(self):
        """FHPB_MODE=local 压过任何配置。"""
        console_client.save_config("http://h:1", "sb_api_k")
        os.environ[console_client.MODE_ENV] = "local"
        self.assertIsNone(console_client.resolve())

    def test_half_configured_is_local(self):
        """只有 server 没有 key 不算配置好。"""
        os.environ[console_client.SERVER_ENV] = "http://env:2"
        self.assertIsNone(console_client.resolve())


class CliHelperTests(unittest.TestCase):
    """cli.py 里控制台相关的纯函数（需要 cryptography 的跳过）。"""

    @classmethod
    def setUpClass(cls):
        """导入 cli；缺依赖时整组跳过。"""
        try:
            import cli  # noqa: F401
            cls.cli = cli
        except ModuleNotFoundError as e:
            raise unittest.SkipTest(f"缺依赖: {e}")

    def test_upload_plan_includes_symbols_tar(self):
        """symbols 目录打成 tar 上传；伴随文件用 fhpb: 前缀的 arch；缺的可选文件不列。"""
        tmp = pathlib.Path(tempfile.mkdtemp())
        rel = tmp / "rel"
        (rel / "symbols").mkdir(parents=True)
        (rel / "symbols" / "a.symbols").write_text("s")
        for n in ("App.baseline", "release.json", "app.dill", "base.blob"):
            (rel / n).write_bytes(b"x")
        plan = self.cli.release_upload_plan(rel, tmp)
        archs = [a for a, _ in plan]
        self.assertEqual(archs[0], "aarch64")
        self.assertIn("fhpb:symbols.tar", archs)
        self.assertNotIn("fhpb:base.aot", archs)
        self.assertTrue(all(p.exists() for _, p in plan))

    def test_patch_number_refused(self):
        """控制台模式传 number 直接退出：号只能由服务端分配（发生在碰服务端之前）。"""
        with self.assertRaises(SystemExit):
            self.cli.publish_vmcode_remote(None, "A", {"id": 1, "version": "v"}, pathlib.Path("x"),
                                           pathlib.Path("y"), channel="stable", private_key=None, pub_b64=None,
                                           note=None, patch_tool=pathlib.Path("z"), metadata={},
                                           out_dir=pathlib.Path("."), number=7)

    def test_resolve_app_ids_prefers_flag(self):
        """--app-id 优先；否则读 --app-dir 的 yaml；再否则读本地仓库 release.json。"""
        tmp = pathlib.Path(tempfile.mkdtemp())

        class A:
            """参数桩。"""
            app_id = None
            app_dir = None

        a = A()
        (tmp / "releases" / "1.0+1").mkdir(parents=True)
        (tmp / "releases" / "1.0+1" / "release.json").write_text(json.dumps({"app_id": "R"}))
        self.assertEqual(self.cli.resolve_app_ids(a, tmp), ["R"])
        app = tmp / "app"
        app.mkdir()
        (app / "shorebird.yaml").write_text("app_id: Y\n")
        a.app_dir = str(app)
        self.assertEqual(self.cli.resolve_app_ids(a, tmp), ["Y"])
        a.app_id = "F"
        self.assertEqual(self.cli.resolve_app_ids(a, tmp), ["F"])


if __name__ == "__main__":
    unittest.main()

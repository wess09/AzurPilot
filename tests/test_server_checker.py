"""服务器状态检查器的 API 协议与故障恢复测试。"""

import threading
import unittest
from json import JSONDecodeError
from unittest.mock import Mock, patch

import requests

from module.exception import ScriptError, WorkerStop
from module.server_checker import ServerChecker

API_BASE = "https://server-checker.nanoda.work/api/v1/servers"


def make_response(status_code=200, payload=None, text=""):
    """创建 requests.Response 的最小替身，避免测试访问真实服务。"""
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload
    return response


def make_server_payload(server_id, name, status):
    """创建单服务器端点的成功响应。"""
    return {
        "region": "test",
        "region_name": "测试区服",
        "server": {
            "id": server_id,
            "name": name,
            "status": status,
            "tag": None,
        },
    }


class ServerCheckerTestCase(unittest.TestCase):
    """为每个测试提供不会访问网络的 requests.Session。"""

    def setUp(self):
        self.session = Mock()
        self.session.get.return_value = make_response(
            payload=make_server_payload(1, "测试服务器", "normal")
        )
        self.session_patch = patch(
            "module.server_checker.requests.Session", return_value=self.session
        )
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)

    def build_checker(self, server, response=None):
        """以指定首个响应构造检查器。"""
        if response is not None:
            self.session.get.return_value = response
        return ServerChecker(server)

    def assert_requested_server(self, composite_id):
        """断言单服务器查询使用 HTTPS、复合 ID 与 15 秒超时。"""
        self.session.get.assert_called_once()
        args, kwargs = self.session.get.call_args
        url = kwargs.get("url", args[0] if args else None)
        self.assertEqual(url, f"{API_BASE}/{composite_id}")
        self.assertEqual(kwargs.get("timeout"), 15)


class TestServerMapping(ServerCheckerTestCase):
    """配置键必须映射到 API 固定复合 ID，不能依赖列表序号推导。"""

    def test_config_keys_use_expected_api_composite_ids(self):
        cases = (
            ("cn_android-0", "cn_1", 1, "莱茵演习"),
            ("cn_ios-0", "cn_ios_1", 1, "夏威夷"),
            ("cn_channel-0", "cn_channel_1", 1, "皇家巡游"),
            ("en-6", "en_7", 7, "Belfast"),
            # JP 的本地索引 2 对应 API ID 4，验证不能按 index + 1 推导。
            ("jp-2", "jp_4", 4, "佐世保"),
            ("tw-4", "tw_5", 5, "雷伊泰灣"),
        )

        for config_key, composite_id, server_id, name in cases:
            with self.subTest(config_key=config_key):
                self.session.get.reset_mock()
                self.session.get.return_value = make_response(
                    payload=make_server_payload(server_id, name, "normal")
                )

                checker = self.build_checker(config_key)

                self.assertTrue(checker.is_available())
                self.assert_requested_server(composite_id)

    def test_disabled_does_not_create_network_request(self):
        checker = self.build_checker("disabled")

        self.assertTrue(checker.is_available())
        self.session.get.assert_not_called()


class TestServerStatus(ServerCheckerTestCase):
    """API 状态值必须转换为调度器使用的可用性布尔值。"""

    def test_available_statuses_are_accepted(self):
        for status in ("normal", "full", "reg_full"):
            with self.subTest(status=status):
                self.session.get.reset_mock()
                self.session.get.return_value = make_response(
                    payload=make_server_payload(1, "莱茵演习", status)
                )

                checker = self.build_checker("cn_android-0")

                self.assertTrue(checker.is_available())

    def test_unavailable_statuses_are_retried_later(self):
        for status in ("maintenance", "unopened", "unknown"):
            with self.subTest(status=status):
                self.session.get.reset_mock()
                self.session.get.return_value = make_response(
                    payload=make_server_payload(1, "莱茵演习", status)
                )

                checker = self.build_checker("cn_android-0")

                self.assertFalse(checker.is_available())
                self.assertGreater(checker._timer.limit, 0)

    def test_recovery_is_reported_once_after_server_becomes_available(self):
        self.session.get.return_value = make_response(
            payload=make_server_payload(1, "莱茵演习", "maintenance")
        )
        checker = self.build_checker("cn_android-0")
        self.assertFalse(checker.is_available())

        self.session.get.return_value = make_response(
            payload=make_server_payload(1, "莱茵演习", "normal")
        )
        checker.check_now()

        self.assertTrue(checker.is_available())
        self.assertTrue(checker.is_recovered())
        self.assertFalse(checker.is_recovered())

    def test_wait_until_available_stops_without_waiting_for_maintenance_timer(self):
        self.session.get.return_value = make_response(
            payload=make_server_payload(1, "莱茵演习", "maintenance")
        )
        checker = self.build_checker("cn_android-0")
        stop_event = threading.Event()
        stop_event.set()

        with self.assertRaises(WorkerStop):
            checker.wait_until_available(stop_event=stop_event)


class TestServerApiFailure(ServerCheckerTestCase):
    """临时 API 故障应走快速重试，协议错误应作为脚本错误暴露。"""

    def test_not_found_for_known_local_server_is_allowed(self):
        checker = self.build_checker(
            "tw-0", make_response(status_code=404, text='{"detail": "not found"}')
        )

        self.assertTrue(checker.is_available())
        self.assert_requested_server("tw_1")

    def test_transient_http_errors_use_fast_retry(self):
        for status_code in (429, 502):
            with self.subTest(status_code=status_code):
                self.session.get.reset_mock()
                self.session.get.return_value = make_response(
                    status_code=status_code, text="temporary failure"
                )
                with patch.object(ServerChecker, "fast_retry", return_value=True) as retry:
                    checker = self.build_checker("cn_android-0")

                self.assertTrue(checker.is_available())
                retry.assert_called_once_with()

    def test_connection_and_read_timeout_use_fast_retry(self):
        for error in (
            requests.exceptions.ConnectionError("connection failed"),
            requests.exceptions.ReadTimeout("read timed out"),
        ):
            with self.subTest(error=type(error).__name__):
                self.session.get.reset_mock()
                self.session.get.side_effect = error
                with patch.object(ServerChecker, "fast_retry", return_value=True) as retry:
                    checker = self.build_checker("cn_android-0")

                self.assertTrue(checker.is_available())
                retry.assert_called_once_with()
                self.session.get.side_effect = None

    def test_invalid_json_raises_script_error_from_loader(self):
        checker = self.build_checker(
            "cn_android-0",
            make_response(payload=make_server_payload(1, "莱茵演习", "normal")),
        )
        response = make_response(text="not json")
        response.json.side_effect = JSONDecodeError("invalid JSON", "not json", 0)
        self.session.get.return_value = response

        with self.assertRaises(ScriptError):
            checker._load_server()

    def test_missing_server_status_raises_script_error_from_loader(self):
        checker = self.build_checker(
            "cn_android-0",
            make_response(payload=make_server_payload(1, "莱茵演习", "normal")),
        )
        self.session.get.return_value = make_response(
            payload={"region": "cn", "region_name": "国服", "server": {"id": 1}}
        )

        with self.assertRaises(ScriptError):
            checker._load_server()

    def test_wrong_server_id_raises_script_error_from_loader(self):
        checker = self.build_checker(
            "cn_android-0",
            make_response(payload=make_server_payload(1, "莱茵演习", "normal")),
        )
        self.session.get.return_value = make_response(
            payload=make_server_payload(2, "莱茵演习", "normal")
        )

        with self.assertRaises(ScriptError):
            checker._load_server()


if __name__ == "__main__":
    unittest.main()

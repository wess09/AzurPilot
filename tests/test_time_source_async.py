"""后台校时的阻塞、缓存、重试与并发回归，不访问真实网络。"""

import os
import threading
import time
import unittest
from unittest.mock import Mock, patch
from module.config.time_source import NetworkTimeSource


class TestAsyncNtp(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {"AZURPILOT_NTP_DISABLE": "0", "AZURPILOT_NTP_SERVERS": "test.invalid"},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.source = NetworkTimeSource()
        self.source._log_info = Mock()
        self.source._log_warning = Mock()

    def finish(self):
        self.source._refresh_thread.join(2)
        self.assertFalse(self.source._refresh_thread.is_alive())

    def test_slow_dns_does_not_block_any_time_reader_or_duplicate_query(self):
        entered = threading.Event()
        release = threading.Event()

        def query(host):
            entered.set()
            release.wait(3)
            raise OSError("DNS 不可用")

        self.source._query_server = Mock(side_effect=query)
        try:
            results = []

            def read():
                results.extend(
                    [self.source.timestamp(), self.source.now(), self.source.status()]
                )

            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            reader.join(1)
            self.assertFalse(reader.is_alive(), "读取时间被 DNS 阻塞")
            self.assertTrue(entered.wait(1))
            self.assertEqual(len(results), 3)
            self.assertLess(abs(results[0] - time.time()), 2)
            threads = [
                threading.Thread(
                    target=lambda: self.source.refresh(force=True), daemon=True
                )
                for _ in range(10)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(1)
                self.assertFalse(t.is_alive())
            self.source._query_server.assert_called_once()
            self.assertTrue(self.source._refresh_thread.daemon)
        finally:
            release.set()
            self.finish()

    def test_success_publishes_cached_time(self):
        self.source._query_server = Mock(return_value=12.5)
        self.source.refresh()
        self.finish()
        self.assertTrue(self.source.synced)
        self.assertAlmostEqual(self.source.timestamp() - time.time(), 12.5, delta=0.1)
        self.assertEqual(self.source.status()["server"], "test.invalid")
        self.source._query_server.assert_called_once()

    def test_failed_refresh_keeps_last_success(self):
        self.source._query_server = Mock(return_value=4)
        self.source.refresh()
        self.finish()
        baseline = (self.source.base_timestamp, self.source.base_monotonic)
        self.source._query_server = Mock(side_effect=OSError("DNS 不可用"))
        self.source.refresh(force=True)
        self.finish()
        self.assertTrue(self.source.synced)
        self.assertEqual(
            baseline, (self.source.base_timestamp, self.source.base_monotonic)
        )
        self.assertAlmostEqual(self.source.timestamp() - time.time(), 4, delta=0.1)

    def test_failure_backoff_prevents_query_on_every_screenshot(self):
        self.source._query_server = Mock(side_effect=OSError("DNS 不可用"))
        self.source.refresh()
        self.finish()
        for _ in range(20):
            self.source.timestamp()
            self.source.status()
        self.source._query_server.assert_called_once()
        self.assertGreater(self.source.retry_after_monotonic, time.monotonic())
        self.assertFalse(self.source._refreshing)
        self.source.refresh(force=True)
        self.finish()
        self.assertEqual(self.source._query_server.call_count, 2)

    def test_disabled_never_starts_thread(self):
        with patch.dict(os.environ, {"AZURPILOT_NTP_DISABLE": "1"}):
            self.source._query_server = Mock()
            self.assertAlmostEqual(self.source.timestamp(), time.time(), delta=0.1)
            self.assertIsNone(self.source._refresh_thread)
            self.source._query_server.assert_not_called()

    def test_expired_success_refreshes_in_background(self):
        self.source._query_server = Mock(return_value=1)
        self.source.refresh()
        self.finish()
        self.source.last_sync_monotonic -= self.source.refresh_interval + 1
        self.source.refresh()
        self.finish()
        self.assertEqual(self.source._query_server.call_count, 2)


if __name__ == "__main__":
    unittest.main()

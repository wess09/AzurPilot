import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from deploy.git import GitManager as DeployGitManager
from deploy.Windows.git import GitManager as WindowsGitManager
from deploy.git_over_cdn.client import GitOverCdnClient
from deploy.git_over_cdn.endpoints import CLOUDFLARE_UPDATE_URLS, FALLBACK_UPDATE_URLS


class TestGitOverCdnClient(unittest.TestCase):
    @staticmethod
    def _client(urls=None, fallback_urls=None):
        return GitOverCdnClient(
            url=urls or ['https://one.example', 'https://two.example'],
            fallback_urls=fallback_urls,
            folder='.',
        )

    @staticmethod
    def _response(ok=True, text=None, status_code=200):
        response = MagicMock()
        response.ok = ok
        response.text = text or '{"commit": "0123456789abcdef0123456789abcdef01234567"}'
        response.status_code = status_code
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def test_probe_url_accepts_valid_latest_commit_within_timeout(self):
        client = self._client()
        session = MagicMock()
        session.get.return_value = self._response()

        with (
            patch.object(client, '_create_session', return_value=session),
            patch('deploy.git_over_cdn.client.time.perf_counter', side_effect=[0.0, 0.25]),
        ):
            self.assertEqual(0.25, client.probe_url('https://one.example', timeout=5))

        session.get.assert_called_once_with(
            'https://one.example/latest.json', timeout=5, allow_redirects=False
        )
        session.close.assert_called_once_with()

    def test_probe_url_rejects_invalid_or_slow_response(self):
        client = self._client()
        invalid_session = MagicMock()
        invalid_session.get.return_value = self._response(text='{"commit": "invalid"}')

        with (
            patch.object(client, '_create_session', return_value=invalid_session),
            patch('deploy.git_over_cdn.client.time.perf_counter', side_effect=[0.0, 0.25]),
        ):
            self.assertIsNone(client.probe_url('https://one.example', timeout=5))

        slow_session = MagicMock()
        slow_session.get.return_value = self._response()
        with (
            patch.object(client, '_create_session', return_value=slow_session),
            patch('deploy.git_over_cdn.client.time.perf_counter', side_effect=[0.0, 5.01]),
        ):
            self.assertIsNone(client.probe_url('https://one.example', timeout=5))

    def test_probe_urls_starts_all_candidates_concurrently_and_sorts_latency(self):
        urls = ['https://slow.example', 'https://fast.example', 'https://middle.example']
        client = self._client(urls)
        started = []
        started_all = threading.Event()
        release = threading.Event()
        lock = threading.Lock()
        result = []
        timeouts = []
        latency = {
            'https://slow.example': 0.4,
            'https://fast.example': 0.1,
            'https://middle.example': 0.2,
        }

        def probe(url, timeout):
            with lock:
                started.append(url)
                timeouts.append(timeout)
                if len(started) == len(urls):
                    started_all.set()
            release.wait(timeout=1)
            return latency[url]

        client.probe_url = probe
        worker = threading.Thread(target=lambda: result.extend(client._probe_urls(urls, timeout=5)))
        worker.start()
        try:
            self.assertTrue(started_all.wait(timeout=0.5))
        finally:
            release.set()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(
            ['https://fast.example', 'https://middle.example', 'https://slow.example'], result
        )
        self.assertEqual([5, 5, 5], timeouts)

    def test_preferred_urls_uses_fallback_only_when_all_primary_nodes_fail(self):
        fallback_urls = ['https://fallback.example']
        client = self._client(fallback_urls=fallback_urls)
        client._probe_urls = MagicMock(return_value=[])

        self.assertEqual(fallback_urls, client.preferred_urls)
        client._probe_urls.assert_called_once_with(client.urls, timeout=5)

    def test_preferred_urls_keeps_only_healthy_primary_nodes(self):
        client = self._client(fallback_urls=['https://fallback.example'])
        client._probe_urls = MagicMock(return_value=['https://two.example'])

        self.assertEqual(['https://two.example'], client.preferred_urls)

    def test_both_deploy_entrypoints_share_update_endpoint_configuration(self):
        for manager_class in (DeployGitManager, WindowsGitManager):
            manager = object.__new__(manager_class)
            manager.root_filepath = '.'
            manager.git = 'git'

            client = manager.goc_client

            self.assertEqual(list(CLOUDFLARE_UPDATE_URLS), client.urls)
            self.assertEqual(list(FALLBACK_UPDATE_URLS), client.fallback_urls)

    def test_macos_update_manager_uses_detected_command_line_tools_git(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = object.__new__(DeployGitManager)
            manager.root_filepath = directory
            bundled_git = Path(directory) / '.venv' / 'bin' / 'git'
            bundled_git.parent.mkdir(parents=True)
            bundled_git.write_text('', encoding='utf-8')

            with (
                patch("deploy.git.sys.platform", "darwin"),
                patch.object(manager, "_find_macos_system_git", return_value="/Applications/Xcode.app/git"),
                patch.object(manager, "_set_macos_git_executable") as set_executable,
            ):
                self.assertEqual(
                    "/Applications/Xcode.app/git",
                    manager.git,
                )

            self.assertFalse(bundled_git.exists())
        set_executable.assert_called_once_with("/Applications/Xcode.app/git")

    def test_macos_update_manager_keeps_bundled_git_without_tools(self):
        manager = object.__new__(DeployGitManager)

        with (
            patch("deploy.git.sys.platform", "darwin"),
            patch.object(manager, "_find_macos_system_git", return_value=None),
            patch.object(manager, "_legacy_macos_git", return_value="/release/.venv/bin/git"),
        ):
            self.assertEqual("/release/.venv/bin/git", manager.git)


if __name__ == '__main__':
    unittest.main()

import unittest
from unittest.mock import patch

from deploy import config as deploy_config
from deploy import geo
from deploy.Windows import config as windows_config


class TestIp9Location(unittest.TestCase):
    @patch('deploy.geo.requests.get')
    def test_returns_lowercase_country_code(self, get):
        response = get.return_value
        response.json.return_value = {'data': {'country_code': 'CN'}}

        self.assertEqual(geo.get_country_code(), 'cn')

        get.assert_called_once_with(
            geo.IP9_LOCATION_URL,
            timeout=5,
            headers={'User-Agent': 'AzurPilot'},
        )
        response.raise_for_status.assert_called_once_with()

    @patch('deploy.geo.requests.get')
    def test_invalid_response_returns_none(self, get):
        response = get.return_value
        response.json.return_value = {'data': {}}

        self.assertIsNone(geo.get_country_code())


class TestDeployLocation(unittest.TestCase):
    def make_config(self, config_module, repository=None):
        instance = object.__new__(config_module.DeployConfig)
        instance.config = {
            'Repository': repository or config_module.GITHUB_REPOSITORY,
        }
        instance.Repository = instance.config['Repository']
        instance.Branch = 'master'
        instance._github_location_checked = False
        return instance

    def test_china_uses_cdn_and_gitcode_fallback(self):
        for config_module in (deploy_config, windows_config):
            with self.subTest(config_module=config_module.__name__), patch.object(
                config_module, 'get_country_code', return_value='cn'
            ) as get_country_code:
                config = self.make_config(config_module)

                config.config_redirect()

                self.assertEqual(config.config['Repository'], config_module.GIT_OVER_CDN_REPOSITORY)
                self.assertTrue(config.GitOverCdn)
                self.assertEqual(config.Repository, config_module.GIT_OVER_CDN_FALLBACK_REPOSITORY)
                get_country_code.assert_called_once_with()

    def test_non_china_keeps_github_and_only_checks_once(self):
        for config_module in (deploy_config, windows_config):
            with self.subTest(config_module=config_module.__name__), patch.object(
                config_module, 'get_country_code', return_value='us'
            ) as get_country_code:
                config = self.make_config(config_module)

                config.config_redirect()
                config.config_redirect()

                self.assertEqual(config.config['Repository'], config_module.GITHUB_REPOSITORY)
                self.assertFalse(config.GitOverCdn)
                self.assertEqual(config.Repository, config_module.GITHUB_REPOSITORY)
                get_country_code.assert_called_once_with()

    def test_failed_lookup_keeps_github(self):
        for config_module in (deploy_config, windows_config):
            with self.subTest(config_module=config_module.__name__), patch.object(
                config_module, 'get_country_code', return_value=None
            ):
                config = self.make_config(config_module)

                config.config_redirect()

                self.assertEqual(config.config['Repository'], config_module.GITHUB_REPOSITORY)
                self.assertFalse(config.GitOverCdn)

    def test_custom_repository_does_not_query_location(self):
        for config_module in (deploy_config, windows_config):
            with self.subTest(config_module=config_module.__name__), patch.object(
                config_module, 'get_country_code'
            ) as get_country_code:
                config = self.make_config(config_module, 'https://github.com/example/custom')

                config.config_redirect()

                get_country_code.assert_not_called()

    def test_macos_keeps_legacy_git_path_until_command_line_tools_are_detected(self):
        config = self.make_config(deploy_config)
        config.GitExecutable = './.venv/bin/git'
        config.config['GitExecutable'] = config.GitExecutable

        with (
            patch.object(deploy_config.sys, 'platform', 'darwin'),
            patch.object(deploy_config, 'get_country_code', return_value='us'),
        ):
            config.config_redirect()

        self.assertEqual('./.venv/bin/git', config.GitExecutable)
        self.assertEqual('./.venv/bin/git', config.config['GitExecutable'])


if __name__ == '__main__':
    unittest.main()

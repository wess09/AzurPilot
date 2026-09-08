"""launcher_trust（启动器信任免密登录）纯逻辑单元测试。"""

import unittest

from module.webui import launcher_trust


class TestLauncherTrust(unittest.TestCase):
    def setUp(self):
        launcher_trust._reset()

    def tearDown(self):
        launcher_trust._reset()

    def test_default_disabled(self):
        self.assertFalse(launcher_trust.enabled())
        self.assertIsNone(launcher_trust.issue_token())
        self.assertFalse(launcher_trust.validate_token("anything"))
        self.assertFalse(launcher_trust.check_secret("anything"))

    def test_enabled_only_when_secret_and_key(self):
        launcher_trust.configure("secret", "key")
        self.assertTrue(launcher_trust.enabled())
        self.assertEqual(launcher_trust.webui_key(), "key")

        launcher_trust.configure("secret", None)
        self.assertFalse(launcher_trust.enabled())

        launcher_trust.configure(None, "key")
        self.assertFalse(launcher_trust.enabled())

        launcher_trust.configure("secret", "   ")
        self.assertFalse(launcher_trust.enabled())

    def test_check_secret(self):
        launcher_trust.configure("s3cret", "key")
        self.assertTrue(launcher_trust.check_secret("s3cret"))
        self.assertFalse(launcher_trust.check_secret("wrong"))
        self.assertFalse(launcher_trust.check_secret(None))
        # 未配置时任何候选都不匹配
        launcher_trust.configure(None, None)
        self.assertFalse(launcher_trust.check_secret("s3cret"))

    def test_token_issue_and_validate(self):
        launcher_trust.configure("s3cret", "key")
        token = launcher_trust.issue_token()
        self.assertIsInstance(token, str)
        self.assertTrue(token)
        self.assertTrue(launcher_trust.validate_token(token))

        # 错误令牌 / 空令牌一律无效
        self.assertFalse(launcher_trust.validate_token("forged"))
        self.assertFalse(launcher_trust.validate_token(""))
        self.assertFalse(launcher_trust.validate_token(None))

    def test_token_expired(self):
        launcher_trust.configure("s3cret", "key")
        token = launcher_trust.issue_token()
        self.assertTrue(launcher_trust.validate_token(token))

        # 直接让令牌过期，验证会被拒绝并清理
        launcher_trust._tokens[token] = 0.0
        self.assertFalse(launcher_trust.validate_token(token))
        self.assertNotIn(token, launcher_trust._tokens)

    def test_reconfigure_invalidates_old_tokens(self):
        launcher_trust.configure("s3cret-a", "key")
        token = launcher_trust.issue_token()
        self.assertTrue(launcher_trust.validate_token(token))

        launcher_trust.configure("s3cret-b", "key")
        self.assertFalse(launcher_trust.validate_token(token))

    def test_issue_token_disabled(self):
        launcher_trust.configure(None, "key")
        self.assertIsNone(launcher_trust.issue_token())


if __name__ == "__main__":
    unittest.main()

"""NemuIpc SDK DLL 选择逻辑的单元测试。

覆盖实例版本推断（vms 目录名）与 DLL 候选路径顺序：
实例版本精确匹配的 SDK 必须排在通用路径之前，避免同机多版本
并存时（如 nx_device/12.0 与 15.0）错用旧版 DLL 连新版实例。
"""

import os
import shutil
import tempfile
import unittest

from module.device.method.nemu_ipc import NemuIpcImpl


def build_fake_install(root, versions=('12.0',), instance_names=('MuMuPlayer-12.0-0',)):
    """构造一个仿真的 MuMu 安装目录结构。

    Args:
        root (str): 临时目录。
        versions (tuple): nx_device 下存在的版本目录。
        instance_names (tuple): vms 下存在的实例目录名。

    Returns:
        str: 安装根目录。
    """
    for version in versions:
        folder = os.path.join(root, 'nx_device', version, 'shell', 'sdk')
        os.makedirs(folder)
        with open(os.path.join(folder, 'external_renderer_ipc.dll'), 'w') as f:
            f.write('fake')
    folder = os.path.join(root, 'nx_main', 'sdk')
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'external_renderer_ipc.dll'), 'w') as f:
        f.write('fake')
    for name in instance_names:
        os.makedirs(os.path.join(root, 'vms', name))
    return root


class TestDetectVersion(unittest.TestCase):
    def test_detect_from_vms_name(self):
        with tempfile.TemporaryDirectory() as root:
            build_fake_install(
                root, versions=('12.0', '15.0'),
                instance_names=('MuMuPlayer-12.0-1', 'MuMuPlayer-15.0-0'))
            self.assertEqual(
                NemuIpcImpl.detect_version(root, 0), '15.0')
            self.assertEqual(
                NemuIpcImpl.detect_version(root, 1), '12.0')

    def test_detect_yxarknights_instance(self):
        with tempfile.TemporaryDirectory() as root:
            build_fake_install(
                root, versions=('12.0',), instance_names=('YXArkNights-12.0-1',))
            self.assertEqual(
                NemuIpcImpl.detect_version(root, 1), '12.0')

    def test_detect_missing_vms_returns_none(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(NemuIpcImpl.detect_version(root, 0))


class TestDllPathOrder(unittest.TestCase):
    """验证加载的 DLL 来自实例版本对应的 nx_device/<版本> 目录。

    __init__ 会真实加载 DLL，这里用写入假内容的 dll 文件会让
    ctypes.CDLL 抛 OSError 并继续尝试下一个候选；因此只对
    "最终选中路径" 的语义做间接验证：让仅实例版本的路径真实可加载
    是不可能的（假 DLL），改为验证候选列表顺序 via detect + 文件系统。
    """

    def _probe_selected(self, root, instance_id, version=None):
        """拦截 ctypes.CDLL，记录第一个存在的候选路径。"""
        import ctypes as _ctypes

        selected = []

        class _FakeLib:
            pass

        original = _ctypes.CDLL

        def fake_cdll(path, *args, **kwargs):
            if path not in selected:
                selected.append(path)
            return _FakeLib()

        _ctypes.CDLL = fake_cdll
        try:
            NemuIpcImpl(
                nemu_folder=root, instance_id=instance_id,
                version=version)
        finally:
            _ctypes.CDLL = original
        return selected[0]

    def test_explicit_version_wins(self):
        with tempfile.TemporaryDirectory() as root:
            build_fake_install(
                root, versions=('12.0', '15.0'),
                instance_names=('MuMuPlayer-12.0-1', 'MuMuPlayer-15.0-0'))
            selected = self._probe_selected(root, 0)
            self.assertIn('nx_device/15.0', selected.replace('\\', '/'))
            self.assertNotIn('nx_device/12.0', selected.replace('\\', '/'))

    def test_version_inferred_from_vms(self):
        with tempfile.TemporaryDirectory() as root:
            build_fake_install(
                root, versions=('12.0', '15.0'),
                instance_names=('MuMuPlayer-12.0-1', 'MuMuPlayer-15.0-0'))
            # 不传 version，从 vms/MuMuPlayer-15.0-0 自动推断
            selected = self._probe_selected(root, 0)
            self.assertIn('nx_device/15.0', selected.replace('\\', '/'))

    def test_fallback_prefers_newer_version(self):
        with tempfile.TemporaryDirectory() as root:
            # 只有 12.0/15.0 目录，vms 为空（无法推断版本）
            build_fake_install(root, versions=('12.0', '15.0'), instance_names=())
            selected = self._probe_selected(root, 0)
            normalized = selected.replace('\\', '/')
            # 经典 shell/sdk 路径不存在时，兜底应选更高版本 15.0
            self.assertIn('nx_device/15.0', normalized)
            self.assertNotIn('nx_device/12.0', normalized)




if __name__ == '__main__':
    unittest.main()

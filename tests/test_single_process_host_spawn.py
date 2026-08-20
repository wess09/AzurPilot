"""专用单进程宿主的真实进程启动/关闭回归测试。"""

import unittest

from module.webui.single_process_runtime import SingleProcessRuntime


class TestSingleProcessHostSpawn(unittest.TestCase):
    def test_spawned_host_is_ready_and_does_not_remain_after_shutdown(self):
        runtime = SingleProcessRuntime()
        try:
            self.assertTrue(runtime.ensure_host())
            self.assertIsNotNone(runtime.host_pid())
        finally:
            self.assertTrue(runtime.shutdown(timeout=3, force=True))
            self.assertIsNone(runtime.host_pid())


if __name__ == '__main__':
    unittest.main()

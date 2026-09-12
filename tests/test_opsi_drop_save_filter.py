"""opsi_save_method 单元测试：仅耄耋相接任务允许本地保存掉落截图。"""
import unittest

from module.statistics.azurstats import AzurStats


class TestOpsiSaveMethod(unittest.TestCase):
    def test_meow_keeps_save(self):
        """耄耋相接任务保留保存行为。"""
        self.assertEqual(
            AzurStats.opsi_save_method("OpsiMeowfficerFarming", "save_and_upload"),
            "save_and_upload",
        )
        self.assertEqual(
            AzurStats.opsi_save_method("OpsiMeowfficerFarming", "save"), "save"
        )

    def test_cl1_save_stripped(self):
        """侵蚀1练级任务去掉保存、保留上传。"""
        self.assertEqual(
            AzurStats.opsi_save_method("OpsiHazard1Leveling", "save_and_upload"),
            "upload",
        )
        self.assertEqual(
            AzurStats.opsi_save_method("OpsiHazard1Leveling", "save"), "do_not"
        )
        self.assertEqual(
            AzurStats.opsi_save_method("OpsiHazard1Leveling", "upload"), "upload"
        )
        self.assertEqual(
            AzurStats.opsi_save_method("OpsiHazard1Leveling", "do_not"), "do_not"
        )

    def test_other_opsi_tasks(self):
        """其余大世界任务同样只去掉保存。"""
        for task in ("OpsiDaily", "OpsiObscure", "OpsiAbyssal", "OpsiExplore", "OpsiStronghold"):
            self.assertEqual(
                AzurStats.opsi_save_method(task, "save_and_upload"), "upload"
            )
            self.assertEqual(AzurStats.opsi_save_method(task, "save"), "do_not")

    def test_none_method_passes_through(self):
        """无配置时原样返回。"""
        self.assertIsNone(AzurStats.opsi_save_method("OpsiHazard1Leveling", None))


if __name__ == "__main__":
    unittest.main()

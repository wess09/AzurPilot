"""大世界敌人搜索处理器。

继承标准敌人搜索处理器，针对大世界地图场景进行适配。
提供大世界地图内状态检测（含雾天地图识别）以及地图按钮
滑入动画的等待逻辑，确保 UI 元素就绪后再进行后续操作。
"""
from module.handler.enemy_searching import EnemySearchingHandler as EnemySearchingHandler_
from module.logger import logger
from module.os.assets import MAP_GOTO_GLOBE_FOG
from module.os_handler.assets import AUTO_SEARCH_REWARD, IN_MAP, ORDER_ENTER


class EnemySearchingHandler(EnemySearchingHandler_):
    """大世界敌人搜索处理器，处理大世界地图状态检测与界面动效等待。"""

    def is_in_map(self):
        """
        判断当前是否在大世界海域地图内部。

        Returns:
            bool: 处于大世界地图中返回 True。
        """
        if IN_MAP.match_luma(self.device.image, offset=(200, 5)):
            return True
        if self.match_template_color(MAP_GOTO_GLOBE_FOG, offset=(200, 5), threshold=40):
            return True

        return False

    def wait_os_map_buttons(self):
        """
        等待大世界地图右侧操作按钮滑入到位。

        进入大世界海域时，雷达和右侧指令按钮会有从右侧滑出的动画，
        等待直到按钮移动到最终可用位置。
        """
        for _ in self.loop(timeout=1):
            if self.appear(ORDER_ENTER, offset=(20, 20)):
                break
            # 游戏偶尔出现上一次通关弹窗 AUTO_SEARCH_REWARD 延迟弹出的 Bug
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                continue
        else:
            logger.warning('[大世界处理-搜索] 大世界地图按钮等待超时，假设已等待完成')

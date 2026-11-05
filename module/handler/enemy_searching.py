"""敌人搜索动画处理器。

处理地图移动后出现的敌人搜索动画（侦察动画）。
当舰队在地图上移动时，游戏会播放敌人搜索动画，
此模块检测动画的出现和消失，确保自动化流程在动画结束后继续。

继承自 InfoHandler，与 AutoSearchHandler 配合使用。
"""

from module.base.decorator import del_cached_property
from module.base.timer import Timer
from module.exception import CampaignEnd
from module.handler.assets import *
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.map.assets import *
from module.ui.assets import CAMPAIGN_CHECK, EVENT_CHECK, SP_CHECK


class EnemySearchingHandler(InfoHandler):
    """敌人搜索动画处理器。

    检测地图中敌人搜索（侦察）动画的出现和消失，并处理动画期间可能出现的
    各种异常情况（关卡结束、紧急委托、剧情弹窗等）。

    该处理器在地图操作后被调用，等待敌人搜索动画完成后再继续下一步操作。

    Attributes:
        MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD (float):
            红色覆盖层透明度阈值，超过此值认为搜索动画出现。正常值为 (0.70, 0.80)。
        MAP_ENEMY_SEARCHING_TIMEOUT_SECOND (int):
            搜索动画等待超时时间（秒）。
        in_stage_timer (Timer): 关卡页面检测计时器，防止误判。
        stage_entrance: 关卡入口标识。
        map_is_100_percent_clear (bool): 地图是否已 100% 通关，在 fast_forward.py 中被覆盖。
    """
    MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD = 0.5  # 通常值为 (0.70, 0.80)
    MAP_ENEMY_SEARCHING_TIMEOUT_SECOND = 5
    in_stage_timer = Timer(0.5, count=2)
    stage_entrance = None

    map_is_100_percent_clear = False  # 将在 fast_forward.py 中被覆盖

    def enemy_searching_color_initial(self):
        """初始化敌人搜索动画的颜色参考值。

        子类可覆盖此方法，在检测搜索动画前从当前截图加载颜色数据。
        """
        pass

    def enemy_searching_appear(self):
        """检测敌人搜索动画是否出现。

        通过模板匹配和亮度分析判断屏幕上是否显示了敌人搜索动画。

        Returns:
            bool: 搜索动画是否出现。
        """
        if not self.is_in_map():
            return False

        if MAP_ENEMY_SEARCHING.match_luma(self.device.image, offset=(5, 5)):
            return True

        return False

    def handle_enemy_flashing(self):
        """等待敌人闪烁动画消失。

        在敌人搜索动画结束后，地图上的敌人图标会短暂闪烁。
        此方法通过固定延时等待闪烁结束。
        """
        self.device.sleep(1.2)

    def handle_in_stage(self):
        """检测并处理已返回关卡选择页面的情况。

        当战斗结束或地图探索完成后，游戏会返回关卡选择页面。
        此方法通过计时器避免短暂的画面切换导致误判。

        Returns:
            bool: 始终返回 False（正常情况）。

        Raises:
            CampaignEnd: 确认已回到关卡页面后抛出，终止当前战役流程。
        """
        if self.is_in_stage():
            if self.in_stage_timer.reached():
                self.ensure_no_info_bar(timeout=1.2)
                # 战后转场可能短暂闪过选关页，等待提示栏后再次确认。
                if self.is_in_stage():
                    logger.info('[处理器-搜索] 已回到关卡页面')
                    raise CampaignEnd('[处理器-搜索] 已回到关卡页面')
                self.in_stage_timer.reset()
            return False
        else:
            if self.appear(MAP_PREPARATION, offset=(20, 20)) \
                    or self.appear(MAP_PREPARATION_HARD, offset=(20, 20)) \
                    or self.appear(FLEET_PREPARATION, offset=(20, 50)):
                self.device.click(MAP_PREPARATION_CANCEL)
            self.in_stage_timer.reset()
            return False

    def is_in_stage_page(self):
        """检测当前是否在关卡选择页面（战役/活动/SP）。

        Returns:
            bool: 是否在关卡选择页面。
        """
        for check in [CAMPAIGN_CHECK, EVENT_CHECK, SP_CHECK]:
            if self.appear(check, offset=(20, 20)):
                return True
        return False

    def is_stage_page_has_entrance(self):
        """检查关卡页面是否有关卡入口，即页面是否已完全加载。

        通过 OCR 提取关卡名称图像来判断页面加载状态。

        Returns:
            bool: 关卡入口是否可见（页面已完全加载）。
        """
        # campaign_extract_name_image 位于 CampaignOcr 中
        try:
            if hasattr(self, 'campaign_extract_name_image'):
                del_cached_property(self, '_stage_image')
                del_cached_property(self, '_stage_image_gray')
                if not len(self.campaign_extract_name_image(self.device.image)):
                    return False
        except IndexError:
            return False

        return True

    def is_in_stage(self):
        """检测当前是否已完全回到关卡选择页面。

        组合页面类型检测和关卡入口可见性检测。

        Returns:
            bool: 是否已完全回到关卡页面。
        """
        if not self.is_in_stage_page():
            return False
        if not self.is_stage_page_has_entrance():
            return False
        return True

    def is_in_map(self):
        """检测当前是否在地图界面。

        Returns:
            bool: 是否在地图中。
        """
        return self.appear(IN_MAP)

    def is_event_animation(self):
        """检查是否有活动中的动画（击败敌人后的动画）。

        Returns:
            bool: 是否正在播放动画。
        """
        return False

    def handle_auto_search_exit(self, drop=None) -> bool:
        """处理自动搜索退出操作。

        占位方法，将在 AutoSearchHandler 中被覆盖。AutoSearchHandler 继承自
        EnemySearchingHandler，但 handle_in_map_with_enemy_searching() 需要
        调用 handle_auto_search_exit() 处理意外情况。

        Args:
            drop (DropImage | None): 掉落记录对象。默认为 None。

        Returns:
            bool: 是否执行了退出操作。
        """
        return False

    def handle_in_map_with_enemy_searching(self, drop=None):
        """处理地图中敌人搜索动画出现的情况。

        Args:
            drop (DropImage | None): 掉落记录对象。默认为 None。

        Returns:
            bool: 是否进行了处理。
        """
        if not self.is_in_map():
            return False

        timeout = Timer(self.MAP_ENEMY_SEARCHING_TIMEOUT_SECOND)
        appeared = False
        while 1:
            self.device.screenshot()
            if self.is_event_animation():
                continue
            if self.is_in_map():
                timeout.start()
            else:
                timeout.reset()

            # 关卡可能已经结束，尽管此处预期出现敌人搜索动画
            if self.handle_in_stage():
                return True
            # 16章中可能立即进入潜艇战
            if hasattr(self, 'is_combat_loading') and self.is_combat_loading():
                logger.warning('[处理器-搜索] 进入地图时出现战斗加载画面')
                break
            if self.handle_auto_search_exit(drop=drop):
                timeout.limit = 10
                timeout.reset()
                continue

            # 弹窗处理
            if self.handle_vote_popup():
                timeout.limit = 10
                timeout.reset()
                continue
            if self.handle_story_skip():
                self.ensure_no_story()
                timeout.limit = 10
                timeout.reset()
            if self.handle_guild_popup_cancel():
                timeout.limit = 10
                timeout.reset()
                continue
            if self.handle_urgent_commission(drop=drop):
                timeout.limit = 10
                timeout.reset()
                continue

            # 结束条件
            if self.enemy_searching_appear():
                appeared = True
            else:
                if appeared:
                    self.handle_enemy_flashing()
                    self.device.sleep(0.3)
                    self.device.screenshot()
                    logger.info('[处理器-搜索] 敌人搜索动画已出现')
                    break
                self.enemy_searching_color_initial()
            if timeout.reached():
                logger.info('[处理器-搜索] 敌人搜索动画超时')
                break

        return True

    def handle_in_map_no_enemy_searching(self, drop=None):
        """处理地图中未出现敌人搜索动画的情况。

        Args:
            drop (DropImage | None): 掉落记录对象。默认为 None。

        Returns:
            bool: 是否进行了处理。
        """
        if not self.is_in_map():
            return False

        timeout = Timer(1, count=2).start()
        while 1:
            self.device.screenshot()

            if not self.is_in_map():
                timeout.reset()

            # 关卡可能已经结束，尽管此处预期出现敌人搜索动画
            if self.handle_in_stage():
                return True
            if self.handle_auto_search_exit(drop=drop):
                timeout.reset()
                continue

            # 弹窗处理
            if self.handle_vote_popup():
                timeout.reset()
                continue
            if self.handle_story_skip():
                self.ensure_no_story()
                timeout.reset()
            if self.handle_guild_popup_cancel():
                timeout.reset()
                continue
            if self.handle_urgent_commission(drop=drop):
                timeout.reset()
                continue

            # 结束条件
            if timeout.reached():
                logger.info('[处理器-搜索] 地图中未出现敌人搜索动画')
                break

        return True

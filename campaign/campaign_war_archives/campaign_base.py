from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.exception import RequestHumanTakeover
from module.handler.fast_forward import to_map_input_name
from module.logger import logger
from module.ui.assets import WAR_ARCHIVES_CHECK
from module.ui.page import page_archives
from module.ui.scroll import Scroll
from module.ui.switch import Switch
from module.war_archives.assets import (WAR_ARCHIVES_CAMPAIGN_CHECK,
                                        WAR_ARCHIVES_EX_ON,
                                        WAR_ARCHIVES_SCROLL,
                                        WAR_ARCHIVES_SP_ON)
from module.war_archives.dictionary import dic_archives_template

WAR_ARCHIVES_SWITCH = Switch('War_Archives_switch', is_selector=True)
WAR_ARCHIVES_SWITCH.add_state('ex', WAR_ARCHIVES_EX_ON)
WAR_ARCHIVES_SWITCH.add_state('sp', WAR_ARCHIVES_SP_ON)
WAR_ARCHIVES_SCROLL = Scroll(WAR_ARCHIVES_SCROLL, color=(247, 211, 66), name='WAR_ARCHIVES_SCROLL')


class CampaignBase(CampaignBase_):
    # Helper variable to keep track of whether is the first runthrough
    first_run = True
    ENEMY_FILTER = '1T > 1L > 1E > 1M > 2T > 2L > 2E > 2M > 3T > 3L > 3E > 3M'

    def map_get_info(self, star=False):
        """获取地图信息，并在自动开荒模式下按星星状态选择战斗策略。

        自动开荒（WarArchives.AutoClear）开启时，读取关卡准备界面
        三颗星的暗亮状态，为本场战斗选择策略，详见 _auto_clear_strategy()。

        Pages:
            in: MAP_PREPARATION（关卡准备界面）

        Args:
            star: 是否强制认为所有星星已达成。
        """
        super().map_get_info(star)
        if self.config.WarArchives_AutoClear:
            self._auto_clear_strategy()

    def _auto_clear_strategy(self):
        """根据三颗星的暗亮状态选择本场战斗策略。

        星星达成条件：第一颗星为击破敌方旗舰，第二颗星为累计击破
        足量护卫舰队，第三颗星为单场击破所有敌舰。

        - 满 3 星：不干预，由 triggered_map_stop() 收尾，关卡推进
          交给 war_archives.run() 的关卡序列管理
        - 缺第 3 星（含未首通）：开荒全清，手动走图清空所有敌舰，
          一把同时推进达成度与三颗星
        - 仅缺第 2 星（第 3 星已亮，地图必然已 100% 清空、解锁通关
          模式）：自律刷，用自动搜索快速重复通关累计护卫舰队击杀数

        两种开荒目标共用上述策略：全图三星模式所有关打满星；
        100% 通关模式中间关由停止条件 100_percent_clear 在达成度
        100% 时收尾推进（全清一次即达标），最后一关由 map_3_stars
        打满星——首通全清达成度 100% 后通常仅缺第 2 星，此时切
        自律刷，不能因开荒目标为 100% 通关而恒定全清。

        策略通过临时覆盖配置实现。本方法在 handle_fast_forward()
        之前执行，覆盖不写入用户配置文件；同键重复覆盖会更新值，
        因此关卡间策略切换不受 override 不可逆性影响。

        Pages:
            in: MAP_PREPARATION（关卡准备界面）
        """
        if self.map_is_3_stars:
            logger.attr('[作战档案] 开荒策略', '满星，按停止条件收尾')
            return

        if not self.map_achieved_star_3:
            logger.attr('[作战档案] 开荒策略', '开荒全清')
            self.config.override(
                MAP_CLEAR_ALL_THIS_TIME=True,
                Campaign_UseAutoSearch=False,
            )
        else:
            logger.attr('[作战档案] 开荒策略', '缺第二颗星，自律刷护卫舰队')
            self.config.override(
                MAP_CLEAR_ALL_THIS_TIME=False,
                Campaign_UseAutoSearch=True,
            )

    def handle_map_stop(self):
        """满星后的关卡推进处理。

        自动开荒模式下关卡推进由 war_archives.run() 的关卡序列管理，
        此处仅避免原逻辑在递进失败时禁用任务；非开荒模式保持原有
        行为（递进下一关，递进失败禁用任务）。
        """
        if not self.config.WarArchives_AutoClear:
            super().handle_map_stop()
            return

        logger.info(f'[作战档案] 关卡 {to_map_input_name(self.config.Campaign_Name)} 开荒完成')

    def _get_archives_entrance(self, name):
        """
        Create entrance button to target archive campaign
        using a template acquired by event folder name

        Args:
            name(str): event folder name
        """
        template = dic_archives_template[name]

        sim, button = template.match_result(self.device.image)
        if sim < 0.85:
            return None

        entrance = button.crop((-12, -12, 44, 32), image=self.device.image, name=name)
        return entrance

    def _archives_loading_complete(self):
        """
        Check if war archive has finished loading
        """
        for war_archive_folder in dic_archives_template:
            template = dic_archives_template[war_archive_folder]
            loading_result = template.match(self.device.image)
            if loading_result:
                return True

        return False

    def _search_archives_entrance(self, name, skip_first_screenshot=True):
        """
        Search for entrance using mini-touch scroll down
        at center
        Fixed number of scrolls until give up, may need to
        increase as more war archives campaigns are added
        """
        loading_checked = False
        swipe_count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            while self.device.click_record and self.device.click_record[-1] == 'WAR_ARCHIVES_SCROLL':
                self.device.click_record.pop()

            # Drag may result in accidental exit, recover
            # before starting next search attempt
            while not self.appear(WAR_ARCHIVES_CHECK):
                self.ui_ensure(destination=page_archives)
                loading_checked = False

            # check entrance first, because game can remember last scrolling position
            # if you stays at page_campaign_menu
            # and bypass _archives_loading_complete if reached entrance
            entrance = self._get_archives_entrance(name)
            if entrance is not None:
                return entrance

            if not loading_checked:
                # _archives_loading_complete might take 1~2s if archive list is not at top
                while not self._archives_loading_complete():
                    self.device.screenshot()
                loading_checked = True

                entrance = self._get_archives_entrance(name)
                if entrance is not None:
                    return entrance

            # too many swipes
            if swipe_count >= 20:
                break

            if WAR_ARCHIVES_SCROLL.appear(main=self):
                if WAR_ARCHIVES_SCROLL.at_bottom(main=self):
                    WAR_ARCHIVES_SCROLL.set_top(main=self)
                else:
                    WAR_ARCHIVES_SCROLL.next_page(main=self, page=0.66)
                    swipe_count += 1
                continue
            else:
                break

        logger.warning(f'Failed to find archives entrance: {name}')
        return None

    def _scan_archives_events_visible(self):
        """匹配当前界面上可见的档案活动入口。

        Returns:
            list[str]: 活动文件夹名称，按界面从上到下排序。
        """
        visible = []
        for folder, template in dic_archives_template.items():
            for button in template.match_multi(self.device.image, similarity=0.85, name=folder):
                visible.append((button.area[1], folder))
        return [folder for _, folder in sorted(visible)]

    def _iterate_archives_events(self):
        """从档案列表顶部到底部遍历所有可见活动。

        回到档案列表并滚动到顶部后逐屏匹配已知活动入口，按界面
        从上到下的顺序产出活动文件夹名称，每个活动只产出一次。

        Yields:
            str: 活动文件夹名称，如 'war_archives_20210325_cn'。
        """
        scanned = set()
        skip_first_screenshot = True
        for _ in range(20):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            while self.device.click_record and self.device.click_record[-1] == 'WAR_ARCHIVES_SCROLL':
                self.device.click_record.pop()

            # 拖动可能误退出列表，先回到档案列表
            while not self.appear(WAR_ARCHIVES_CHECK):
                self.ui_ensure(destination=page_archives)

            # 滚动到顶部，保证从第一个活动开始遍历
            if WAR_ARCHIVES_SCROLL.appear(main=self):
                WAR_ARCHIVES_SCROLL.set_top(main=self)

            # 等待列表加载完成（不在顶部时可能需要 1~2s）；
            # 整屏都是字典外的新活动时模板永远不匹配，限制等待次数
            for _ in range(10):
                if self._archives_loading_complete():
                    break
                self.device.screenshot()

            for folder in self._scan_archives_events_visible():
                if folder not in scanned:
                    scanned.add(folder)
                    yield folder

            if WAR_ARCHIVES_SCROLL.appear(main=self):
                if WAR_ARCHIVES_SCROLL.at_bottom(main=self):
                    return
                WAR_ARCHIVES_SCROLL.next_page(main=self, page=0.66)
            else:
                return

    def ui_goto_archives_campaign(self, mode='ex'):
        """
        Performs the operations needed to transition
        to target archive's campaign stage map
        """
        # On first run regardless of current location
        # even in target stage map, start from page_archives
        # For subsequent runs when neither reward or
        # stop_triggers occur, no need perform operations
        result = True
        # 自动搜索菜单的模糊背景会遮挡 WAR_ARCHIVES_CAMPAIGN_CHECK，使下方
        # appear 检查误判失败，导致 ui_ensure(page_archives) 绕经主页重新进档
        # 案。作战档案不支持续战，刷星每轮结束后游戏停在菜单中，先退出菜单，
        # 让当前战役界面（WAR_ARCHIVES_CAMPAIGN_CHECK 可见）可以直接复用
        self.ensure_auto_search_exit()
        if self.first_run or not self.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
            result = self.ui_ensure(destination=page_archives)

            WAR_ARCHIVES_SWITCH.set(mode, main=self)

            entrance = self._search_archives_entrance(self.config.Campaign_Event)
            if entrance is not None:
                self.ui_click(entrance, appear_button=WAR_ARCHIVES_CHECK, check_button=WAR_ARCHIVES_CAMPAIGN_CHECK,
                              skip_first_screenshot=True)
            else:
                logger.critical('[战役] 当前服务器可能不支持该活动，请稍后再试')
                raise RequestHumanTakeover

        # Subsequent runs all set False
        if self.first_run:
            self.first_run = False

        return result

    def ui_goto_event(self):
        """
        Overridden to handle specifically transitions
        to target ex event in page_archives
        """
        return self.ui_goto_archives_campaign(mode='ex')

    def ui_goto_sp(self):
        """
        Overridden to handle specifically transitions
        to target sp event in page_archives
        """
        return self.ui_goto_archives_campaign(mode='sp')

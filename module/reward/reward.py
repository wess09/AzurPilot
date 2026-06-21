from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.combat.assets import *
from module.logger import logger
from module.reward.assets import *
from module.ui.navbar import Navbar
from module.ui.page import page_main, page_mission, page_reward
from module.ui.ui import UI
from module.ui_white.assets import MISSION_NOTICE_WHITE


class Reward(UI):
    def reward_receive(self, oil, coin, exp):
        """
        领取资源奖励（石油、金币、经验）。

        Args:
            oil (bool): 是否领取石油。
            coin (bool): 是否领取金币。
            exp (bool): 是否领取经验。

        Returns:
            bool: 是否领取了奖励。

        Pages:
            in: page_reward
            out: page_reward, 领取成功时带有 info_bar
        """
        if not oil and not coin and not exp:
            return False

        logger.hr('Reward receive')
        logger.info(f'oil={oil}, coin={coin}, exp={exp}')
        confirm_timer = Timer(1, count=3).start()
        # 设置点击间隔为 0.3 秒，因为游戏无法响应过快的点击。
        click_timer = Timer(0.3)
        for _ in self.loop():
            if oil and click_timer.reached() and self.appear_then_click(OIL, offset=(20, 50), interval=60):
                confirm_timer.reset()
                click_timer.reset()
                continue
            if coin and click_timer.reached() and self.appear_then_click(COIN, offset=(25, 50), interval=60):
                confirm_timer.reset()
                click_timer.reset()
                continue
            if exp and click_timer.reached() and self.appear_then_click(EXP, offset=(30, 50), interval=60):
                confirm_timer.reset()
                click_timer.reset()
                continue

            # End
            if confirm_timer.reached():
                break

        logger.info('Reward receive end')
        return True

    def _reward_get_state(self):
        if self.appear(MISSION_MULTI, offset=(20, 20)):
            return MISSION_MULTI
        if self.match_template_color(MISSION_SINGLE, offset=(50, 200)):
            return MISSION_SINGLE
        if self.appear(MISSION_EMPTY, offset=(20, 20)):
            return MISSION_EMPTY
        if self.appear(MISSION_UNFINISH, offset=(50, 200)):
            return MISSION_UNFINISH
        return None

    def _reward_mission_claim_click(self):
        """
        点击领取任务奖励。

        Returns:
            bool: 是否已点击领取。

        Pages:
            in: page_mission, MISSION_MULTI 或 MISSION_SINGLE
            out: 未知弹窗
        """
        clicked = False
        click_interval = Timer(1, count=2)
        for _ in self.loop():
            if clicked and not self.ui_page_appear(page_mission):
                return clicked
            if click_interval.reached():
                if self.appear_then_click(MISSION_MULTI, offset=(20, 20)):
                    click_interval.reset()
                    clicked = True
                    continue
                if self.match_template_color(MISSION_SINGLE, offset=(50, 200)):
                    self.device.click(MISSION_SINGLE)
                    click_interval.reset()
                    clicked = True
                    continue
                if self.appear(MISSION_UNFINISH, offset=(50, 200)):
                    return clicked

    def _reward_mission_claim_receive(self):
        """
        处理领取任务奖励后的弹窗。

        Returns:
            Button | str: Button 对象或状态字符串。

        Pages:
            in: 未知弹窗
            out: page_mission
        """
        logger.info('Mission claim receive')
        timeout = Timer(2, count=6).start()
        for _ in self.loop():
            if self.ui_page_appear(page_mission):
                state = self._reward_get_state()
                if state:
                    return state
                if timeout.reached():
                    logger.warning('Wait mission receive timeout')
                    return 'timeout'
            else:
                timeout.reset()

            # click
            if self.appear_then_click(GET_ITEMS_1, offset=(30, 30), interval=1):
                continue
            if self.appear_then_click(GET_ITEMS_2, offset=(30, 30), interval=1):
                continue
            if self.appear_then_click(GET_SHIP, interval=1):
                continue
            if self.handle_mission_popup_ack():
                continue
            if self.handle_vote_popup():
                continue
            if self.handle_story_skip():
                continue
            if self.handle_popup_confirm('MISSION_REWARD'):
                continue

    def _reward_wait_mission_list(self):
        """
        等待任务列表完全加载。

        Pages:
            in: page_mission
            out: page_mission, 任意任务状态或超时
        """
        timeout = Timer(1, count=2).start()
        for _ in self.loop():
            state = self._reward_get_state()
            if state:
                return state
            if timeout.reached():
                return 'timeout'

    def _reward_mission_collect(self):
        """
        统一处理"全部"和"每周"页面的任务奖励领取。

        Returns:
            Button | str: 最终状态，Button 对象或状态字符串。
        """
        state = self._reward_wait_mission_list()
        while 1:
            logger.attr('MissionState', state)
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            if state == 'timeout':
                logger.warning('Reward wait mission list timeout')
                return state
            if state in [MISSION_EMPTY, MISSION_UNFINISH]:
                logger.info('Mission collect finished')
                break
            elif state in [MISSION_MULTI, MISSION_SINGLE]:
                # 清除以下资源的已有间隔计时器
                self.interval_clear([GET_ITEMS_1, GET_ITEMS_2, MISSION_MULTI, MISSION_SINGLE, GET_SHIP])
                self._reward_mission_claim_click()
                state = self._reward_mission_claim_receive()
                continue
            else:
                logger.warning('Empty mission state, mission collect finished')

        return state

    def _reward_mission_all(self):
        """
        领取"全部"页面的任务奖励。

        Returns:
            bool: 是否已处理。
        """
        self.reward_side_navbar_ensure(upper=1)
        return self._reward_mission_collect()

    def _reward_mission_weekly(self):
        """
        领取"每周"页面的任务奖励。

        Returns:
            bool: 是否已处理。
        """
        if not self.image_color_count(MISSION_WEEKLY_RED_DOT, color=(206, 81, 66), threshold=221, count=20):
            logger.info('No MISSION_WEEKLY_RED_DOT')
            return False

        self.reward_side_navbar_ensure(upper=5)
        return self._reward_mission_collect()

    def reward_mission_notice(self):
        """
        检测主页面是否存在任务完成提示。

        Returns:
            bool: 是否存在任务提示。

        Pages:
            in: page_main
        """
        if self.appear(MISSION_NOTICE):
            logger.info('Found mission notice MISSION_NOTICE')
            return True
        if self.image_color_count(MISSION_NOTICE_WHITE, color=(214, 117, 99), threshold=221, count=20):
            logger.info('Found mission notice MISSION_NOTICE_WHITE')
            return True

        return False

    def reward_mission(self, daily=True, weekly=True):
        """
        领取任务奖励。

        Args:
            daily (bool): 是否领取每日奖励。
            weekly (bool): 是否领取每周奖励。

        Returns:
            bool: 是否领取了奖励。

        Pages:
            in: page_main
            out: page_mission
        """
        if not daily and not weekly:
            return False
        logger.hr('Mission reward')
        if not self.reward_mission_notice():
            return False

        self.ui_goto(page_mission, skip_first_screenshot=True)

        if daily:
            self._reward_mission_all()
        if weekly:
            self._reward_mission_weekly()

    @cached_property
    def _reward_side_navbar(self):
        """
        侧边导航栏选项：
           all.    （全部）
           main.   （主线）
           side.   （支线）
           daily.  （每日）
           weekly. （每周）
           event.  （活动）
        """
        reward_side_navbar = ButtonGrid(
            origin=(21, 118), delta=(0, 94.5),
            button_shape=(60, 75), grid_shape=(1, 6),
            name='REWARD_SIDE_NAVBAR')

        return Navbar(grids=reward_side_navbar,
                      active_color=(247, 255, 173),
                      inactive_color=(140, 162, 181))

    def reward_side_navbar_ensure(self, upper=None, bottom=None):
        """
        确保侧边导航栏切换到指定页面。
        页面是否完全加载由调用方单独处理。

        Args:
            upper (int):
                1  全部。
                2  主线。
                3  支线。
                4  每日。
                5  每周。
                6  活动。
            bottom (int):
                6  全部。
                5  主线。
                4  支线。
                3  每日。
                2  每周。
                1  活动。

        Returns:
            bool: 侧边导航栏是否设置成功。
        """
        if self._reward_side_navbar.set(self, upper=upper, bottom=bottom):
            return True
        return False

    def run(self):
        """
        Pages:
            in: 任意页面
            out: page_main 或 page_mission，可能带有 info_bar
        """
        self.ui_ensure(page_reward)
        self.reward_receive(
            oil=self.config.Reward_CollectOil,
            coin=self.config.Reward_CollectCoin,
            exp=self.config.Reward_CollectExp)
        self.ui_goto(page_main)
        self.reward_mission(daily=self.config.Reward_CollectMission,
                            weekly=self.config.Reward_CollectWeeklyMission)
        self.config.task_delay(server_update=True)

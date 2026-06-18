from module.combat.assets import *
from module.combat.combat import Combat as Combat_
from module.logger import logger
from module.os_combat.assets import *
from module.os_handler.assets import *
from module.os_handler.map_event import MapEventHandler
from module.base.timer import Timer
from module.exception import GameBugError
from module.statistics.opsi_runtime import finish_battle_timer, start_battle_timer


class ContinuousCombat(Exception):
    """
    大世界连续战斗异常。

    在塞壬扫描装置等场景中，两个敌人无间隔出现，
    战斗结束后立即进入下一场战斗时抛出此异常，
    由 combat() 方法捕获并循环重试。
    """
    pass


class Combat(Combat_, MapEventHandler):
    """
    大世界战斗处理器。

    继承标准战斗和地图事件处理器，针对大世界场景定制战斗流程：
    连续战斗检测、S 评价延迟点击、大世界专用物品获取逻辑。

    Attributes:
        battle_status_s_autoclick_delay (int): S 评价页面自动点击延迟秒数。
    """
    battle_status_s_autoclick_delay = 20

    def combat_appear(self):
        """
        检测是否进入战斗。

        依次检查地图状态、战斗加载、战斗执行、战斗准备和塞壬准备界面，
        任一条件满足即判定为已进入战斗。

        Pages:
            in: 大世界地图或战斗过渡画面
            out: 战斗准备界面或战斗执行中

        Returns:
            bool: 是否进入战斗。
        """
        if self.is_in_map():
            return False

        if self.is_combat_loading():
            return True

        # 检查是否已在战斗执行中（暂停按钮可见）
        # 处理自动搜索跳过战斗准备界面的情况
        if self.is_combat_executing():
            return True

        if self.appear(BATTLE_PREPARATION):
            return True
        if self.appear(SIREN_PREPARATION, offset=(20, 20)):
            return True
        if self.appear(BATTLE_PREPARATION_WITH_OVERLAY) and self.handle_combat_automation_confirm():
            return True

        return False

    def _battle_status_s_timer(self):
        """
        获取或重建 S 评价延迟点击计时器。

        大世界自动战斗中，S 评价页面需要延迟一段时间再点击，
        避免与自动搜索的自动推进产生冲突。

        Returns:
            Timer: S 评价延迟计时器实例。
        """
        try:
            timer = self._os_battle_status_s_timer
        except AttributeError:
            timer = Timer(self.battle_status_s_autoclick_delay)
            self._os_battle_status_s_timer = timer
        if timer.limit != self.battle_status_s_autoclick_delay:
            timer = Timer(self.battle_status_s_autoclick_delay)
            self._os_battle_status_s_timer = timer
        return timer

    def _clear_battle_status_s_timer(self):
        """
        重置 S 评价延迟计时器，在每次新的战斗状态出现时调用。
        """
        self._battle_status_s_timer().clear()

    def _handle_auto_battle_status_s(self, drop=None, timer=None):
        """
        大世界自动模式下，等待后再点击 BATTLE_STATUS_S。

        自动搜索通常会自行推进 S 评价结果页面，此处仅作为客户端卡住时的延迟兜底处理。
        先启动计时器，到达延迟阈值后才执行点击，避免与自动搜索冲突。

        Args:
            drop (DropImage): 掉落图像对象，用于处理战斗掉落。
            timer (Timer): 可选的外部计时器，为 None 时使用内部计时器。

        Returns:
            tuple: (是否出现, 是否点击)。
        """
        timer = timer or self._battle_status_s_timer()
        if not self.appear(BATTLE_STATUS_S):
            timer.clear()
            return False, False

        timer.start()
        if not timer.reached():
            return True, False

        handled = self._handle_single_battle_status(BATTLE_STATUS_S, 'S', drop)
        timer.clear()
        return True, handled

    def combat_preparation(self, balance_hp=False, emotion_reduce=False, auto='combat_auto', fleet_index=1):
        """
        大世界战斗准备阶段。

        循环处理战斗准备界面，设置自动战斗模式、处理退役和弹窗确认，
        直到检测到战斗执行界面出现。

        Pages:
            in: 战斗准备界面（BATTLE_PREPARATION 或 SIREN_PREPARATION）
            out: 战斗执行中界面

        Args:
            balance_hp (bool): 是否平衡血量。
            emotion_reduce (bool): 是否减少情绪值。
            auto (str): 自动战斗模式。
            fleet_index (int): 舰队索引。
        """
        logger.info('Combat preparation.')
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        skip_first_screenshot = True

        for _ in self.loop():

            if self.appear(BATTLE_PREPARATION):
                if self.handle_combat_automation_set(auto=auto == 'combat_auto'):
                    continue
            if self.handle_retirement():
                continue
            if self.appear_then_click(BATTLE_PREPARATION, interval=2):
                continue
            if self.appear_then_click(SIREN_PREPARATION, offset=(20, 20), interval=2):
                continue
            if self.handle_popup_confirm('ENHANCED_ENEMY'):
                continue
            if self.handle_combat_automation_confirm():
                continue
            if self.handle_story_skip():
                continue

            # 结束
            pause = self.is_combat_executing()
            if pause:
                logger.attr('BattleUI', pause)
                break

    def _get_exp_info_sleep(self):
        """
        返回经验结算页面点击后的随机等待时间范围。

        有掉落物时等待更久（1.5-2秒），让掉落识别完成；
        无掉落时快速跳过（0.25-0.5秒）。

        Returns:
            tuple: (最小秒数, 最大秒数)。
        """
        return (1.5, 2) if self.__os_combat_drop else (0.25, 0.5)

    def handle_exp_info(self):
        """
        处理战斗结束后的经验结算页面（S/A/B/C/D 评价）。

        点击对应评价按钮后清除 S 评价计时器，并等待随机时间。
        战斗执行中时不处理。

        Pages:
            in: 战斗结束，经验结算界面
            out: 经验结算界面已关闭

        Returns:
            bool: 是否点击了经验结算按钮。
        """
        if self.is_combat_executing():
            return False
        sleep = self._get_exp_info_sleep()
        if self.appear_then_click(EXP_INFO_S):
            self._clear_battle_status_s_timer()
            self.device.sleep(sleep)
            return True
        if self.appear_then_click(EXP_INFO_A):
            self._clear_battle_status_s_timer()
            self.device.sleep(sleep)
            return True
        if self.appear_then_click(EXP_INFO_B):
            self._clear_battle_status_s_timer()
            self.device.sleep(sleep)
            return True
        if self.appear_then_click(EXP_INFO_C):
            self._clear_battle_status_s_timer()
            self.device.sleep(sleep)
            return True
        if self.appear_then_click(EXP_INFO_D):
            self._clear_battle_status_s_timer()
            self.device.sleep(sleep)
            return True

        return False

    def handle_get_items(self, drop=None):
        """
        点击安全区域关闭物品获取弹窗，而非直接点击按钮本身。

        Args:
            drop (DropImage): 掉落图像对象。

        Returns:
            bool: 是否处理了物品获取弹窗。
        """
        if getattr(self, '_disable_handle_get_items', False):
            return False
        if self.appear(GET_ITEMS_1, offset=5, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self, before=2)
            self.device.click(CLICK_SAFE_AREA)
            self._clear_battle_status_s_timer()
            self.interval_reset(BATTLE_STATUS_S)
            self.interval_reset(BATTLE_STATUS_A)
            self.interval_reset(BATTLE_STATUS_B)
            return True
        if self.appear(GET_ITEMS_2, offset=5, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self, before=2)
            self.device.click(CLICK_SAFE_AREA)
            self._clear_battle_status_s_timer()
            self.interval_reset(BATTLE_STATUS_S)
            self.interval_reset(BATTLE_STATUS_A)
            self.interval_reset(BATTLE_STATUS_B)
            return True
        if self.appear(GET_ADAPTABILITY, offset=5, interval=self.battle_status_click_interval):
            if drop:
                drop.handle_add(self, before=2)
            self.device.click(CLICK_SAFE_AREA)
            self._clear_battle_status_s_timer()
            self.interval_reset(BATTLE_STATUS_S)
            self.interval_reset(BATTLE_STATUS_A)
            self.interval_reset(BATTLE_STATUS_B)
            return True

        return False

    def _os_combat_expected_end(self):
        """
        判断大世界战斗是否已结束并回到地图。

        处理地图事件后检测是否仍在战斗中，若连续战斗则抛出异常；
        否则确认已回到大世界地图。

        Pages:
            in: 战斗结束结算或地图事件
            out: 大世界地图

        Returns:
            bool: 是否已回到大世界地图。
        """
        if self.handle_map_event(drop=self.__os_combat_drop):
            return False
        if self.combat_appear():
            raise ContinuousCombat

        return self.handle_os_in_map()

    __os_combat_drop = None

    def combat_status(self, drop=None, expected_end=None):
        """
        大世界战斗状态处理。

        禁用标准物品获取弹窗处理，仅使用大世界专用的地图物品获取逻辑。
        通过 _disable_handle_get_items 标志临时禁用 handle_get_items，
        使掉落物通过 handle_map_get_items 路径处理。

        Pages:
            in: 战斗执行中或战斗结束结算
            out: 大世界地图

        Args:
            drop (DropImage): 掉落图像对象。
            expected_end (callable): 自定义战斗结束判断函数，默认为 _os_combat_expected_end。
        """
        self.__os_combat_drop = drop
        if expected_end is None:
            expected_end = self._os_combat_expected_end
        # 禁用 handle_get_items，仅使用 handle_map_get_items
        self._disable_handle_get_items = True
        try:
            super().combat_status(drop=drop, expected_end=expected_end)
        finally:
            self._disable_handle_get_items = False

    def combat(self, *args, save_get_items=False, **kwargs):
        """
        处理大世界中的连续战斗。

        在塞壬扫描装置中，有 2 个无间隔的伏击敌人。
        舰队前往塞壬扫描装置，攻击一个敌人，跳过 TB，攻击另一个。
        标准 combat 函数需要确认战斗已结束且已返回地图，
        但处理塞壬扫描装置时会在第二场战斗中卡住。
        此函数通过捕获 ContinuousCombat 异常实现最多 3 次重试。

        Pages:
            in: 大世界地图，即将进入战斗
            out: 大世界地图，连续战斗全部结束

        Args:
            *args: 传递给父类 combat 的位置参数。
            save_get_items (bool): 是否保存物品获取截图。
            **kwargs: 传递给父类 combat 的关键字参数。
        """
        for count in range(3):
            self._clear_battle_status_s_timer()
            if count >= 2:
                logger.warning('Too many continuous combat')

            try:
                super().combat(*args, save_get_items=save_get_items, **kwargs)
                break
            except ContinuousCombat:
                logger.info('Continuous combat detected')
                continue
            finally:
                self._clear_battle_status_s_timer()

    def _handle_single_battle_status(self, status_button, status_letter, drop):
        """
        处理单个战斗评价状态按钮（S/A/B/C/D）。

        检测到对应评价按钮后，记录掉落数据并点击按钮关闭评价页面。
        S 评价记录为 info 级别，其余评价记录为 warning 级别。

        Args:
            status_button (Button): 评价状态按钮资源。
            status_letter (str): 评价等级字母（'S'/'A'/'B'/'C'/'D'）。
            drop (DropImage): 掉落图像对象，为 None 时仅等待随机时间。

        Returns:
            bool: 是否检测到并点击了评价按钮。
        """
        if self.appear(status_button, interval=self.battle_status_click_interval):
            if status_letter == 'S':
                logger.info(f'Battle Status {status_letter}')
            else:
                logger.warning(f'Battle Status {status_letter}')
            if drop:
                drop.handle_add(self)
            else:
                self.device.sleep((0.25, 0.5))
            self.device.click(status_button)
            return True
        return False

    def handle_battle_status(self, drop=None):
        """
        处理大世界战斗评价状态页面（S/A/B/C/D）。

        战斗执行中时重置 S 评价计时器并跳过处理。
        优先通过延迟机制处理 S 评价，再依次检查 A/B/C/D 评价。

        Pages:
            in: 战斗评价页面（S/A/B/C/D 任一可见）
            out: 评价页面已关闭

        Args:
            drop (DropImage): 掉落图像对象。

        Returns:
            bool: 是否处理了评价状态页面。
        """
        if self.is_combat_executing():
            self._clear_battle_status_s_timer()
            return False

        appeared, clicked = self._handle_auto_battle_status_s(drop=drop)
        if clicked:
            return True
        if appeared:
            return True

        for status_button, status_letter in [
            (BATTLE_STATUS_A, 'A'),
            (BATTLE_STATUS_B, 'B'),
            (BATTLE_STATUS_C, 'C'),
            (BATTLE_STATUS_D, 'D'),
        ]:
            if self._handle_single_battle_status(status_button, status_letter, drop):
                return True
        return False

    def handle_auto_search_battle_status(self, drop=None, battle_status_s_timer=None):
        """
        自动搜索模式下的战斗评价状态处理。

        与 handle_battle_status 类似，但使用外部传入的 S 评价计时器，
        且不检查 is_combat_executing 状态（由调用方保证）。

        Pages:
            in: 战斗评价页面（S/A/B/C/D 任一可见）
            out: 评价页面已关闭

        Args:
            drop (DropImage): 掉落图像对象。
            battle_status_s_timer (Timer): S 评价延迟计时器。

        Returns:
            bool: 是否处理了评价状态页面。
        """
        _, clicked = self._handle_auto_battle_status_s(
            drop=drop, timer=battle_status_s_timer
        )
        if clicked:
            return True

        for status_button, status_letter in [
            (BATTLE_STATUS_A, 'A'),
            (BATTLE_STATUS_B, 'B'),
            (BATTLE_STATUS_C, 'C'),
            (BATTLE_STATUS_D, 'D'),
        ]:
            if self._handle_single_battle_status(status_button, status_letter, drop):
                return True
        return False

    def handle_auto_search_exp_info(self):
        """
        自动搜索模式下的经验结算页面处理。

        依次检查 S/A/B/C/D 经验结算按钮，点击后清除 S 评价计时器并等待随机时间。
        等待时间根据是否有掉落物决定（有掉落 1.5-2 秒，无掉落 0.25-0.5 秒）。

        Pages:
            in: 经验结算页面（S/A/B/C/D 任一可见）
            out: 经验结算页面已关闭

        Returns:
            bool: 是否点击了经验结算按钮。
        """
        sleep = self._get_exp_info_sleep()
        for exp_info_button in [EXP_INFO_S, EXP_INFO_A, EXP_INFO_B, EXP_INFO_C, EXP_INFO_D]:
            if self.appear_then_click(exp_info_button):
                self._clear_battle_status_s_timer()
                self.device.sleep(sleep)
                return True
        return False

    def auto_search_combat(self, drop=None):
        """
        大世界自动搜索战斗处理。

        分为加载和执行两个阶段：加载阶段等待战斗界面就绪，
        执行阶段处理潜艇呼叫、战斗评价、经验结算和地图事件。
        CL1 指标模式下设置 5 分钟超时限制。

        Pages:
            in: 战斗加载中（is_combat_loading()）
            out: 大世界地图（战斗状态处理完毕）

        Args:
            drop (DropImage): 掉落图像对象。

        Returns:
            bool: 敌人是否已清除，舰队阵亡则返回 False。

        Raises:
            GameBugError: CL1 指标模式下战斗超过 5 分钟超时。
        """
        # 保持战斗专注于状态转换；指标层决定此任务是否应产生 CL1/short-meow 计时样本。
        battle_timer_source = start_battle_timer(self.config)
        
        cl1_combat_timer = Timer(300, count=300)
        
        logger.info('Auto search combat loading')
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        self.device.screenshot_interval_set('combat')
        while 1:
            self.device.screenshot()

            if self.handle_combat_automation_confirm():
                continue

            # 结束
            if self.handle_os_auto_search_map_option(drop=drop):
                self._clear_battle_status_s_timer()
                break
            pause = self.is_combat_executing()
            if pause:
                logger.attr('BattleUI', pause)
                break
            if self.is_in_map():
                break

        logger.info('Auto Search combat execute')
        self.submarine_call_reset()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        submarine_mode = 'do_not_use'
        if self.config.Submarine_Fleet:
            submarine_mode = self.config.Submarine_Mode

        if battle_timer_source == 'cl1':
            cl1_combat_timer.start()

        success = True
        battle_status_s_timer = Timer(self.battle_status_s_autoclick_delay)
        while 1:
            self.device.screenshot()

            if battle_timer_source == 'cl1' and cl1_combat_timer.reached():
                logger.warning('CL1 combat timeout (5 minutes limit reached)')
                raise GameBugError('CL1 combat timeout')

            if self.handle_submarine_call(submarine_mode):
                continue
            # 失败时不更改自动搜索选项
            enable = success if success is not None else None
            if self.handle_os_auto_search_map_option(drop=drop, enable=enable):
                battle_status_s_timer.clear()
                continue

            # 结束
            if self.is_in_map():
                self.device.screenshot_interval_set()
                break
            if self.is_combat_executing():
                battle_status_s_timer.clear()
                continue
            if self.config.OpsiGeneral_RepairThreshold > 0 and self.handle_auto_search_exp_info():
                battle_status_s_timer.clear()
                success = None
                continue
            if self.handle_auto_search_battle_status(drop=drop, battle_status_s_timer=battle_status_s_timer):
                success = None
                continue
            if self.handle_map_event():
                battle_status_s_timer.clear()
                continue
            
        logger.info('Combat end.')
        
        # 通过相同的指标源结束，避免 CL1 和 short-meow 样本意外共享存储键。
        finish_battle_timer(self.config, battle_timer_source)
        
        return success

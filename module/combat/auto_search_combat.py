"""自动搜索战斗管理器。

管理通关模式（快进模式）下的自动搜索战斗流程。

在通关模式下，游戏会自动进行地图探索和战斗。
此模块负责：
- 启动自动搜索（地图中的出击按钮）
- 等待自动搜索完成（检测回到关卡页面）
- 处理战斗期间的异常（退役、低情绪、撤退等）
- 检测停止条件（石油/物资限制、通关次数等）
- Boss 战后的关卡推进

继承自 MapOperation + Combat + CampaignStatus，
组合了地图操作、战斗系统和战役状态追踪的能力。
"""

from module.base.timer import Timer
from module.campaign.campaign_status import CampaignStatus
from module.combat.assets import *
from module.combat.combat import Combat
from module.exception import CampaignEnd, GameStuckError, RequestHumanTakeover, ScriptEnd
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF, AUTO_SEARCH_MAP_OPTION_ON, FLEET_UNAVAILABLE
from module.logger import logger
from module.map.assets import WITHDRAW, FLEET_NUM_1, FLEET_NUM_2
from module.map.map_operation import MapOperation


class AutoSearchCombat(MapOperation, Combat, CampaignStatus):
    """自动搜索战斗执行器。

    在通关模式下编排自动搜索战斗流程，处理各种战斗异常和停止条件。

    Attributes:
        _auto_search_in_stage_timer (Timer): 关卡页面检测计时器。
        _auto_search_status_confirm (bool): 自动搜索状态是否已确认。
        _withdraw (bool): 是否仍有待处理的战败撤退或换队。
        _defeat_count (int): 连续战败次数。
        auto_search_oil_limit_triggered (bool): 石油限制是否已触发。
        auto_search_coin_limit_triggered (bool): 物资限制是否已触发。
    """
    _auto_search_in_stage_timer = Timer(3, count=6)
    _auto_search_status_confirm = False
    _withdraw = False
    _defeat_count = 0
    auto_search_defeat_recovery = True
    auto_search_oil_limit_triggered = False
    auto_search_coin_limit_triggered = False

    def auto_search_recovery_state(self):
        """异常重启只识别返回的关卡地图，不接管重启前的战斗或结算。"""
        if self.is_auto_search_running() or (self.is_in_map() and self.appear(WITHDRAW, offset=(30, 30))):
            return 'map'
        return None

    def prepare_auto_search_recovery(self, state):
        """确认已回到地图后开启自律，后续战斗重新按普通入口计算心情。"""
        if state != 'map':
            return False
        self.combat_result_reset()
        self._withdraw = False
        self._auto_search_status_confirm = False
        self._auto_search_fleet_confirmed = False
        if self.is_auto_search_running():
            logger.info('[战役续接] 自律寻敌已开启，直接接管，不重复点击')
        self._restart_resume_timer = Timer(30, count=60).start()
        self._restart_resume_click_timer = Timer(2).start()
        self._restart_resume_guard = True
        self._restart_emotion_checked = False
        self._auto_search_in_stage_timer.reset()
        logger.info('[战役续接] 已返回关卡地图，恢复自律；后续战斗按正常流程计算心情')
        return True

    def handle_auto_search_map_option(self):
        """重启续接时以模板和颜色共同确认 OFF，沿用原点击冷却。"""
        if not self.__dict__.get('_restart_resume_guard', False):
            return super().handle_auto_search_map_option()
        if self._restart_resume_timer is None:
            if not (self.is_auto_search_running() or self.is_in_map()):
                return False
            self._restart_resume_timer = Timer(30, count=60).start()
        if self._restart_resume_timer.reached():
            raise GameStuckError('[战役续接] 自律寻敌未在期限内进入战斗')
        if self.is_auto_search_running():
            return False
        # 刚回到地图时先持续截图两秒，避免游戏尚未就绪就触发开关。
        if not self._restart_resume_click_timer.reached():
            return False
        if self.is_combat_loading() or self.is_combat_executing():
            return False
        if not self.match_template_color(AUTO_SEARCH_MAP_OPTION_OFF,
                                         offset=self._auto_search_offset, threshold=10):
            return False
        if not self._restart_emotion_checked:
            self.auto_search_watch_fleet()
            if not self.__dict__.get('_auto_search_fleet_confirmed'):
                return False
            try:
                self.emotion.check_fleet(self.fleet_show_index, after_restart=True)
            except (ScriptEnd, RequestHumanTakeover) as error:
                if isinstance(error, RequestHumanTakeover):
                    from module.config.recovery import check_error_recovery
                    check_error_recovery(self.config, error)
                logger.warning('[战役续接] 舰队心情检查未通过，先撤退再交回任务处理')
                try:
                    self.withdraw()
                except CampaignEnd:
                    pass
                raise
            self._restart_emotion_checked = True
            logger.info('[战役续接] 已确认自律寻敌关闭，尝试恢复')
        return super().handle_auto_search_map_option()

    def _handle_auto_search_menu_missing(self):
        """处理自动搜索菜单缺失的异常情况。

        有时游戏出现异常未显示自动搜索菜单，Boss 战后直接返回关卡页面。
        若停留在关卡页面超过一定时间，则判定自动搜索已结束。

        Returns:
            bool: 是否触发自动搜索结束。
        """
        if self.is_in_stage():
            if self._auto_search_in_stage_timer.reached():
                logger.info('捕获自动搜索菜单缺失')
                return True
        else:
            self._auto_search_in_stage_timer.reset()

        return False

    def map_offensive_auto_search(self, skip_first_screenshot=True):
        """在地图中启动自动搜索。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。

        Pages:
            in: in_map, MAP_OFFENSIVE
            out: is_combat_loading
        """
        self.interval_reset(AUTO_SEARCH_MAP_OPTION_ON)
        for _ in self.loop():

            if self.handle_auto_search_map_option():
                self.interval_reset(AUTO_SEARCH_MAP_OPTION_ON)
                continue
            # 处理碧蓝航线客户端异常：
            # 从退役界面退出并立即开启自动搜索时，图标显示正在运行但实际未动作。
            # 定时点击：每 3 秒尝试关闭自动搜索一次，不包含初始阶段
            if not self.__dict__.get('_restart_resume_guard', False) \
                    and self.appear(AUTO_SEARCH_MAP_OPTION_ON, offset=self._auto_search_offset, interval=3) \
                    and self.appear_then_click(AUTO_SEARCH_MAP_OPTION_ON):
                continue
            if self.handle_combat_low_emotion():
                continue
            if self.handle_retirement():
                continue

            # 结束判断
            if self.is_combat_loading():
                break

    def auto_search_watch_fleet(self, checked=False):
        """监控舰队索引与舰船等级。

        Args:
            checked (bool, optional): 舰队移动期间监控操作仅执行或记录一次。
                设为 True 跳过再次执行。默认为 False。

        Returns:
            bool: 监控操作是否已执行。
        """
        prev = self.fleet_current_index
        if self.appear(FLEET_NUM_1, offset=(20, 20)):
            self.fleet_show_index = 1
        elif self.appear(FLEET_NUM_2, offset=(20, 20)):
            self.fleet_show_index = 2
        else:
            # 转场读不到编号时保留上一次正向确认，不能把二队改记为默认一队。
            return checked
        self._auto_search_fleet_confirmed = True
        self.get_fleet_current_index()
        if self.fleet_current_index == prev:
            # 与当前舰队一致，仅输出一次日志
            if not checked:
                logger.info(f'[自动搜索-舰队] 舰队: {self.fleet_show_index}, 当前舰队索引: {self.fleet_current_index}')
                checked = True
                self.lv_get(after_battle=True)
        else:
            # 舰队发生切换
            logger.info(f'[自动搜索-舰队] 舰队: {self.fleet_show_index}, 当前舰队索引: {self.fleet_current_index}')
            checked = True
            self.lv_get(after_battle=False)

        return checked

    def auto_search_watch_oil(self, checked=False):
        """监控当前石油存量并更新石油限制状态。

        Args:
            checked (bool, optional): 是否已执行过检查。默认为 False。

        Returns:
            bool: 检查是否已执行。
        """
        if not checked:
            oil = self.get_oil()
            if oil == 0:
                logger.warning('未找到石油')
            else:
                if oil < max(self.config.StopCondition_OilLimitHardFloor, self.config.StopCondition_OilLimit):
                    logger.info('达到石油上限')
                    self.auto_search_oil_limit_triggered = True
                else:
                    if self.auto_search_oil_limit_triggered:
                        logger.warning('[自动搜索-石油] 石油限制已触发但石油已恢复，'
                                       '可能是因为之前的OCR结果错误')
                    self.auto_search_oil_limit_triggered = False
                checked = True

        return checked

    def auto_search_watch_coin(self, checked=False):
        """监控当前物资存量并更新物资限制状态。

        Args:
            checked (bool, optional): 是否已执行过检查。默认为 False。

        Returns:
            bool: 检查是否已执行。
        """
        if not checked:
            limit = self.config.TaskBalancer_CoinLimit
            coin = self.get_coin()
            if coin == 0:
                logger.warning('未找到物资')
            else:
                if self.is_balancer_task():
                    if coin < limit:
                        logger.info('达到物资上限')
                        self.auto_search_coin_limit_triggered = True
                    else:
                        # 物资充足
                        self.auto_search_coin_limit_triggered = False
                else:
                    if self.auto_search_coin_limit_triggered:
                        logger.warning('[自动搜索-物资] 物资限制已触发但物资已恢复，'
                                       '可能是因为之前的OCR结果错误')
                    self.auto_search_coin_limit_triggered = False
                checked = True

        return checked

    def _wait_until_in_map(self, skip_first_screenshot=True):
        """等待直到回到地图界面。

        处理退役或强化退出后立即开启自动搜索时，
        图标显示运行但游戏无响应的客户端异常。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。

        Pages:
            in: 退出退役或强化界面
            out: in_map()
        """
        timeout = Timer(3, count=6).start()
        for _ in self.loop():

            if self.is_in_map():
                break
            if timeout.reached():
                logger.warning('[自动搜索-地图] 等待退役后进入地图超时，假设已在地图中')
                break

    def auto_search_moving(self, skip_first_screenshot=True):
        """监控自动搜索中的舰队移动状态。

        持续监控舰队移动、更新资源状态，并处理途中遭遇的退役、心情、剧情等弹窗。

        Args:
            skip_first_screenshot (bool, optional): 是否跳过首次截图。默认为 True。

        Raises:
            CampaignEnd: 检测到自动搜索菜单或菜单丢失时抛出，表示本轮探索结束。

        Pages:
            in: 地图界面
            out: is_combat_loading()
        """
        logger.info('自动搜索移动中')
        self.device.stuck_record_clear()
        checked_fleet = False
        checked_oil = False
        checked_coin = False
        for _ in self.loop():

            if self.is_auto_search_running():
                checked_fleet = self.auto_search_watch_fleet(checked_fleet)
                if not checked_oil or not checked_coin:
                    checked_oil = self.auto_search_watch_oil(checked_oil)
                    checked_coin = self.auto_search_watch_coin(checked_coin)
            if self.handle_retirement():
                self.map_offensive_auto_search()
                # 地图出击在 is_combat_loading 处结束
                break
            if self.handle_auto_search_map_option():
                continue
            if self.handle_combat_low_emotion():
                self._auto_search_status_confirm = True
                continue
            if self.handle_story_skip():
                continue
            if self.handle_map_cat_attack():
                continue
            if self.handle_vote_popup():
                continue

            # 结束判断
            if self.is_combat_loading():
                break
            if self.is_combat_executing():
                logger.info('[自动搜索-战斗] 战斗执行中')
                break
            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                raise CampaignEnd

    def auto_search_combat_execute(self, emotion_reduce, fleet_index, battle=None, expected_end=None,
                                   shipwreck_reduce=None):
        """执行自动搜索战斗过程。

        包含战斗加载、自律/手动控制、潜艇召唤、弹窗处理及结算判定。

        Args:
            emotion_reduce (bool): 是否扣减心情。
            fleet_index (int): 当前画面显示的舰队编号（1 或 2），用于选择心情账本。
            battle (tuple[int, int], optional): 当前战斗场次信息 (当前战斗计数, 总战斗计数)。默认为 None。
            expected_end (callable, optional): 外部传入的战斗结束判定回调函数。默认为 None。
            shipwreck_reduce (bool, optional): 是否记录本场结果的额外心情扣减，默认跟随基础扣减。
                联盟多队模式仅首场扣基础心情，但每场仍需观察结果。

        Raises:
            CampaignEnd: 检测到自动搜索菜单时抛出，表示探索已结束。

        Pages:
            in: is_combat_loading()
            out: 战斗结算状态
        """
        self._withdraw = False
        self.combat_result_reset(
            emotion_reduce=emotion_reduce if shipwreck_reduce is None else shipwreck_reduce,
            fleet_index=fleet_index)
        logger.info('自动搜索战斗加载中')
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        self.device.screenshot_interval_set('combat')
        for _ in self.loop():

            if self.handle_combat_automation_confirm():
                continue
            if self.handle_story_skip():
                continue
            if self.handle_vote_popup():
                continue
            # 加载期间出现的红脸（低心情）弹窗同样没有任何其他处理器会认，
            # 不处理会一直等到 GameStuckError。ignore 模式下点「确定」继续出击
            if self.handle_combat_low_emotion():
                continue
            # 过图期间弹出的「船坞已满」弹窗没有任何其他处理器会认，
            # 不处理会一直等到 GameStuckError。处理完退役/强化后重新开启
            # 自动搜索，等待游戏自己再次进入战斗加载
            if self.handle_retirement():
                # 退役流程在地图上进行，先恢复普通截图间隔
                self.device.screenshot_interval_set()
                self.map_offensive_auto_search()
                self.device.screenshot_interval_set('combat')
                continue

            # End
            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                raise CampaignEnd
            pause = self.is_combat_executing()
            if pause:
                logger.attr('战斗UI', pause)
                break

        logger.info('[自动搜索-战斗] 战斗执行')
        self._restart_resume_guard = False
        self.submarine_call_reset()
        submarine_mode = 'do_not_use'
        if self.config.Submarine_Fleet:
            submarine_mode = self.config.Submarine_Mode
        force_call = battle[0] == battle[1] - 1 if battle is not None else False
        self.combat_auto_reset()
        self.combat_manual_reset()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        if emotion_reduce:
            self.emotion.reduce(fleet_index)
        auto = self.config.Fleet_Fleet1Mode if fleet_index == 1 else self.config.Fleet_Fleet2Mode

        confirm_timer = Timer(10)
        confirm_timer.start()
        while 1:
            self.device.screenshot()

            # C/D 共用的失败画面优先于通用弹窗；记录结果后交给结算恢复。
            if self.handle_combat_defeat():
                break
            if self.appear(FLEET_UNAVAILABLE, offset=(160, 30)):
                self.combat_result_record(fleet_unavailable=True)
                break

            if self.handle_submarine_call(submarine_mode, call=force_call):
                continue
            if self.handle_combat_auto(auto):
                continue
            if self.handle_combat_manual(auto):
                continue
            if auto != 'combat_auto' and self.auto_mode_checked and self.is_combat_executing():
                if self.handle_combat_weapon_release():
                    continue
            # 处理各种弹窗
            if self.handle_popup_confirm('AUTO_SEARCH_COMBAT_EXECUTE'):
                continue
            if not self._withdraw and self.handle_urgent_commission():
                continue
            if self.handle_story_skip():
                continue
            if self.handle_guild_popup_cancel():
                continue
            if self.handle_vote_popup():
                continue
            if self.handle_mission_popup_ack():
                continue

            # 结束判断
            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                self.device.screenshot_interval_set()
                raise CampaignEnd
            if self.is_combat_executing():
                confirm_timer.reset()
                continue
            if self.handle_get_ship():
                continue
            if self.combat_result_observe():
                break
            if confirm_timer.reached():
                # 超时只转交结算处理；没有沉船弹窗不能确认战败。
                logger.warning('[自动搜索-战斗] 结算确认超时，进入status处理')
                confirm_timer.reset()
                break
            if self.is_auto_search_running():
                self.device.screenshot_interval_set()
                break
            if callable(expected_end):
                if expected_end():
                    self.device.screenshot_interval_set()
                    break

    def combat_defeat_recovery(self):
        """自动搜索任务每场只登记一次恢复请求；联盟自行推进活动流程。"""
        if not self.auto_search_defeat_recovery or not self.map_is_auto_search:
            return
        self._withdraw = True
        if self.config.Campaign_DefeatWithdraw == 'withdraw_stop':
            self._defeat_count += 1
            logger.attr('战败计数', f'{self._defeat_count}/3')

    def _wait_withdraw_stable(self, withdraw_stable_timer):
        """
        等待WITHDRAW按钮稳定出现，防止界面过渡动画导致误判。

        Args:
            withdraw_stable_timer (Timer): WITHDRAW按钮稳定计时器

        Returns:
            bool: True表示WITHDRAW按钮已稳定出现，可以点击；
                  False表示按钮尚未出现或不稳定，需要继续等待。
        """
        withdraw_appear = self.appear(WITHDRAW, offset=(30, 30))
        if withdraw_appear:
            withdraw_stable_timer.start()
            if not withdraw_stable_timer.reached():
                return False
            return True
        else:
            withdraw_stable_timer.clear()
            return False

    def auto_search_combat_status(self):
        """处理自动搜索战斗后的结算与战败恢复。

        处理经验结算、掉落物品、战败撤退与舰队切换，直至自动搜索重新运行或关卡结束。

        Raises:
            CampaignEnd: 战斗结束且回到自动搜索菜单，或触发撤退时抛出。
            ScriptEnd: 连续战败停止，或接替舰队心情不足，退出后抛出。
            RequestHumanTakeover: 接替舰队账本不可用，退出后抛出。

        Pages:
            in: 任意结算界面
            out: is_auto_search_running()，或恢复自律后进入加载/战斗
        """
        logger.info('[自动搜索-结算] 战斗结算')
        self.device.screenshot_interval_set()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        withdraw_stable_timer = Timer(2)
        handoff_timer = None
        handoff_failed = False
        resume_checked = False
        resume_started = False
        resume_error = None
        for _ in self.loop():

            if self.handle_combat_defeat():
                continue
            # 该正文意味着游戏将自动换队；不能让通用「确定」误识别成紧急委托。
            if self.appear(FLEET_UNAVAILABLE, offset=(160, 30)):
                self.combat_result_record(fleet_unavailable=True)
                if self.appear(FLEET_UNAVAILABLE, offset=(160, 30), interval=2):
                    # 正文随动态舰队名居中偏移，确认按钮本身仍在固定位置。
                    FLEET_UNAVAILABLE.clear_offset()
                    self.device.click(FLEET_UNAVAILABLE)
                continue

            if self._withdraw:
                # 开启后可能直接进入加载/战斗，不能一直等地图上的 ON 图标。
                if resume_started and (self.is_combat_loading() or self.is_combat_executing()):
                    self._withdraw = False
                    self._auto_search_status_confirm = False
                    break
                # 战败后可能直接回到菜单或选关页，仍须退出并执行关闭任务策略。
                if self.is_in_stage():
                    self._withdraw = False
                    if resume_error is not None:
                        raise resume_error
                    if self.config.Campaign_DefeatWithdraw == 'withdraw_stop' and self._defeat_count >= 3:
                        raise ScriptEnd('DefeatWithdraw=withdraw_stop')
                    raise CampaignEnd('Withdraw')
                if self.handle_auto_search_exit():
                    continue
            elif self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                if not self.combat_result.defeated:
                    self._defeat_count = 0
                raise CampaignEnd

            # 撤退等待同样可能被紧急委托、剧情或奖励挡住，处理后重新截图。
            if self.handle_urgent_commission():
                continue
            if self.handle_story_skip():
                continue
            if self.handle_guild_popup_cancel():
                continue
            if self.handle_vote_popup():
                continue
            if self.handle_mission_popup_ack():
                continue
            if self.handle_get_ship():
                continue
            if self.handle_get_items():
                continue
            if self.handle_battle_status():
                continue
            if self.handle_exp_info():
                continue

            # 撤退处理
            if self._withdraw:
                defeat_withdraw = self.config.Campaign_DefeatWithdraw
                allow_switch = defeat_withdraw == 'switch_fleet' and self.combat_result.fleet_unavailable \
                    and not handoff_failed
                if allow_switch:
                    if handoff_timer is None:
                        handoff_timer = Timer(10, count=20).start()
                    # 只等游戏自动换队；原队仍可用时手动切队会被游戏按职责切回。
                    target_index = 3 - self.combat_result.fleet_index
                    target = FLEET_NUM_2 if target_index == 2 else FLEET_NUM_1
                    if self.appear(target, offset=(20, 20)):
                        self.fleet_show_index = target_index
                        if not resume_checked:
                            try:
                                self.emotion.check_fleet(target_index)
                            except (RequestHumanTakeover, ScriptEnd) as exc:
                                if isinstance(exc, RequestHumanTakeover):
                                    from module.config.recovery import check_error_recovery
                                    check_error_recovery(self.config, exc)
                                logger.warning('[战败恢复] 接替舰队心情检查未通过，先撤退再上报')
                                resume_error = exc
                                handoff_failed = True
                                continue
                            resume_checked = True
                        if self.is_auto_search_running():
                            self._withdraw = False
                            self._auto_search_status_confirm = False
                            break
                        if self.handle_auto_search_map_option():
                            resume_started = True
                            continue
                    if handoff_timer.reached():
                        logger.warning('[战败恢复] 未确认游戏自动换队，改为撤退')
                        handoff_failed = True
                    continue

                # 游戏战败时已停止自律。撤退或尚未确认换队时不操作开关；
                # ON/OFF 的文字模板会互相命中，点击所谓 ON 反而可能开启自律。
                if self.handle_popup_confirm('WITHDRAW'):
                    continue
                if not self._wait_withdraw_stable(withdraw_stable_timer):
                    continue
                if self.appear_then_click(WITHDRAW, offset=(30, 30), interval=5):
                    continue
                continue

            # 战斗结算状态处理
            if self.is_auto_search_running():
                self._auto_search_status_confirm = False
                if not self.combat_result.defeated and self._defeat_count > 0:
                    logger.info('战斗胜利，重置失败计数')
                    self._defeat_count = 0
                break
            if self.handle_auto_search_map_option():
                self._auto_search_status_confirm = False
                continue
            if self.handle_popup_confirm('AUTO_SEARCH_COMBAT_STATUS'):
                continue

    def auto_search_combat(self, emotion_reduce=None, fleet_index=1, battle=None):
        """执行单次自动搜索战斗全流程。

        包含战斗执行及后续的状态结算。
        fleet_index 跟随调用方读取的 fleet_show_index，表示画面舰队编号，
        不使用考虑舰队顺序反转后的 fleet_current_index 推断换队目标。

        Args:
            emotion_reduce (bool, optional): 是否扣减心情。若为 None 则使用 self.emotion.is_calculate。默认为 None。
            fleet_index (int, optional): 当前画面显示的舰队编号（1 或 2）。默认为 1。
            battle (tuple[int, int], optional): 当前战斗场次信息。默认为 None。
        """
        emotion_reduce = emotion_reduce if emotion_reduce is not None else self.emotion.is_calculate

        self.auto_search_combat_execute(emotion_reduce=emotion_reduce, fleet_index=fleet_index, battle=battle)
        self.auto_search_combat_status()

        logger.info('[自动搜索-战斗] 战斗结束')

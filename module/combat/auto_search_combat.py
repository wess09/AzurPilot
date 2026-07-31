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
from module.exception import CampaignEnd, ScriptEnd
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_ON, GET_MISSION
from module.logger import logger
from module.map.assets import WITHDRAW, SWITCH_OVER, FLEET_WITHDRAW, FLEET_SWITCH_CONFIRM, FLEET_WITHDRAW_BOSS
from module.map.map_operation import MapOperation


class AutoSearchCombat(MapOperation, Combat, CampaignStatus):
    """自动搜索战斗执行器。

    在通关模式下编排自动搜索战斗流程，处理各种战斗异常和停止条件。

    Attributes:
        _auto_search_in_stage_timer (Timer): 关卡页面检测计时器。
        _auto_search_status_confirm (bool): 自动搜索状态是否已确认。
        _withdraw (bool): 是否已执行撤退。
        _defeat_count (int): 战败次数。
        _shipwreck_emotion_reduced (bool): 沉船心情扣减是否已执行，防止重复扣减。
        _auto_search_emotion_reduce (bool): 当前战斗是否启用心情扣减。
        _auto_search_fleet_index (int): 当前战斗的舰队索引。
        auto_search_oil_limit_triggered (bool): 石油限制是否已触发。
        auto_search_coin_limit_triggered (bool): 物资限制是否已触发。
    """
    _auto_search_in_stage_timer = Timer(3, count=6)
    _auto_search_status_confirm = False
    _withdraw = False
    _defeat_count = 0
    _shipwreck_emotion_reduced = False
    _auto_search_emotion_reduce = False
    _auto_search_fleet_index = 1
    auto_search_oil_limit_triggered = False
    auto_search_coin_limit_triggered = False

    def _handle_auto_search_menu_missing(self):
        """
        Sometimes game is bugged, auto search menu is not shown.
        After BOSS battle, it enters campaign directly.
        To handle this, if game in campaign for a certain time, it means auto search ends.

        Returns:
            bool: If triggered
        """
        if self.is_in_stage():
            if self._auto_search_in_stage_timer.reached():
                logger.info('捕获自动搜索菜单缺失')
                return True
        else:
            self._auto_search_in_stage_timer.reset()

        return False

    def map_offensive_auto_search(self, skip_first_screenshot=True):
        """
        Pages:
            in: in_map, MAP_OFFENSIVE
            out: is_combat_loading
        """
        self.interval_reset(AUTO_SEARCH_MAP_OPTION_ON)
        for _ in self.loop():

            if self.handle_auto_search_map_option():
                self.interval_reset(AUTO_SEARCH_MAP_OPTION_ON)
                continue
            # To handle a bug in Azur Lane game client.
            # Auto search icon shows it's running but it's doing nothing
            # when Alas exited from retirement and turned it on immediately.
            # Monkey clicker, disable auto search every 3s, beginning not included
            if self.appear(AUTO_SEARCH_MAP_OPTION_ON, offset=self._auto_search_offset, interval=3) \
                    and self.appear_then_click(AUTO_SEARCH_MAP_OPTION_ON):
                continue
            if self.handle_combat_low_emotion():
                continue
            if self.handle_retirement():
                continue

            # Break
            if self.is_combat_loading():
                break

    def auto_search_watch_fleet(self, checked=False):
        """
        Watch fleet index and ship level.

        Args:
            checked (bool): Watchers are only executed or logged once during fleet moving.
                            Set True to skip executing again.

        Returns:
            bool: If executed.
        """
        prev = self.fleet_current_index
        self.get_fleet_show_index()
        self.get_fleet_current_index()
        if self.fleet_current_index == prev:
            # Same as current, only print once
            if not checked:
                logger.info(f'[自动搜索-舰队] 舰队: {self.fleet_show_index}, 当前舰队索引: {self.fleet_current_index}')
                checked = True
                self.lv_get(after_battle=True)
        else:
            # Fleet changed
            logger.info(f'[自动搜索-舰队] 舰队: {self.fleet_show_index}, 当前舰队索引: {self.fleet_current_index}')
            checked = True
            self.lv_get(after_battle=False)

        return checked

    def auto_search_watch_oil(self, checked=False):
        """
        Watch oil.
        This will set auto_search_oil_limit_triggered.
        """
        if not checked:
            oil = self.get_oil()
            if oil == 0:
                logger.warning('未找到石油')
            else:
                if oil < max(500, self.config.StopCondition_OilLimit):
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
        """
        Watch coin.
        This will set auto_search_coin_limit_triggered.
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
                        # Enough coin
                        self.auto_search_coin_limit_triggered = False
                else:
                    if self.auto_search_coin_limit_triggered:
                        logger.warning('auto_search_coin_limit_triggered but coin recovered, '
                                       'probably because of wrong OCR result before')
                    self.auto_search_coin_limit_triggered = False
                checked = True

        return checked

    def _wait_until_in_map(self, skip_first_screenshot=True):
        """
        To handle a bug in Azur Lane game client.
        Auto search icon shows it's running but it's doing nothing
        when Alas exited from retirement and turned it on immediately.

        Pages:
            in: Exiting from retirement or enhancement
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
        """
        Pages:
            in: map
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
                # Map offensive ends at is_combat_loading
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

            # End
            if self.is_combat_loading():
                break
            if self.is_combat_executing():
                logger.info('[自动搜索-战斗] 战斗执行中')
                break
            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                raise CampaignEnd

    def auto_search_combat_execute(self, emotion_reduce, fleet_index, battle=None, expected_end=None):
        """
        Args:
            emotion_reduce (bool):
            fleet_index (int):
            expected_end (callable):

        Pages:
            in: is_combat_loading()
            out: combat status
        """
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

            # End
            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                raise CampaignEnd
            pause = self.is_combat_executing()
            if pause:
                logger.attr('战斗UI', pause)
                break

        logger.info('[自动搜索-战斗] 战斗执行')
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

            if self.handle_submarine_call(submarine_mode, call=force_call):
                continue
            if self.handle_combat_auto(auto):
                continue
            if self.handle_combat_manual(auto):
                continue
            if auto != 'combat_auto' and self.auto_mode_checked and self.is_combat_executing():
                if self.handle_combat_weapon_release():
                    continue
            # bunch of popup handlers
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

            # End
            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                self.device.screenshot_interval_set()
                raise CampaignEnd
            if self.is_combat_executing():
                confirm_timer.reset()
                continue
            if self.handle_get_ship():
                continue
            if self.appear_then_click(OPTS_INFO_D, offset=(30, 30), interval=2):
                if emotion_reduce and not self._shipwreck_emotion_reduced:
                    self.emotion.reduce(fleet_index, shipwreck=True)
                    self._shipwreck_emotion_reduced = True
                self._withdraw = True
                break
            # D评价结算界面（BATTLE_STATUS_D / EXP_INFO_D）
            # S/A/B评价的动画过渡帧可能短暂误匹配D评价模板，
            # 但只有真正的沉船才会出现OPTS_INFO_D弹窗。
            # 此处不设置 _withdraw，让后续S/A/B评价条件覆盖误匹配。
            # 真正的D评价会先被上方OPTS_INFO_D捕获。
            if self.appear(BATTLE_STATUS_D) or self.appear(EXP_INFO_D):
                break
            if confirm_timer.reached():
                # 结算确认超时：不扣心情、不盲目点击OPTS_INFO_D
                # 只设置_withdraw让status处理，status中检测到OPTS_INFO_D才扣心情
                logger.warning('[自动搜索-战斗] 结算确认超时，进入status处理')
                self._withdraw = True
                confirm_timer.reset()
                break
            # A/B/C评价可能是沉船或作战超时导致，通过Shipwreck_Marker错误标识区分：
            # - 沉船：结算界面出现错误标识×，游戏扣减-10心情
            # - 超时：结算界面无错误标识×，游戏不额外扣减心情（仅有正常战斗消耗）
            # S评价是完美战斗不会有沉船，D评价一定有错误标识（由OPTS_INFO_D处理）
            if self.appear(BATTLE_STATUS_A) or self.appear(BATTLE_STATUS_B) \
                    or self.appear(BATTLE_STATUS_C) \
                    or self.appear(EXP_INFO_A) or self.appear(EXP_INFO_B) \
                    or self.appear(EXP_INFO_C):
                if emotion_reduce:
                    if self.appear(Shipwreck_Marker_BUTTON):
                        logger.info('[自动搜索-战斗] A/B/C评价检测到沉船标识，扣减-10心情')
                        self.emotion.reduce(fleet_index, shipwreck=True)
                    else:
                        logger.info('[自动搜索-战斗] A/B/C评价未检测到沉船标识（作战超时），不额外扣减心情')
                break
            if self.appear(BATTLE_STATUS_S) or self.appear(EXP_INFO_S) \
                    or self.appear(GET_MISSION) or self.is_auto_search_running():
                self.device.screenshot_interval_set()
                break
            if callable(expected_end):
                if expected_end():
                    self.device.screenshot_interval_set()
                    break
            

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
            if not withdraw_stable_timer.reached():
                return False
            return True
        else:
            withdraw_stable_timer.reset()
            return False

    def _handle_fleet_switch_over(self):
        """
        处理舰队切换操作：仅撤退当前战败舰队，切换到另一队继续战斗。
        包含超时保护，避免UI异常时无限循环。

        Returns:
            bool: True表示切换成功，False表示超时。
        """
        timeout = Timer(10, count=20).start()
        while 1:
            self.device.screenshot()
            if self.appear_then_click(FLEET_WITHDRAW, offset=(30, 30)):
                break
            if self.appear(FLEET_WITHDRAW_BOSS, offset=(30, 30)):
                self.withdraw()
                break
            if self.appear_then_click(SWITCH_OVER, interval=2):
                continue
            if timeout.reached():
                logger.warning('舰队切换超时，改为撤退')
                self.withdraw()
                break
        self.fleet_alive_multiple = False
        return True

    def auto_search_combat_status(self):
        """
        Pages:
            in: any
            out: is_auto_search_running()
        """
        logger.info('[自动搜索-结算] 战斗结算')
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        exp_info = False  # This is for the white screen bug in game
        withdraw_stable_timer = Timer(2)

        for _ in self.loop():

            # End
            if self.is_auto_search_running():
                self._auto_search_status_confirm = False
                # 战斗正常结束（非战败），重置连续战败计数
                if self._defeat_count > 0:
                    logger.info('战斗胜利，重置失败计数')
                    self._defeat_count = 0
                break
            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                raise CampaignEnd

            # Withdraw
            if self._withdraw:
                # 先处理战斗结算界面（D评价、经验信息、获得舰船等），
                # 结算完成后才会出现FLEET_SWITCH_CONFIRM或WITHDRAW按钮
                # 沉船D评价流程：OPTS_INFO_D → BATTLE_STATUS_D → EXP_INFO_D → OPTS_INFO_D(再次出现) → FLEET_SWITCH_CONFIRM
                if self.appear_then_click(OPTS_INFO_D, offset=(30, 30), interval=2):
                    continue
                if self.handle_battle_status():
                    continue
                if self.handle_exp_info():
                    continue
                if self.handle_get_ship():
                    continue
                if self.handle_get_items():
                    continue
                if self.handle_popup_confirm('combat_status'):
                    continue

                defeat_withdraw = self.config.Campaign_DefeatWithdraw
                if defeat_withdraw == 'withdraw_continue' or defeat_withdraw == 'withdraw_stop':
                    # 撤退后继续任务 / 撤退后关闭任务：
                    # 点击FLEET_SWITCH_CONFIRM仅关闭弹窗，不取消撤退
                    # 游戏在舰队战败后弹出FLEET_SWITCH_CONFIRM，点击后才能看到WITHDRAW按钮
                    if self.appear_then_click(FLEET_SWITCH_CONFIRM, offset=(30, 30)):
                        continue
                    if self.handle_popup_confirm('WITHDRAW'):
                        continue
                    if not self._wait_withdraw_stable(withdraw_stable_timer):
                        continue
                    self._withdraw = False
                    if defeat_withdraw == 'withdraw_stop':
                        # 撤退后关闭任务：连续3次战败才关闭任务
                        self._defeat_count += 1
                        logger.attr('战败计数', f'{self._defeat_count}/3')
                        if self._defeat_count >= 3:
                            # 连续3次战败，关闭任务
                            # withdraw()内部抛出CampaignEnd，
                            # 需要捕获后转换为ScriptEnd以终止任务
                            try:
                                self.withdraw()
                            except CampaignEnd:
                                raise ScriptEnd('DefeatWithdraw=withdraw_stop')
                        else:
                            # 未满3次，撤退后继续任务
                            self.withdraw()
                            break
                    else:
                        self.withdraw()
                    break
                elif defeat_withdraw == 'switch_fleet':
                    # 切换队伍继续出击：尝试切换另一队继续战斗
                    if self.appear_then_click(FLEET_SWITCH_CONFIRM, offset=(30, 30)):
                        self.fleet_alive_multiple = False
                        self._withdraw = False
                        continue
                    if not self._wait_withdraw_stable(withdraw_stable_timer):
                        continue

                    self._withdraw = False
                    if not self.fleet_alive_multiple:
                        self.withdraw()
                        break
                    else:
                        self._handle_fleet_switch_over()
                        continue

            # Combat status
            if self.handle_get_ship():
                continue
            if not self._withdraw and self.handle_auto_search_map_option():
                self._auto_search_status_confirm = False
                continue
            # bunch of popup handlers
            if self.handle_popup_confirm('AUTO_SEARCH_COMBAT_STATUS'):
                continue
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

            # 处理战斗结算界面——SABC评价在自动搜索中可能快速自动过渡，
            # 若截图恰好捕获到结算画面则点击推进并记录评价
            # D评价点击BATTLE_STATUS_D后，会出现OPTS_INFO_D沉船弹窗
            if self.handle_battle_status():
                continue
            if self.handle_exp_info():
                continue
            # 检测D评价（沉船）弹窗——这是沉船的确认性标志（二次确认）
            # 只有OPTS_INFO_D出现才确认是真正的D评价并扣心情
            # S/A/B/C转场误匹配BATTLE_STATUS_D不会出现OPTS_INFO_D，不会扣心情
            if self.appear(OPTS_INFO_D, offset=(30, 30)):
                logger.info('[自动搜索-结算] 检测到沉船弹窗，进入撤退处理')
                if self._auto_search_emotion_reduce and not self._shipwreck_emotion_reduced:
                    self.emotion.reduce(self._auto_search_fleet_index, shipwreck=True)
                    self._shipwreck_emotion_reduced = True
                self._withdraw = True
                continue

            # Handle low emotion combat
            # Combat status
            if self._auto_search_status_confirm:
                if not exp_info and self.handle_get_ship():
                    continue
                if self.handle_get_items():
                    continue
                if self.handle_battle_status():
                    continue
                if self.handle_popup_confirm('combat_status'):
                    continue
                if self.handle_exp_info():
                    exp_info = True
                    continue

    def auto_search_combat(self, emotion_reduce=None, fleet_index=1, battle=None):
        """
        Execute a combat.

        Note that fleet index == 1 is mob fleet, 2 is boss fleet.
        It's not the fleet index in fleet preparation or auto search setting.
        """
        emotion_reduce = emotion_reduce if emotion_reduce is not None else self.emotion.is_calculate

        self._auto_search_emotion_reduce = emotion_reduce
        self._auto_search_fleet_index = fleet_index
        self._shipwreck_emotion_reduced = False
        self.auto_search_combat_execute(emotion_reduce=emotion_reduce, fleet_index=fleet_index, battle=battle)
        self.auto_search_combat_status()

        logger.info('[自动搜索-战斗] 战斗结束')

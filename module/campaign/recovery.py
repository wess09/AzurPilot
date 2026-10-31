"""同一调度进程内的异常重启凭据与战役续接导航。"""

import copy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import monotonic

from module.base.timer import Timer
from module.config.deep import deep_get
from module.exception import (EmulatorNotRunningError, GameBugError,
                              GameNotRunningError, GameStuckError, GameTooManyClickError)
from module.logger import logger
from module.ui.page import Page, page_campaign, page_event, page_sp


CAMPAIGN_RESTART_ERRORS = (GameNotRunningError, GameStuckError, GameTooManyClickError,
                          GameBugError, EmulatorNotRunningError)
_recovery_owner = ContextVar('campaign_recovery_owner', default=None)


@contextmanager
def campaign_recovery_scope(script):
    """将战役断点交回当前调度器，不把回调或运行器写入用户配置。"""
    token = _recovery_owner.set(script)
    try:
        yield
    finally:
        _recovery_owner.reset(token)


def capture_campaign_recovery(runner, run_kwargs):
    """所有使用公共战役入口的任务都可以保存原实例与内层调用参数。"""
    owner = _recovery_owner.get()
    if owner is None:
        return
    previous = owner.__dict__.get('_resuming_campaign_recovery')
    recovery = CampaignRecovery.capture(runner, previous)
    if recovery is not None:
        recovery.run_kwargs = run_kwargs
    owner._campaign_recovery = recovery


def recovery_settings(config, task=None):
    """只比较影响原关卡执行与账本的设置，不记录或输出私人配置。"""
    task = task or config.task.command
    groups = ('Campaign', 'Fleet', 'Submarine', 'Emotion', 'VanguardEmotion', 'HpControl',
              'EnemyPriority', 'StopCondition', 'TaskBalancer', 'EventDaily', 'GemsFarming')
    return copy.deepcopy([
        config.config_name, task,
        *[deep_get(config.data, f'{task}.{group}') for group in groups],
        deep_get(config.data, 'Alas.Emulator'),
        deep_get(config.data, 'General.PublicEmotion'),
    ])


@dataclass
class CampaignRecovery:
    """仅由已中断战役产生，须实际完成 Restart 后才能消费。"""

    runner: object
    settings: list
    generation: int = 0
    attempts: int = 0
    restart_attempts: int = 0
    map_campaign: object = field(default=None, repr=False)
    run_kwargs: dict = field(default_factory=dict)
    ready: bool = False
    created: float = field(default_factory=monotonic)

    MAX_ATTEMPTS = 3
    MAX_AGE = 600

    @classmethod
    def capture(cls, runner, previous=None):
        campaign = runner.campaign
        # 自定义战役可能有额外副作用，没有明确断点时不尝试恢复。
        from module.campaign.campaign_base import CampaignBase
        from module.combat.auto_search_combat import AutoSearchCombat
        supported = (type(campaign).run is CampaignBase.run
                     and type(campaign).auto_search_execute_a_battle is CampaignBase.auto_search_execute_a_battle
                     and type(campaign).auto_search_combat is AutoSearchCombat.auto_search_combat)
        map_folder = runner.folder
        if not (supported and (map_folder in ('campaign_main', 'campaign_hard')
                               or map_folder.startswith('event_'))
                and campaign.config.Campaign_ContinueAfterRestart
                and campaign.config.Campaign_UseClearMode and campaign.config.Campaign_UseAutoSearch
                and campaign.map_is_clear_mode and campaign.map_is_auto_search
                and campaign.__dict__.get('_recovery_map_active', False)
                and not campaign.__dict__.get('_restart_stop_requested', False)
                and not campaign.AUTO_SEARCH_WITHDRAW
                and not campaign.config.MAP_IS_ONE_TIME_STAGE):
            return None
        generation = campaign.__dict__.get('_recovery_map_generation', 0)
        same_map = (previous is not None and previous.map_campaign is campaign
                    and previous.generation == generation)
        attempts = previous.attempts if same_map else 0
        restart_attempts = previous.restart_attempts if same_map else 0
        if attempts >= cls.MAX_ATTEMPTS or restart_attempts >= cls.MAX_ATTEMPTS:
            logger.warning('[战役续接] 同一关卡恢复次数已达上限，回退原有恢复流程')
            return None
        logger.info('[战役续接] 检测到异常中断，保留原关卡，等待 Restart 后恢复地图自律')
        return cls(runner, recovery_settings(campaign.config), generation=generation,
                   attempts=attempts, restart_attempts=restart_attempts, map_campaign=campaign)

    def matches(self, config, task=None):
        enabled = task is not None or (config.Campaign_ContinueAfterRestart
                                      and config.Campaign_UseClearMode and config.Campaign_UseAutoSearch)
        return (enabled and monotonic() - self.created <= self.MAX_AGE
                and recovery_settings(config, task=task) == self.settings)

    def bind_device(self, device):
        self.runner.device = device
        self.runner.campaign.device = device

    def find_state(self):
        """沿已有 Page 导航图找到保留海域；不选关、不切难度、不处理撤退。

        Pages:
            in: 登录后的主界面或原地图
            out: 已识别的原地图状态，或确认选关页后返回 None
        """
        campaign = self.runner.campaign
        destination = getattr(campaign, 'ui_current', None)
        if destination not in (page_campaign, page_event, page_sp):
            destination = page_campaign if self.runner.folder == 'campaign_main' else page_event
        timeout = Timer(30, count=60).start()
        outside = Timer(3, count=6).start()
        Page.init_connection(destination)
        try:
            for _ in campaign.loop():
                state = campaign.auto_search_recovery_state()
                if state is not None:
                    logger.attr('战役续接-当前状态', state)
                    return state
                if timeout.reached():
                    raise GameStuckError('[战役续接] 无法确认原关卡，导航超时')
                if campaign.is_in_stage():
                    if outside.reached():
                        logger.info('[战役续接] 已回到选关页，没有可确认的未完成关卡')
                        return None
                    continue
                outside.reset()
                # 只点击正向识别页面上通往原选关页的现有导航按钮。
                for page in Page.iter_pages():
                    if page.parent is None or page.check_button is None:
                        continue
                    if campaign.appear(page.check_button, offset=(20, 20), interval=3):
                        campaign.device.click(page.links[page.parent])
                        break
                else:
                    if campaign.handle_story_skip():
                        continue
                    if campaign.handle_combat_low_emotion():
                        continue
        finally:
            Page.clear_connection()

    def prepare(self, config, device):
        """重新读取原配置并保留地图运行时字段，防止使用重启前的磁盘快照写回。"""
        self.attempts += 1
        self.ready = False
        self.bind_device(device)
        self.runner.config.update()
        self.runner.campaign.config.update()
        if not self.matches(self.runner.campaign.config):
            logger.warning('[战役续接] 重新读盘后原任务设置或账本已改变，放弃续接')
            self.runner.campaign._recovery_map_active = False
            return False
        # 心情读取当前持久化账本；恢复后每场出击仍按普通战斗入口正常扣减。
        campaign = self.runner.campaign
        campaign.emotion = type(campaign.emotion)(campaign.config)
        campaign.emotion.map_is_2x_book = campaign.map_is_2x_book
        logger.info(f'[战役续接] 尝试恢复原任务 {config.task.command}，第 {self.attempts}/{self.MAX_ATTEMPTS} 次')
        state = self.find_state()
        if state is None:
            campaign._recovery_map_active = False
            return False
        return campaign.prepare_auto_search_recovery(state)

    def resume(self, config, device):
        """恢复一次内层出击，外层每日进度和紧急委托换船仍由原任务处理。"""
        try:
            self.runner._resume_map = self.prepare(config, device)
        except CAMPAIGN_RESTART_ERRORS:
            capture_campaign_recovery(self.runner, self.run_kwargs)
            raise
        self.runner._resume_campaign_run = True
        self.runner._resume_campaign_kwargs = self.run_kwargs
        try:
            return self.runner.run(**self.run_kwargs)
        finally:
            self.runner.__dict__.pop('_resume_campaign_run', None)
            self.runner.__dict__.pop('_resume_campaign_kwargs', None)

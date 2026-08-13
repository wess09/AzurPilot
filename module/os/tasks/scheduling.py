"""
OpsiScheduling - 智能调度+模块

智能调度+功能，用于在侵蚀1练级和耄耋相接/其他黄币补充任务之间按代理模式调度。

功能说明:
    1. 黄币检查与任务代理 - 当黄币低于保留值时，代理执行黄币补充任务
    2. 行动力阈值推送通知 - 当行动力跨越阈值时发送推送通知
    3. 最低行动力保留检查 - 检查行动力是否低于最低保留值
    4. 任务智能调度+ - 由 OpsiScheduling 统一代理执行子任务

任务层级:
    - OpsiScheduling 是和 OpsiHazard1Leveling、OpsiMeowfficerFarming 相同层级的调度器
    - 它负责协调这些任务的执行顺序，并以子任务上下文代理执行

配置项:
    - Scheduler.Enable: 任务启用开关（启用此任务即启用智能调度+功能）
    - OperationCoinsPreserve: 智能调度+时侵蚀1保留的黄币阀值（优先级高于原配置）
    - UseSmartSchedulingOperationCoinsPreserve: 开启时使用黄币目标调度，关闭时使用体力调度
    - OperationCoinsReturnThreshold: 黄币目标调度回到侵蚀1前需要高于保留值的缓冲数量
    - ActionPointPreserve: 智能调度+时保留的行动力阀值（同时作用于所有任务）
    - ActionPointNotifyLevels: 行动力阈值列表，用于推送通知
此模块包含:
    - OpsiScheduling: 智能调度+任务主类
    - CoinTaskMixin: 黄币补充任务的通用 Mixin 类（供其他任务继承使用）
"""
import re
from datetime import timedelta

from module.config.config import Function, name_to_function
from module.config.deep import deep_get
from module.config.time_source import now as current_time
from module.config.utils import get_os_reset_remain

from module.logger import logger
from module.exception import GameStuckError, GameNotRunningError
from module.os.map import OSMap
from module.os_handler.action_point import ActionPointLimit


class CoinTaskMixin:
    """
    黄币补充任务的通用 Mixin 类。
    
    提供黄币补充任务（OpsiObscure、OpsiAbyssal、OpsiStronghold、OpsiMeowfficerFarming）
    所需的通用功能，包括配置读取、通知与无内容标记。
    
    使用方法:
        class OpsiMeowfficerFarming(CoinTaskMixin, OSMap):
            ...
    """
    
    # 任务名称映射（用于通知显示）
    TASK_NAMES = {
        'OpsiMeowfficerFarming': '耄耋相接',
        'OpsiObscure': '隐秘海域',
        'OpsiAbyssal': '深渊坐标',
        'OpsiStronghold': '塞壬要塞'
    }
    
    # 配置路径常量
    CONFIG_PATH_CL1_PRESERVE = 'OpsiHazard1Leveling.OpsiHazard1Leveling.OperationCoinsPreserve'
    # 四个独立任务开关的配置路径
    CONFIG_PATH_ENABLE_MEOWFFICER = 'OpsiScheduling.OpsiScheduling.EnableMeowfficerFarming'
    CONFIG_PATH_ENABLE_OBSCURE = 'OpsiScheduling.OpsiScheduling.EnableObscure'
    CONFIG_PATH_ENABLE_ABYSSAL = 'OpsiScheduling.OpsiScheduling.EnableAbyssal'
    CONFIG_PATH_ENABLE_STRONGHOLD = 'OpsiScheduling.OpsiScheduling.EnableStronghold'
    # 智能调度+新增配置路径
    CONFIG_PATH_USE_SMART_CL1_PRESERVE = 'OpsiScheduling.OpsiScheduling.UseSmartSchedulingOperationCoinsPreserve'
    CONFIG_PATH_SMART_CL1_PRESERVE = 'OpsiScheduling.OpsiScheduling.OperationCoinsPreserve'
    CONFIG_PATH_SMART_AP_PRESERVE = 'OpsiScheduling.OpsiScheduling.ActionPointPreserve'
    CONFIG_PATH_SMART_COIN_RETURN_THRESHOLD = 'OpsiScheduling.OpsiScheduling.OperationCoinsReturnThreshold'
    CONFIG_PATH_SMART_STATE = 'OpsiScheduling.Storage.Storage'
    # 月末清理行动力配置路径
    CONFIG_PATH_MONTH_END_CLEANUP_ENABLE = 'OpsiScheduling.OpsiScheduling.MonthEndActionPointCleanupEnable'
    CONFIG_PATH_MONTH_END_CLEANUP_DAYS = 'OpsiScheduling.OpsiScheduling.MonthEndActionPointCleanupDays'
    CONFIG_PATH_MONTH_END_AP_PRESERVE = 'OpsiScheduling.OpsiScheduling.MonthEndActionPointPreserve'
    CONFIG_PATH_MONTH_END_SHOP_PURCHASE = 'OpsiScheduling.OpsiScheduling.MonthEndShopPurchase'
    STATE_KEY_COIN_REPLENISH_START = 'CoinReplenishStart'
    STATE_KEY_AP_REPLENISH_ACTIVE = 'ApReplenishActive'
    STATE_KEY_SCHEDULING_MODE = 'SchedulingMode'
    STATE_KEY_MONTH_END_CLEANUP_FIRST_RUN = 'MonthEndCleanupFirstRun'
    SCHEDULING_MODE_COIN_TARGET = 'coin_target'
    SCHEDULING_MODE_ACTION_POINT = 'action_point'
    SCHEDULING_MODE_MONTH_END_CLEANUP = 'month_end_cleanup'
    RUNTIME_ATTR_LAST_NOTIFIED_COIN_TASK = '_smart_scheduling_last_notified_coin_task'
    RUNTIME_ATTR_LAST_COIN_TASK_NOTIFICATION_ATTEMPT = '_smart_scheduling_last_coin_task_notification_attempt'
    RUNTIME_ATTR_PREVENT_OVERFLOW_DELAY = '_prevent_action_point_overflow_delay'
    # 各任务的配置路径常量（集中管理，避免硬编码）
    CONFIG_PATH_MEOW_AP_PRESERVE = 'OpsiMeowfficerFarming.OpsiMeowfficerFarming.ActionPointPreserve'
    CONFIG_PATH_CL1_MIN_AP_RESERVE = 'OpsiHazard1Leveling.OpsiHazard1Leveling.MinimumActionPointReserve'
    
    # 耄耋相接任务名称
    TASK_NAME_MEOWFFICER_FARMING = 'OpsiMeowfficerFarming'
    TASK_NAME_HAZARD1_LEVELING = 'OpsiHazard1Leveling'
    TASK_NAME_SCHEDULING = 'OpsiScheduling'
    TASK_NAME_OBSCURE = 'OpsiObscure'
    TASK_NAME_ABYSSAL = 'OpsiAbyssal'
    TASK_NAME_STRONGHOLD = 'OpsiStronghold'
    AP_NOTIFY_MIN_INTERVAL_MINUTES = 30

    def _config_enabled(self, keys, default=False):
        """
        严格读取布尔配置，兼容 WebUI checkbox 历史值 [] / [True]。
        """
        value = self.config.cross_get(keys=keys, default=default)
        if isinstance(value, list):
            return any(bool(item) for item in value)
        return value is True

    def is_running_smart_scheduling_task(self):
        """判断当前是否由 OpsiScheduling 代执行子任务。"""
        return bool(
            getattr(self, '_smart_scheduling_context', False)
            or getattr(self.config, '_smart_scheduling_context', False)
        )

    def is_running_prevent_action_point_overflow_task(self):
        """判断当前是否由防止行动力溢出任务代执行子任务。"""
        return bool(
            getattr(self, '_prevent_action_point_overflow_context', False)
            or getattr(self.config, '_prevent_action_point_overflow_context', False)
        )

    def delay_opsi_active_task(self, *args, **kwargs):
        """
        延迟当前实际执行的大世界子任务。

        当 OpsiScheduling 代执行子任务时，将子任务延迟映射到智能调度+；
        防止行动力溢出代跑时由防止行动力溢出任务统一更新下次运行时间。
        """
        if self.is_running_smart_scheduling_task():
            self._clear_coin_task_notification_state()
            if self.is_running_prevent_action_point_overflow_task():
                kwargs.pop('task', None)
                setattr(
                    self,
                    self.RUNTIME_ATTR_PREVENT_OVERFLOW_DELAY,
                    (args, kwargs),
                )
                logger.info('[大世界-智能调度+] 已将子任务延迟请求交给防止行动力溢出任务')
                return

            kwargs.pop('task', None)
            if kwargs.get('server_update') is True:
                kwargs['server_update'] = self.config.cross_get(
                    keys=f'{self.TASK_NAME_SCHEDULING}.Scheduler.ServerUpdate',
                    default='00:00',
                )
            logger.info('[大世界-智能调度+] 将子任务延迟映射到智能调度+任务')
            self.config.task_delay(
                *args,
                task=self.TASK_NAME_SCHEDULING,
                **kwargs,
            )
            return

        task = kwargs.pop('task', None)
        if task is None:
            task = self._get_current_coin_task_name()
        self.config.task_delay(*args, task=task, **kwargs)

    def _is_direct_prevent_overflow_coin_task(self):
        """判断防止行动力溢出任务是否正在直接代跑黄币补充任务。"""
        if not self.is_running_prevent_action_point_overflow_task():
            return False
        owner = getattr(self.config, '_task_switch_owner', None)
        return getattr(owner, 'command', None) == 'OpsiPreventActionPointOverflow'

    def _clear_coin_task_notification_state(self):
        """清理本轮补币阶段的通知成功和尝试状态。"""
        for key in (
            self.RUNTIME_ATTR_LAST_NOTIFIED_COIN_TASK,
            self.RUNTIME_ATTR_LAST_COIN_TASK_NOTIFICATION_ATTEMPT,
        ):
            if hasattr(self.config, key):
                delattr(self.config, key)

    def _delay_smart_scheduling_to_server_update(self, reason):
        """将实际运行智能调度+的任务延迟到服务器刷新。"""
        self._clear_coin_task_notification_state()
        if self.is_running_prevent_action_point_overflow_task():
            setattr(
                self,
                self.RUNTIME_ATTR_PREVENT_OVERFLOW_DELAY,
                ((), {'server_update': True}),
            )
            logger.info(f'[大世界-智能调度+] {reason}，防止行动力溢出任务延迟到服务器刷新')
            return

        logger.info(f'[大世界-智能调度+] {reason}，智能调度+延迟到服务器刷新')
        self.config.task_delay(
            server_update=self.config.cross_get(
                keys=f'{self.TASK_NAME_SCHEDULING}.Scheduler.ServerUpdate',
                default='00:00',
            ),
            task=self.TASK_NAME_SCHEDULING,
        )

    def _delay_smart_scheduling_with_minutes(self, reason, minutes):
        """
        将实际运行智能调度+的任务延迟指定分钟数。

        Args:
            reason (str): 延迟原因（用于日志）。
            minutes (int): 延迟的分钟数。
        """
        self._clear_coin_task_notification_state()
        if self.is_running_prevent_action_point_overflow_task():
            setattr(
                self,
                self.RUNTIME_ATTR_PREVENT_OVERFLOW_DELAY,
                ((), {'minutes': minutes}),
            )
            logger.info(
                f'[大世界-智能调度+] {reason}，防止行动力溢出任务延迟 {minutes} 分钟'
            )
            return

        logger.info(f'[大世界-智能调度+] {reason}，智能调度+延迟 {minutes} 分钟')
        self.config.task_delay(
            minute=minutes,
            task=self.TASK_NAME_SCHEDULING,
        )
    
    # ==================== 推送通知相关方法 ====================
    
    def notify_push(self, title, content):
        """
        发送推送通知（智能调度+功能）
        
        Args:
            title (str): 通知标题（会自动添加实例名称前缀）
            content (str): 通知内容
            
        Notes:
            - 仅在启用智能调度+时生效
            - 启动器推送和 OnePush 推送分别由各自配置控制
            - 标题会自动格式化为 "[AzurPilot <实例名>] 原标题" 的形式

        Returns:
            bool: True 表示推送成功发送，False 表示未发送或发送失败
        """
        # 检查是否启用智能调度+
        if not self.is_smart_scheduling_enabled():
            return False

        launcher_enabled = getattr(self.config, 'OpsiGeneral_LauncherPush', True)
        onepush_enabled = bool(getattr(self.config, 'OpsiGeneral_NotifyOpsiMail', False))
        if not launcher_enabled and not onepush_enabled:
            return False

        # 获取实例名称并格式化标题
        instance_name = getattr(self.config, 'config_name', 'AzurPilot')
        if title.startswith('[AzurPilot]'):
            formatted_title = f"[AzurPilot <{instance_name}>]{title[len('[AzurPilot]'):]}"
        elif title.startswith('[AzurPilot info]'):
            formatted_title = f"[AzurPilot <{instance_name}>]{title[len('[AzurPilot info]'):]}"
        elif title.startswith('[Alas]'):
            formatted_title = f"[AzurPilot <{instance_name}>]{title[len('[Alas]'):]}"
        elif title.startswith('[Alas info]'):
            formatted_title = f"[AzurPilot <{instance_name}>]{title[len('[Alas info]'):]}"
        else:
            formatted_title = f"[AzurPilot <{instance_name}>] {title}"

        webui_success = False
        if launcher_enabled:
            try:
                from module.notify import notify_webui
                launcher_title, launcher_content = self._format_launcher_notification(
                    instance_name=instance_name,
                    title=title,
                    content=content
                )
                webui_success = notify_webui(
                    instance_name,
                    title=launcher_title,
                    content=launcher_content
                )
                if webui_success:
                    logger.info(f"[大世界-智能调度+] 启动器推送通知成功: {launcher_title}")
            except Exception as e:
                logger.error(f"[大世界-智能调度+] 启动器推送通知异常: {e}")

        if not onepush_enabled:
            return webui_success

        # 检查是否配置了 OnePush。启动器推送不依赖 OnePush 配置。
        push_config = (
            self.config.OpsiGeneral_OpsiOnePushConfig
            if self.config.OpsiGeneral_IndependentPush
            else self.config.Error_OnePushConfig
        )
        if not self._is_push_config_valid(push_config):
            logger.warning("[大世界-智能调度+] 推送配置未设置或 provider 为 null，跳过 OnePush 推送。请在 AzurPilot 设置 -> 错误处理 -> OnePush 配置中设置有效的推送渠道。")
            return webui_success

        try:
            from module.notify import handle_notify as notify_handle_notify
            success = notify_handle_notify(
                push_config,
                title=formatted_title,
                content=content
            )
            if success:
                logger.info(f"[大世界-智能调度+] 推送通知成功: {formatted_title}")
            else:
                logger.warning(f"[大世界-智能调度+] 推送通知失败: {formatted_title}")
            return bool(success or webui_success)
        except Exception as e:
            logger.error(f"[大世界-智能调度+] 推送通知异常: {e}")
            return webui_success

    def _format_launcher_notification(self, instance_name, title, content):
        """
        启动器通知走更轻一点的本地文案，OnePush 仍保留原始标题和正文。
        """
        plain_title = title.strip()
        for prefix in ('[AzurPilot info]', '[AzurPilot]', '[Alas info]', '[Alas]'):
            if plain_title.startswith(prefix):
                plain_title = plain_title[len(prefix):].strip()
                break
        if not plain_title:
            plain_title = '大世界有新消息'

        if '行动力出现变化' in plain_title:
            launcher_title = f"{instance_name} 行动力动了一下喵~"
        elif '行动力不足' in plain_title or '行动力低于最低保留' in plain_title:
            launcher_title = f"{instance_name} 大世界行动力不够喵~"
        elif '黄币与行动力双重不足' in plain_title:
            launcher_title = f"{instance_name} 大世界补给和行动力都告急喵~"
        elif '代理执行' in plain_title:
            launcher_title = f"{instance_name} 大世界要换个活干喵~"
        elif '黄币充足' in plain_title or '凭证' in plain_title:
            launcher_title = f"{instance_name} 大世界补给有消息喵~"
        elif '检测' in plain_title or '报告' in plain_title or '检查' in plain_title:
            launcher_title = f"{instance_name} 大世界检查报告来啦喵~"
        else:
            launcher_title = f"{instance_name} 的大世界小铃铛响了喵~"

        launcher_content = f"{plain_title}\n{content}".strip()
        if not launcher_content.endswith(('喵', '喵~', '。', '！', '~')):
            launcher_content = f"{launcher_content} 喵~"
        return launcher_title, launcher_content
    
    def _is_push_config_valid(self, push_config):
        """
        检查推送配置是否有效
        
        Args:
            push_config: 推送配置字符串或对象
            
        Returns:
            bool: True 表示配置有效，False 表示无效
        """
        if not push_config:
            return False
        
        # 尝试解析为结构化数据
        if isinstance(push_config, dict):
            provider = push_config.get('provider')
            return provider is not None and provider.lower() != 'null'
        
        # 回退到字符串匹配
        if isinstance(push_config, str):
            push_config_lower = push_config.lower()
            if 'provider:null' in push_config_lower or 'provider: null' in push_config_lower:
                return False
            if 'provider' in push_config_lower:
                if re.search(r'provider\s*[:=]\s*null', push_config_lower):
                    return False
        
        return True

    def _can_send_ap_notification(self, key):
        """
        限制体力相关推送尝试的最小间隔，避免失败时高频重试。
        """
        now = current_time()
        attempt_key = f'{key}_attempt'
        last_notify = getattr(self.config, attempt_key, None) or getattr(self.config, key, None)
        min_interval = timedelta(minutes=self.AP_NOTIFY_MIN_INTERVAL_MINUTES)
        if last_notify and now - last_notify < min_interval:
            logger.info(
                f"Skip AP notification ({key}, last: {last_notify}, wait {self.AP_NOTIFY_MIN_INTERVAL_MINUTES}m)"
            )
            return False
        setattr(self.config, attempt_key, now)
        return True

    def _mark_ap_notification_sent(self, key):
        """仅在至少一个通知渠道发送成功后记录成功时间。"""
        setattr(self.config, key, current_time())
    
    def check_and_notify_action_point_threshold(self):
        """
        发送行动力变化推送通知。
        需要类中包含 _action_point_total 属性。
        """
        if not hasattr(self, '_action_point_total'):
            return
            
        total_ap = self._action_point_total

        instance_name = getattr(self.config, 'config_name', 'default')
        # AP 快照由各任务模块自行管理（如 _record_ap_and_coins），此处仅保留推送逻辑。
        previous_ap = None
        try:
            from module.statistics.cl1_database import db as cl1_db
            last_notification = cl1_db.get_last_ap_notification(instance_name)
            if isinstance(last_notification, dict):
                previous_ap = last_notification.get('ap')
        except Exception:
            logger.exception('Failed to load last AP notification')

        content = f"总行动力: {total_ap}"
        if previous_ap is not None:
            ap_delta = total_ap - previous_ap
            if ap_delta == 0:
                logger.info('[大世界-智能调度+] 行动力未发生变化，跳过推送通知')
                return
            if ap_delta > 0:
                content = f"总行动力: {total_ap} 上涨{ap_delta}行动力"
            else:
                content = f"总行动力: {total_ap} 下跌{abs(ap_delta)}行动力"

        if not self._can_send_ap_notification('_last_ap_notification_time'):
            return

        pushed = self.notify_push(
            title="[AzurPilot] 行动力出现变化！",
            content=content
        )
        if pushed:
            self._mark_ap_notification_sent('_last_ap_notification_time')
            try:
                from module.statistics.cl1_database import db as cl1_db
                cl1_db.async_set_last_ap_notification(instance_name, total_ap)
            except Exception:
                logger.exception('Failed to save last AP notification')

    
    def _get_smart_scheduling_operation_coins_preserve(self):
        """
        获取智能调度+模式下的侵蚀1黄币保留值

        Returns:
            int: 保留的黄币数量
        """
        # 检查是否启用智能调度+黄币保留配置
        use_smart_preserve = self._is_coin_target_scheduling_enabled()
        
        if not use_smart_preserve:
            # 开关未开启，回退到侵蚀1原配置
            cl1_preserve_original = self.config.cross_get(
                keys=self.CONFIG_PATH_CL1_PRESERVE
            )
            # 保证返回 int 以免后续比较报错
            if cl1_preserve_original is None:
                cl1_preserve_original = 0
            logger.info(f'[大世界-智能调度+] 黄币保留使用原配置: {cl1_preserve_original} (黄币目标调度未启用)')
            return cl1_preserve_original
        else:
            # 开关开启，使用智能调度+自己的配置，允许为 0
            preserve = self.config.cross_get(
                keys=self.CONFIG_PATH_SMART_CL1_PRESERVE
            )
            if preserve is None:
                preserve = 0
            logger.info(f'[大世界-智能调度+] 黄币保留使用智能调度+配置: {preserve} (开关已开启)')
            return preserve
    
    def _get_smart_scheduling_action_point_preserve(self):
        """
        获取智能调度+模式下的行动力保留“覆盖值”。

        注意：此处不做回退。
        - 返回值 > 0：表示启用智能调度+覆盖值（由调用方决定覆盖哪个任务的阀值）
        - 返回值 == 0：表示不覆盖，调用方应回退到各自任务的原配置

        Returns:
            int: 智能调度+行动力保留覆盖值（0 表示不覆盖）
        """
        preserve = self.config.cross_get(
            keys=self.CONFIG_PATH_SMART_AP_PRESERVE
        )
        return preserve or 0

    def _is_coin_target_scheduling_enabled(self):
        """判断是否启用黄币目标调度。关闭时使用体力调度。"""
        return self._config_enabled(
            keys=self.CONFIG_PATH_USE_SMART_CL1_PRESERVE
        )

    def _get_coin_task_action_point_preserve(self):
        """获取智能调度+用于启动黄币补充任务的行动力阈值。"""
        smart_ap_preserve = self._get_smart_scheduling_action_point_preserve()
        if smart_ap_preserve > 0:
            return smart_ap_preserve
        return self.config.cross_get(
            keys=self.CONFIG_PATH_MEOW_AP_PRESERVE
        ) or 1000

    def _get_smart_scheduling_operation_coins_return_threshold(self):
        """
        获取智能调度+补黄币阶段的回补增量。

        进入补黄币阶段后，黄币需要达到“侵蚀 1 保留值 + 此阈值”，才允许回到侵蚀 1。
        """
        threshold = self.config.cross_get(
            keys=self.CONFIG_PATH_SMART_COIN_RETURN_THRESHOLD,
            default=0,
        )
        try:
            threshold = int(threshold or 0)
        except (TypeError, ValueError):
            logger.warning(f'[大世界-智能调度+] 智能调度+黄币回补阈值无效: {threshold}，使用 0')
            threshold = 0
        return max(threshold, 0)

    def _get_smart_scheduling_state(self):
        """读取智能调度+持久化运行状态。"""
        state = self.config.cross_get(
            keys=self.CONFIG_PATH_SMART_STATE,
            default={},
        )
        if not isinstance(state, dict):
            return {}
        return dict(state)

    def _get_smart_scheduling_state_value(self, key, default=None):
        """读取单个智能调度+运行状态。"""
        return self._get_smart_scheduling_state().get(key, default)

    def _set_smart_scheduling_state_value(self, key, value):
        """写入单个智能调度+运行状态并立即持久化。"""
        state = self._get_smart_scheduling_state()
        if state.get(key) == value:
            return
        state[key] = value
        self.config.modified[self.CONFIG_PATH_SMART_STATE] = state
        self.config.save()

    def _clear_smart_scheduling_state_value(self, key):
        """清理单个智能调度+运行状态并立即持久化。"""
        state = self._get_smart_scheduling_state()
        if key not in state:
            return
        state.pop(key, None)
        self.config.modified[self.CONFIG_PATH_SMART_STATE] = state
        self.config.save()

    def _get_coin_replenish_target(self, yellow_coins, cl1_preserve):
        """
        获取本轮补黄币目标值。

        目标值与模拟器保持一致：侵蚀 1 保留值 + 回补阈值。
        """
        start_coins = self._get_smart_scheduling_state_value(
            self.STATE_KEY_COIN_REPLENISH_START
        )
        if start_coins is None or yellow_coins < start_coins:
            start_coins = yellow_coins
            self._set_smart_scheduling_state_value(
                self.STATE_KEY_COIN_REPLENISH_START,
                start_coins,
            )

        return_threshold = self._get_smart_scheduling_operation_coins_return_threshold()
        target = cl1_preserve + return_threshold
        return target, start_coins, return_threshold

    def _clear_coin_replenish_target(self):
        """清理本轮补黄币状态。"""
        self._clear_smart_scheduling_state_value(
            self.STATE_KEY_COIN_REPLENISH_START
        )

    def _is_coin_replenish_active(self):
        """判断当前是否处于补黄币阶段。"""
        return self._get_smart_scheduling_state_value(
            self.STATE_KEY_COIN_REPLENISH_START
        ) is not None

    def _set_ap_replenish_active(self):
        """标记体力调度补黄币阶段已开始。"""
        self._set_smart_scheduling_state_value(
            self.STATE_KEY_AP_REPLENISH_ACTIVE,
            True,
        )

    def _clear_ap_replenish_active(self):
        """清理体力调度补黄币状态。"""
        self._clear_smart_scheduling_state_value(
            self.STATE_KEY_AP_REPLENISH_ACTIVE
        )

    def _is_ap_replenish_active(self):
        """判断当前是否处于体力调度补黄币阶段。"""
        return bool(
            self._get_smart_scheduling_state_value(
                self.STATE_KEY_AP_REPLENISH_ACTIVE,
                False,
            )
        )

    def _sync_smart_scheduling_mode_state(self, coin_target_scheduling):
        """同步调度模式，并清理另一模式遗留的补黄币状态。"""
        current_mode = (
            self.SCHEDULING_MODE_COIN_TARGET
            if coin_target_scheduling
            else self.SCHEDULING_MODE_ACTION_POINT
        )
        state = self._get_smart_scheduling_state()
        previous_mode = state.get(self.STATE_KEY_SCHEDULING_MODE)
        if previous_mode == current_mode:
            return

        if previous_mode is None:
            if coin_target_scheduling:
                state.pop(self.STATE_KEY_AP_REPLENISH_ACTIVE, None)
            else:
                state.pop(self.STATE_KEY_COIN_REPLENISH_START, None)
        else:
            state.pop(self.STATE_KEY_COIN_REPLENISH_START, None)
            state.pop(self.STATE_KEY_AP_REPLENISH_ACTIVE, None)
            self._clear_coin_task_notification_state()
            logger.info(
                f'[大世界-智能调度+] 调度模式由 {previous_mode} 切换为 {current_mode}，'
                '已清理旧模式运行状态'
            )

        state[self.STATE_KEY_SCHEDULING_MODE] = current_mode
        self.config.modified[self.CONFIG_PATH_SMART_STATE] = state
        self.config.save()

    def _get_effective_cl1_ap_preserve(self):
        """
        获取智能调度+下侵蚀 1 使用的行动力保留值。
        """
        preserve = self.config.cross_get(
            keys=self.CONFIG_PATH_CL1_MIN_AP_RESERVE,
            default=200,
        )
        return preserve

    def _get_current_coin_task_name(self):
        """
        获取当前任务名称（用于调度范围检查）
        
        Returns:
            str: 任务命令名称（如 'OpsiObscure'），如果不可用则返回类名
        """
        if hasattr(self.config, 'task') and hasattr(self.config.task, 'command') and self.config.task.command:
            return self.config.task.command
        return self.__class__.__name__
    
    def _get_enabled_coin_tasks(self):
        """
        获取智能调度+中启用的黄币补充任务列表，并按 TaskPriority 排序。
        
        Returns:
            list: 启用的任务名称列表
        """
        enabled_tasks = []
        
        # 检查每个任务的独立开关
        task_config_map = {
            'OpsiStronghold': self.CONFIG_PATH_ENABLE_STRONGHOLD,
            'OpsiObscure': self.CONFIG_PATH_ENABLE_OBSCURE,
            'OpsiAbyssal': self.CONFIG_PATH_ENABLE_ABYSSAL,
            'OpsiMeowfficerFarming': self.CONFIG_PATH_ENABLE_MEOWFFICER,
        }
        
        for task_name, config_path in task_config_map.items():
            if self._config_enabled(keys=config_path):
                enabled_tasks.append(task_name)

        # 按照 OpsiScheduling_TaskPriority 配置的顺序进行过滤和排序
        try:
            priority_str = self.config.OpsiScheduling_TaskPriority
            if priority_str:
                priorities = [p.strip() for p in priority_str.split('>') if p.strip()]
                def sort_key(task):
                    try:
                        return priorities.index(task)
                    except ValueError:
                        return len(priorities)
                enabled_tasks = sorted(enabled_tasks, key=sort_key)
        except Exception as e:
            logger.warning(f'[大世界-智能调度+] 按优先级排序大世界黄币补充任务失败: {e}，使用默认顺序')
        
        return enabled_tasks

    def _handle_coin_task_no_content(self, task_display_name, log_message):
        """
        处理黄币补充任务没有可执行内容的情况。
        """
        logger.info(f'[大世界-智能调度+] {log_message}，准备结束当前任务')
        task_name = self._get_current_coin_task_name()
        logger.info(f'[大世界-智能调度+] 处理任务: {task_name}')

        if self.is_running_smart_scheduling_task():
            if '没有更多' not in log_message:
                self._smart_scheduling_no_content_task = task_name
            logger.info(f'[大世界-智能调度+] 智能调度+代理执行中，{task_display_name}无可执行内容')
            if self._is_direct_prevent_overflow_coin_task():
                self.delay_opsi_active_task(server_update=True)
                self.config.task_stop()
            return True

        if self.is_smart_scheduling_enabled():
            logger.info(f'[大世界-智能调度+] 智能调度+已启用，{task_display_name}无可执行内容')
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        with self.config.multi_set():
            try:
                from module.config.utils import get_os_reset_remain
            except ImportError:
                get_os_reset_remain = None

            if task_name in ('OpsiObscure', 'OpsiAbyssal') and get_os_reset_remain is not None:
                remain = get_os_reset_remain()
                if remain == 0:
                    logger.info(f'[大世界-智能调度+] {task_name} 没有更多可执行内容，距离大世界重置不足1天，延迟2.5小时后再运行')
                    self.config.task_delay(minute=150, server_update=True)
                else:
                    logger.info(f'[大世界-智能调度+] {task_name} 没有更多可执行内容，延迟到下次服务器刷新后再运行')
                    self.config.task_delay(server_update=True)
            else:
                logger.info(f'[大世界-智能调度+] {task_name} 没有更多可执行内容，延迟到下次服务器刷新后再运行')
                self.config.task_delay(server_update=True)
        
        self.config.task_stop()
        return True


class OpsiScheduling(CoinTaskMixin, OSMap):
    """
    智能调度+任务主类
    
    负责协调大世界（Operation Siren）中的各项任务调度，
    包括侵蚀1练级、耄耋相接、隐秘海域、深渊坐标、塞壬要塞等。
    
    主要功能:
        1. 黄币管理 - 当黄币不足时代理执行补充任务
        2. 行动力监控 - 监控行动力并发送阈值通知
        3. 任务协调 - 统一决定并代理执行子任务
    """

    def _make_opsi_task_function(self, task_name):
        """从当前配置数据构造临时代跑任务对象。"""
        data = deep_get(self.config.data, keys=task_name, default=None)
        if isinstance(data, dict):
            task = Function(data)
            if task.command != "Unknown":
                return task
        return name_to_function(task_name)

    def _run_with_opsi_task_context(self, task_name, func, *args, **kwargs):
        """
        以指定大世界子任务身份执行逻辑，保证统计和配置读取仍按子任务归类。
        """
        previous_task = self.config.task
        previous_bind = getattr(self.config, '_bind_task_override', None)
        previous_context = getattr(self, '_smart_scheduling_context', None)
        previous_config_context = getattr(self.config, '_smart_scheduling_context', None)
        previous_disable_task_switch = getattr(self.config, '_disable_task_switch', False)
        previous_task_switch_owner = getattr(self.config, '_task_switch_owner', None)
        self._smart_scheduling_context = True
        self.config._smart_scheduling_context = True
        self.config._disable_task_switch = task_name not in (
            self.TASK_NAME_HAZARD1_LEVELING,
            self.TASK_NAME_MEOWFFICER_FARMING,
        )
        self.config._task_switch_owner = previous_task
        self.config.task = self._make_opsi_task_function(task_name)
        self.config._bind_task_override = task_name
        self.config.bind(task_name)
        try:
            return func(*args, **kwargs)
        except (GameStuckError, GameNotRunningError):
            # 记录卡死/闪退时正在代跑的子任务；嵌套代跑时保留最内层的真实子任务，
            # 避免外层 OpsiScheduling 包装覆盖内层已记录的 OpsiObscure/OpsiAbyssal。
            if not hasattr(self.device, 'game_stuck_proxy_task'):
                self.device.game_stuck_proxy_task = task_name
            raise
        finally:
            self.config.task = previous_task

            if previous_context is None:
                if hasattr(self, '_smart_scheduling_context'):
                    delattr(self, '_smart_scheduling_context')
            else:
                self._smart_scheduling_context = previous_context

            if previous_config_context is None:
                if hasattr(self.config, '_smart_scheduling_context'):
                    delattr(self.config, '_smart_scheduling_context')
            else:
                self.config._smart_scheduling_context = previous_config_context
            self.config._disable_task_switch = previous_disable_task_switch
            if previous_task_switch_owner is None:
                if hasattr(self.config, '_task_switch_owner'):
                    delattr(self.config, '_task_switch_owner')
            else:
                self.config._task_switch_owner = previous_task_switch_owner

            if previous_bind is None:
                if hasattr(self.config, '_bind_task_override'):
                    delattr(self.config, '_bind_task_override')
                self.config.bind(self.config.task)
            else:
                self.config._bind_task_override = previous_bind
                self.config.bind(previous_bind)

    def _get_scheduling_action_point(self):
        """
        读取智能调度+决策所需的行动力。

        Returns:
            tuple[int, int]: (总行动力, 当前真实行动力)
        """
        self.action_point_enter()
        self.action_point_safe_get()
        self.action_point_quit()
        self.check_and_notify_action_point_threshold()
        return (
            int(getattr(self, '_action_point_total', 0) or 0),
            int(getattr(self, '_action_point_current', 0) or 0),
        )

    def _run_scheduled_meowfficer_farming(self, ap_preserve):
        """
        由智能调度+执行一轮耄耋相接。
        """
        if not hasattr(self, 'run_meowfficer_farming_once'):
            logger.error('[大世界-智能调度+] 当前实例不支持执行耄耋相接')
            self.config.task_stop()

        logger.info('[大世界-智能调度+] 执行一轮耄耋相接')
        # 耄耋相接会通过共享的手动配置项控制本轮行动力下限。
        # 代跑结束后必须恢复，否则其保留值会泄漏到后续侵蚀 1 调度。
        with self.config.temporary(
            OS_ACTION_POINT_PRESERVE=self.config.OS_ACTION_POINT_PRESERVE,
        ):
            try:
                self._run_with_opsi_task_context(
                    self.TASK_NAME_MEOWFFICER_FARMING,
                    self.run_meowfficer_farming_once,
                    ap_preserve=ap_preserve,
                )
            except ActionPointLimit as e:
                if ap_preserve > 0 and getattr(e, 'preserve', None) == ap_preserve:
                    logger.info(
                        f'[大世界-智能调度+] 耄耋相接已达到行动力保留值 '
                        f'({e.total} <= {ap_preserve})，返回智能调度+'
                    )
                    return
                raise

    def handle_first_auto_search(self, run):
        """由智能调度+决策是否执行 os_init 阶段跳过的首次自律寻敌。"""
        if not getattr(self, "_smart_scheduling_first_auto_search_pending", False):
            return
        self._smart_scheduling_first_auto_search_pending = False

        if not run:
            logger.info("智能调度+接下来执行侵蚀 1，跳过初始化自律寻敌")
            return

        self.run_first_auto_search()

    def _handle_smart_scheduling_no_task(self, yellow_coins, total_ap, current_ap, coin_target, meow_ap_preserve):
        """
        处理黄币和行动力不足导致没有可运行任务的情况。

        防止行动力溢出任务代跑智能调度+时，需要清理当前真实行动力，因此直接跑一轮耄耋相接。
        普通智能调度+保持延后，不按行动力恢复时间唤起。
        """
        if self.is_running_prevent_action_point_overflow_task() and current_ap > 0:
            logger.info(
                f'防止行动力溢出上下文：黄币不足且总行动力未达补黄币保留，'
                f'执行耄耋相接清理当前行动力 (当前={current_ap}, 总行动力={total_ap})'
            )
            if yellow_coins < coin_target:
                coin_status = f'黄币 {yellow_coins} 低于补黄币目标 {coin_target}'
            else:
                coin_status = f'黄币 {yellow_coins} 已达到补黄币阈值 {coin_target}'
            self.handle_first_auto_search(run=True)
            if self._run_scheduled_coin_task_once(self.TASK_NAME_MEOWFFICER_FARMING, 0):
                self.notify_push(
                    title='[AzurPilot] 防止行动力溢出 - 已执行耄耋相接',
                    content=(
                        f'{coin_status}\n'
                        f'总行动力 {total_ap} 低于补黄币保留 {meow_ap_preserve}\n'
                        f'已由 OpsiScheduling 执行一轮耄耋相接清理当前行动力 {current_ap}'
                    )
                )
                return

            logger.warning('[大世界-防止行动力溢出] 耄耋相接无可执行内容，无法继续清理当前行动力')
            self._delay_smart_scheduling_to_server_update('耄耋相接无可执行内容')
            self.config.task_stop()
            return

        self._notify_coins_ap_insufficient(yellow_coins, total_ap, coin_target, meow_ap_preserve)
        self._delay_smart_scheduling_for_ap_limit(total_ap, meow_ap_preserve)

    def _run_scheduled_hazard1_leveling(self, ap_preserve):
        """
        由智能调度+执行一轮侵蚀 1 练级。
        """
        if not hasattr(self, 'run_hazard1_leveling_once'):
            logger.error('[大世界-智能调度+] 当前实例不支持执行侵蚀 1 练级')
            self.config.task_stop()

        logger.info('[大世界-智能调度+] 执行一轮侵蚀 1 练级')
        self.handle_first_auto_search(run=False)
        if hasattr(self, 'os_check_leveling'):
            self._run_with_opsi_task_context(
                self.TASK_NAME_HAZARD1_LEVELING,
                self.os_check_leveling,
            )
        self._run_with_opsi_task_context(
            self.TASK_NAME_HAZARD1_LEVELING,
            self.run_hazard1_leveling_once,
            ap_preserve=ap_preserve,
        )

    def _run_scheduled_coin_task_once(self, task_name, ap_preserve):
        """由智能调度+代理执行一轮黄币补充任务。"""
        if not hasattr(self, '_smart_scheduling_no_content_task'):
            self._smart_scheduling_no_content_task = None
        self._smart_scheduling_no_content_task = None

        task_display = self.TASK_NAMES.get(task_name, task_name)
        logger.info(f'[大世界-智能调度+] 代理执行一轮{task_display}')
        if task_name == self.TASK_NAME_MEOWFFICER_FARMING:
            self._run_scheduled_meowfficer_farming(ap_preserve)
        elif task_name == self.TASK_NAME_OBSCURE:
            if not hasattr(self, 'clear_obscure'):
                logger.error('[大世界-智能调度+] 当前实例不支持执行隐秘海域')
                self.config.task_stop()
            self._run_with_opsi_task_context(task_name, self.clear_obscure)
        elif task_name == self.TASK_NAME_ABYSSAL:
            if not hasattr(self, 'clear_abyssal'):
                logger.error('[大世界-智能调度+] 当前实例不支持执行深渊坐标')
                self.config.task_stop()
            self._run_with_opsi_task_context(task_name, self.clear_abyssal)
        elif task_name == self.TASK_NAME_STRONGHOLD:
            if not hasattr(self, 'clear_stronghold'):
                logger.error('[大世界-智能调度+] 当前实例不支持执行塞壬要塞')
                self.config.task_stop()
            self._run_with_opsi_task_context(task_name, self.clear_stronghold)
        else:
            logger.error(f'[大世界-智能调度+] 不支持代理执行黄币补充任务: {task_name}')
            self.config.task_stop()

        no_content_task = getattr(self, '_smart_scheduling_no_content_task', None)
        self._smart_scheduling_no_content_task = None
        if no_content_task == task_name:
            logger.info(f'[大世界-智能调度+] {task_display}没有可执行内容')
            return False
        return True

    def _delay_smart_scheduling_for_ap_limit(self, total_ap, min_ap_reserve):
        """
        因行动力不足推迟智能调度+。
        """
        logger.warning(f'[大世界-智能调度+] 行动力达到最低保留 ({total_ap} <= {min_ap_reserve})')
        self._notify_ap_insufficient(total_ap, min_ap_reserve)
        self._delay_smart_scheduling_to_server_update('行动力不足')
        self.config.task_stop()

    def _delay_smart_scheduling_for_opsi_explore(self):
        """开荒未完成时延迟智能调度+并结束本轮。"""
        if not self.is_in_opsi_explore():
            return False

        self._delay_smart_scheduling_to_server_update('每月开荒+正在运行')
        self.config.task_stop()
        return True

    def run_smart_scheduling_once(self):
        """执行一轮智能调度+决策。"""
        # 防溢出任务直接调用本方法，需要在此处补齐开荒拦截。
        if (
            self.is_running_prevent_action_point_overflow_task()
            and self._delay_smart_scheduling_for_opsi_explore()
        ):
            return

        yellow_coins = self.get_yellow_coins()
        total_ap, current_ap = self._get_scheduling_action_point()

        # 月末清理行动力检查（优先级最高，先于黄币和侵蚀1调度）
        self._reset_month_end_cleanup_first_run_if_new_month()
        if self._is_month_end_cleanup_active():
            month_end_preserve = self._get_month_end_action_point_preserve()
            if total_ap > month_end_preserve:
                logger.info(
                    f'[大世界-智能调度+] 进入月末清理行动力模式: '
                    f'总行动力={total_ap}, 保留值={month_end_preserve}'
                )
                self._run_month_end_cleanup(
                    month_end_preserve, yellow_coins, total_ap, current_ap
                )
                return
            else:
                logger.info(
                    f'[大世界-智能调度+] 月末清理已启用但行动力 {total_ap} '
                    f'<= 保留值 {month_end_preserve}，跳过清理'
                )
                # 月底最后一天（重置日当天）行动力不足时，每隔 2 小时再次检查
                # 因为行动力会自然回复，2 小时后可能又有足够的行动力执行月末清理
                remain = get_os_reset_remain()
                if remain <= 0:
                    logger.info(
                        '[大世界-月末清理] 今天是月底最后一天，行动力不足，'
                        '2 小时后再次运行'
                    )
                    self._delay_smart_scheduling_with_minutes(
                        '月末清理行动力不足（月底最后一天）', 120
                    )
                    self.config.task_stop()
                    return

        cl1_preserve = self._get_smart_scheduling_operation_coins_preserve()
        cl1_ap_preserve = self._get_effective_cl1_ap_preserve()
        meow_ap_preserve = self._get_coin_task_action_point_preserve()
        coin_target_scheduling = self._is_coin_target_scheduling_enabled()
        self._sync_smart_scheduling_mode_state(coin_target_scheduling)
        coin_replenish_active = self._is_coin_replenish_active()
        ap_replenish_active = self._is_ap_replenish_active()

        logger.info(f'[大世界-智能调度+] 黄币: {yellow_coins}, 保留值: {cl1_preserve}')
        if self.is_running_prevent_action_point_overflow_task():
            logger.info(
                f'[大世界-智能调度+] 行动力: 当前={current_ap}, 总计={total_ap}, '
                f'CL1保留: {cl1_ap_preserve}, 补黄币保留: {meow_ap_preserve}'
            )
        else:
            logger.info(
                f'[大世界-智能调度+] 总行动力: {total_ap}, '
                f'CL1保留: {cl1_ap_preserve}, 补黄币保留: {meow_ap_preserve}'
            )

        try:
            if coin_target_scheduling and (yellow_coins < cl1_preserve or coin_replenish_active):
                coin_target, start_coins, return_threshold = self._get_coin_replenish_target(
                    yellow_coins,
                    cl1_preserve,
                )
                logger.info(
                    f'[大世界-智能调度+] 补黄币目标: 当前={yellow_coins}, 起始={start_coins}, '
                    f'回补阈值={return_threshold}, 目标={coin_target}'
                )
                if yellow_coins >= coin_target:
                    logger.info(f'[大世界-智能调度+] 黄币已补足 ({yellow_coins} >= {coin_target})，恢复侵蚀1练级')
                    self._clear_coin_replenish_target()
                else:
                    logger.info(f'[大世界-智能调度+] 黄币未补足 ({yellow_coins} < {coin_target})，需要执行黄币补充任务')
                    if total_ap <= meow_ap_preserve:
                        logger.warning(f'[大世界-智能调度+] 行动力不足以执行黄币补充任务 ({total_ap} <= {meow_ap_preserve})')
                        self._handle_smart_scheduling_no_task(
                            yellow_coins,
                            total_ap,
                            current_ap,
                            coin_target,
                            meow_ap_preserve,
                        )
                        return

                    self._dispatch_coin_task(
                        yellow_coins,
                        total_ap,
                        coin_target,
                        meow_ap_preserve,
                    )
                    return

            if not coin_target_scheduling and (yellow_coins < cl1_preserve or ap_replenish_active):
                if not ap_replenish_active:
                    self._set_ap_replenish_active()
                logger.info(
                    f'[大世界-智能调度+] 体力调度补黄币中: 黄币={yellow_coins}, '
                    f'黄币阈值={cl1_preserve}, 总行动力={total_ap}, 行动力阈值={meow_ap_preserve}'
                )
                if total_ap <= meow_ap_preserve:
                    logger.info(f'[大世界-智能调度+] 行动力已达到体力调度阈值 ({total_ap} <= {meow_ap_preserve})，停止补黄币')
                    self._clear_ap_replenish_active()
                    overflow_cleanup = (
                        self.is_running_prevent_action_point_overflow_task()
                        and current_ap > 0
                    )
                    if yellow_coins < cl1_preserve or overflow_cleanup:
                        self._handle_smart_scheduling_no_task(
                            yellow_coins,
                            total_ap,
                            current_ap,
                            cl1_preserve,
                            meow_ap_preserve,
                        )
                        return
                    logger.info(
                        f'[大世界-智能调度+] 黄币已补足 ({yellow_coins} >= {cl1_preserve})，'
                        '恢复侵蚀1练级'
                    )
                else:
                    self._dispatch_coin_task(
                        yellow_coins,
                        total_ap,
                        cl1_preserve,
                        meow_ap_preserve,
                    )
                    return

            if total_ap <= cl1_ap_preserve:
                self._delay_smart_scheduling_for_ap_limit(total_ap, cl1_ap_preserve)

            logger.info(f'[大世界-智能调度+] 黄币充足 ({yellow_coins} >= {cl1_preserve})，执行侵蚀1练级')
            self._execute_hazard1_leveling(yellow_coins, total_ap)
        except ActionPointLimit as e:
            logger.warning(f'[大世界-智能调度+] 智能调度+执行子任务时行动力不足: {e}')
            preserve = getattr(e, 'preserve', None) or cl1_ap_preserve
            current = getattr(e, 'total', None) or getattr(e, 'current', None) or total_ap
            self._delay_smart_scheduling_for_ap_limit(current, preserve)

    def run_smart_scheduling(self):
        """
        执行智能调度+主逻辑

        此方法是智能调度+任务的入口点，负责：
        1. 检查是否启用智能调度+
        2. 根据黄币和行动力状态决定当前应该执行的任务
        3. 按代理模式协调子任务执行
        """
        logger.hr('大世界-智能调度+', level=1)

        # 直接调用入口仍保留保护，覆盖未经过 OSCampaignRun 的调用方。
        if self._delay_smart_scheduling_for_opsi_explore():
            return

        # 检查是否启用智能调度+
        if not self.is_smart_scheduling_enabled():
            logger.info('[大世界-智能调度+] 智能调度+未启用，跳过执行')
            return

        while True:
            self.run_smart_scheduling_once()
            self.config.check_task_switch()

    def _notify_coins_ap_insufficient(self, yellow_coins, total_ap, coin_target, meow_ap_preserve):
        """
        发送黄币与行动力双重不足的通知
        """
        if not self.is_smart_scheduling_enabled():
            return

        if not self._can_send_ap_notification('_last_ap_coins_insufficient_notification_time'):
            return
        
        pushed = self.notify_push(
            title="[AzurPilot] 智能调度+ - 黄币与行动力双重不足",
            content=(
                f"黄币: {yellow_coins}，补黄币阈值: {coin_target}\n"
                f"总行动力 {total_ap} 不足 (需要 {meow_ap_preserve})\n推迟任务"
            )
        )
        if pushed:
            self._mark_ap_notification_sent('_last_ap_coins_insufficient_notification_time')
    
    def _notify_ap_insufficient(self, total_ap, min_reserve):
        """
        发送行动力低于最低保留的通知
        """
        if not self.is_smart_scheduling_enabled():
            return

        if not self._can_send_ap_notification('_last_ap_insufficient_notification_time'):
            return
        
        pushed = self.notify_push(
            title="[AzurPilot] 智能调度+ - 行动力不足",
            content=f"总行动力 {total_ap} 低于最低保留 {min_reserve}，推迟任务"
        )
        if pushed:
            self._mark_ap_notification_sent('_last_ap_insufficient_notification_time')
    
    def _dispatch_coin_task(self, yellow_coins, total_ap, coin_target, meow_ap_preserve):
        """
        调度黄币补充任务。

        所有黄币补充任务都由 OpsiScheduling 代理执行一轮，不启用、关闭、推迟子任务调度器。
        """
        all_coin_tasks = self._get_enabled_coin_tasks()
        if not all_coin_tasks:
            logger.error('[大世界-智能调度+] 没有启用任何黄币补充任务，停止智能调度+')
            self.notify_push(
                title='[AzurPilot] 智能调度+ - 未启用黄币补充任务',
                content='请至少启用耄耋相接、隐秘海域、深渊坐标或塞壬要塞中的一项',
            )
            self._delay_smart_scheduling_to_server_update('未启用黄币补充任务')
            self.config.task_stop()

        self.handle_first_auto_search(run=True)
        task_names = '、'.join([self.TASK_NAMES.get(task, task) for task in all_coin_tasks])
        logger.info(f'[大世界-智能调度+] 启用的黄币补充任务: {task_names}')

        for task_name in all_coin_tasks:
            if self._run_scheduled_coin_task_once(task_name, meow_ap_preserve):
                self._notify_coin_task_proxy(
                    yellow_coins,
                    total_ap,
                    coin_target,
                    meow_ap_preserve,
                    task_name,
                )
                return

        logger.warning('[大世界-智能调度+] 智能调度+启用的黄币补充任务均无可执行内容，结束本轮智能调度+')
        self._delay_smart_scheduling_to_server_update('黄币补充任务均无可执行内容')
        self.config.task_stop()

    def _notify_coin_task_proxy(self, yellow_coins, total_ap, coin_target, meow_ap_preserve, task_name):
        """
        发送代理执行黄币补充任务的通知。
        """
        if not self.is_smart_scheduling_enabled():
            return

        state_key = self.RUNTIME_ATTR_LAST_NOTIFIED_COIN_TASK
        if getattr(self.config, state_key, None) == task_name:
            return

        attempt_key = self.RUNTIME_ATTR_LAST_COIN_TASK_NOTIFICATION_ATTEMPT
        last_attempt = getattr(self.config, attempt_key, None)
        now = current_time()
        if isinstance(last_attempt, tuple) and len(last_attempt) == 2:
            attempted_task, attempted_at = last_attempt
            if (
                attempted_task == task_name
                and isinstance(attempted_at, type(now))
                and now - attempted_at < timedelta(minutes=self.AP_NOTIFY_MIN_INTERVAL_MINUTES)
            ):
                return
        setattr(self.config, attempt_key, (task_name, now))

        task_display = self.TASK_NAMES.get(task_name, task_name)
        pushed = self.notify_push(
            title="[AzurPilot] 智能调度+ - 已代理执行黄币补充任务",
            content=(f"黄币: {yellow_coins}，补黄币阈值: {coin_target}\n"
                     f"总行动力: {total_ap} (需要 {meow_ap_preserve})\n"
                     f"已代理执行一轮{task_display}获取黄币")
        )
        if pushed:
            setattr(self.config, state_key, task_name)
    
    def _execute_hazard1_leveling(self, yellow_coins, total_ap):
        """
        执行侵蚀1练级任务
        """
        self._clear_coin_task_notification_state()
        logger.info('[大世界-智能调度+] 执行侵蚀1练级任务')
        self._run_scheduled_hazard1_leveling(self._get_effective_cl1_ap_preserve())

    # ==================== 月末清理行动力相关方法 ====================

    def _get_month_end_cleanup_days(self):
        """
        读取月末清理行动力的触发天数。

        Returns:
            int: 距大世界重置剩余天数小于等于此值时启动月末清理，0 表示禁用。
        """
        try:
            days = int(self.config.cross_get(
                keys=self.CONFIG_PATH_MONTH_END_CLEANUP_DAYS,
                default=0,
            ) or 0)
        except (TypeError, ValueError):
            days = 0
        return max(0, days)

    def _get_month_end_action_point_preserve(self):
        """
        获取月末清理行动力时的保留值。

        规则：
            - 用户配置 MonthEndActionPointPreserve 作为基础值
            - 如果启用 OpsiCrossMonth，最低预留 200 行动力
            - 取两者最大值作为最终保留值

        Returns:
            int: 月末清理行动力保留值。
        """
        try:
            user_preserve = int(self.config.cross_get(
                keys=self.CONFIG_PATH_MONTH_END_AP_PRESERVE,
                default=0,
            ) or 0)
        except (TypeError, ValueError):
            user_preserve = 0

        cross_month_enabled = self.config.is_task_enabled('OpsiCrossMonth')
        min_preserve = 200 if cross_month_enabled else 0
        final_preserve = max(user_preserve, min_preserve)
        logger.info(
            f'[大世界-月末清理] 行动力保留值: 用户配置={user_preserve}, '
            f'跨月每日{"启用" if cross_month_enabled else "未启用"}, '
            f'最低预留={min_preserve}, 最终保留={final_preserve}'
        )
        return final_preserve

    def _is_month_end_cleanup_active(self):
        """
        判断当前是否应进入月末清理行动力模式。

        触发条件：
            1. MonthEndActionPointCleanupEnable 开关已开启
            2. MonthEndActionPointCleanupDays > 0
            3. 距大世界重置剩余天数 <= MonthEndActionPointCleanupDays

        Returns:
            bool: 是否启用月末清理。
        """
        if not self._config_enabled(keys=self.CONFIG_PATH_MONTH_END_CLEANUP_ENABLE, default=False):
            return False
        cleanup_days = self._get_month_end_cleanup_days()
        if cleanup_days <= 0:
            return False
        remain = get_os_reset_remain()
        active = remain <= cleanup_days
        logger.info(
            f'[大世界-月末清理] 清理天数={cleanup_days}, 重置剩余={remain}, '
            f'月末清理{"启用" if active else "未启用"}'
        )
        return active

    def _is_month_end_cleanup_first_run(self):
        """
        判断本月是否首次运行月末清理。

        Returns:
            bool: True 表示本月首次运行。
        """
        first_run = self._get_smart_scheduling_state_value(
            self.STATE_KEY_MONTH_END_CLEANUP_FIRST_RUN,
            default=True,
        )
        return first_run is not False

    def _set_month_end_cleanup_first_run(self, value):
        """
        标记本月是否已运行过月末清理。

        Args:
            value (bool): False 表示已运行过，True 表示首次运行。
        """
        self._set_smart_scheduling_state_value(
            self.STATE_KEY_MONTH_END_CLEANUP_FIRST_RUN,
            value,
        )

    def _reset_month_end_cleanup_first_run_if_new_month(self):
        """
        检测到大世界重置周期已进入新月时，重置月末清理首次运行标记。
        """
        if not self._is_month_end_cleanup_active():
            if not self._is_month_end_cleanup_first_run():
                logger.info('[大世界-月末清理] 大世界已进入新月周期，重置首次运行标记')
                self._set_month_end_cleanup_first_run(True)

    def _is_month_end_shop_purchase_enabled(self):
        """
        读取月末清理时是否执行商店购买。

        Returns:
            bool: True 表示执行商店购买。
        """
        return self._config_enabled(keys=self.CONFIG_PATH_MONTH_END_SHOP_PURCHASE, default=True)

    def _run_month_end_shop_purchase(self):
        """
        月末清理中的商店购买步骤。

        以 OpsiShop 任务上下文执行一次港口商店购买，
        不触发 task_delay/task_stop，购买完成后返回大世界地图。
        若用户关闭了商店购买开关，则跳过此步骤。
        """
        if not self._is_month_end_shop_purchase_enabled():
            logger.info('[大世界-月末清理] 商店购买已关闭，跳过')
            return
        logger.info('[大世界-月末清理] 执行港口商店购买')
        self._run_with_opsi_task_context(
            'OpsiShop',
            self.perform_port_shop_purchase,
        )

    def _run_month_end_cleanup(self, month_end_preserve, yellow_coins, total_ap, current_ap):
        """
        月末清理行动力主循环。

        执行流程：
            1. 首次运行时先调出塞壬要塞
            2. 每轮循环：短猫相接 → 商店购买 → 隐秘海域 → 深渊坐标
            3. 循环直到总行动力 <= 保留值 或 所有任务无可执行内容

        Args:
            month_end_preserve (int): 月末清理行动力保留值。
            yellow_coins (int): 当前黄币数量。
            total_ap (int): 当前总行动力。
            current_ap (int): 当前真实行动力。
        """
        logger.hr('大世界-月末清理行动力', level=2)
        logger.info(
            f'[大世界-月末清理] 开始清理: 黄币={yellow_coins}, '
            f'总行动力={total_ap}, 当前行动力={current_ap}, 保留值={month_end_preserve}'
        )

        # 首次运行时先调出塞壬要塞
        is_first_run = self._is_month_end_cleanup_first_run()
        if is_first_run:
            logger.info('[大世界-月末清理] 本月首次运行，先调出塞壬要塞')
            try:
                self._run_scheduled_coin_task_once(self.TASK_NAME_STRONGHOLD, 0)
            except ActionPointLimit as e:
                logger.warning(f'[大世界-月末清理] 塞壬要塞行动力不足: {e}')
            self._set_month_end_cleanup_first_run(False)

        # 月末清理主循环（无限制，依靠退出条件终止）
        round_num = 0
        while True:
            round_num += 1
            logger.hr(f'大世界-月末清理 第{round_num}轮', level=3)

            # 检查行动力是否已降到保留值
            total_ap, current_ap = self._get_scheduling_action_point()
            if total_ap <= month_end_preserve:
                logger.info(
                    f'[大世界-月末清理] 总行动力 {total_ap} <= 保留值 {month_end_preserve}，'
                    f'月末清理完成'
                )
                break

            logger.info(
                f'[大世界-月末清理] 第{round_num}轮: 总行动力={total_ap}, '
                f'保留值={month_end_preserve}, 继续清理'
            )

            # 1. 调出隐秘海域
            try:
                self._run_scheduled_coin_task_once(self.TASK_NAME_OBSCURE, 0)
            except ActionPointLimit as e:
                logger.warning(f'[大世界-月末清理] 隐秘海域行动力不足: {e}')

            # 2. 调出深渊坐标
            try:
                self._run_scheduled_coin_task_once(self.TASK_NAME_ABYSSAL, 0)
            except ActionPointLimit as e:
                logger.warning(f'[大世界-月末清理] 深渊坐标行动力不足: {e}')

            # 3. 执行一轮短猫相接
            meow_success = False
            try:
                meow_success = self._run_scheduled_coin_task_once(
                    self.TASK_NAME_MEOWFFICER_FARMING, 0
                )
            except ActionPointLimit as e:
                logger.warning(f'[大世界-月末清理] 短猫相接行动力不足: {e}')

            # 4. 回到大世界商店购买
            try:
                self._run_month_end_shop_purchase()
            except Exception as e:
                logger.warning(f'[大世界-月末清理] 商店购买异常: {e}')

            # 短猫无可执行内容时，其他任务也跑完一轮，结束月末清理
            if not meow_success:
                logger.info('[大世界-月末清理] 短猫相接无可执行内容，月末清理结束')
                break

        # 月末清理结束，刷新行动力并通知
        total_ap, current_ap = self._get_scheduling_action_point()
        logger.info(
            f'[大世界-月末清理] 清理结束: 总行动力={total_ap}, '
            f'当前行动力={current_ap}, 保留值={month_end_preserve}'
        )
        self.notify_push(
            title='[AzurPilot] 智能调度+ - 月末清理行动力完成',
            content=(
                f'月末清理行动力已完成\n'
                f'总行动力: {total_ap} (保留值 {month_end_preserve})\n'
                f'当前行动力: {current_ap}'
            ),
        )

        # 月底最后一天（重置日当天）每隔 2 小时运行一次，其他情况延迟到服务器刷新
        remain = get_os_reset_remain()
        if remain <= 0:
            logger.info('[大世界-月末清理] 今天是月底最后一天，2 小时后再次运行')
            self._delay_smart_scheduling_with_minutes('月末清理行动力已完成（月底最后一天）', 120)
        else:
            self._delay_smart_scheduling_to_server_update('月末清理行动力已完成')
        self.config.task_stop()
    
    def notify_action_point_threshold(self, title, content):
        """
        发送行动力阈值变化通知
        
        Args:
            title (str): 通知标题
            content (str): 通知内容
        """
        if not self.is_smart_scheduling_enabled():
            return

        if not self._can_send_ap_notification('_last_ap_threshold_notification_time'):
            return
        
        pushed = self.notify_push(title=title, content=content)
        if pushed:
            self._mark_ap_notification_sent('_last_ap_threshold_notification_time')

"""
Shared mixin for yellow coin supplement tasks (OpsiObscure, OpsiAbyssal, OpsiStronghold, OpsiMeowfficerFarming).

This mixin provides common functionality for tasks that can supplement yellow coins
and need to check yellow coin thresholds to return to CL1.
"""
from datetime import datetime, timedelta

from module.logger import logger


class CoinTaskMixin:
    """Mixin class for yellow coin supplement tasks."""
    
    # Task names mapping for notifications
    TASK_NAMES = {
        'OpsiMeowfficerFarming': '短猫相接',
        'OpsiObscure': '隐秘海域',
        'OpsiAbyssal': '深渊海域',
        'OpsiStronghold': '塞壬要塞'
    }
    
    # All coin supplement tasks in fixed order
    ALL_COIN_TASKS = ['OpsiObscure', 'OpsiAbyssal', 'OpsiStronghold', 'OpsiMeowfficerFarming']
    
    # Configuration paths (shared constants to avoid hardcoding)
    CONFIG_PATH_CL1_PRESERVE = 'OpsiHazard1Leveling.OpsiHazard1Leveling.OperationCoinsPreserve'
    CONFIG_PATH_RETURN_THRESHOLD = 'OpsiHazard1Leveling.OpsiScheduling.OperationCoinsReturnThreshold'
    CONFIG_PATH_RETURN_THRESHOLD_APPLY_ALL = 'OpsiHazard1Leveling.OpsiScheduling.OperationCoinsReturnThresholdApplyToAllCoinTasks'

    # Task name used for "short cat" (meowfficer farming)
    TASK_NAME_MEOWFFICER_FARMING = 'OpsiMeowfficerFarming'
    
    def notify_push(self, title, content):
        """
        Send push notification (smart scheduling feature).
        
        Args:
            title (str): Notification title (will be prefixed with instance name)
            content (str): Notification content
            
        Notes:
            - Only works when smart scheduling is enabled
            - Requires Error_OnePushConfig to be set in config
            - Uses onepush library to send notifications
            - Title will be formatted as "[Alas <instance_name>] original_title"
        """
        # Check if smart scheduling is enabled
        if not self.config.OpsiScheduling_EnableSmartScheduling:
            return
        # Check if Opsi mail notification is enabled
        if not self.config.OpsiGeneral_NotifyOpsiMail:
            return
        
        # Check if push config is properly set
        push_config = self.config.Error_OnePushConfig
        if not self._is_push_config_valid(push_config):
            logger.warning("推送配置未设置或 provider 为 null，跳过推送。请在 Alas 设置 -> 错误处理 -> OnePush 配置中设置有效的推送渠道。")
            return
        
        # Get instance name and format title
        instance_name = getattr(self.config, 'config_name', 'Alas')
        if title.startswith('[Alas]'):
            formatted_title = f"[Alas <{instance_name}>]{title[6:]}"
        else:
            formatted_title = f"[Alas <{instance_name}>] {title}"
        
        try:
            from module.notify import handle_notify as notify_handle_notify
            success = notify_handle_notify(
                self.config.Error_OnePushConfig,
                title=formatted_title,
                content=content
            )
            if success:
                logger.info(f"✓ 推送通知成功: {formatted_title}")
            else:
                logger.warning(f"✗ 推送通知失败: {formatted_title}")
        except Exception as e:
            logger.error(f"推送通知异常: {e}")
    
    def _is_push_config_valid(self, push_config):
        """
        Check if push config is valid.
        
        Args:
            push_config: Push configuration string or object
            
        Returns:
            bool: True if config is valid, False otherwise
        """
        if not push_config:
            return False
        
        # Try to parse as structured data first
        if isinstance(push_config, dict):
            provider = push_config.get('provider')
            return provider is not None and provider.lower() != 'null'
        
        # Fallback to string matching for backward compatibility
        if isinstance(push_config, str):
            push_config_lower = push_config.lower()
            # Check for common null patterns
            if 'provider:null' in push_config_lower or 'provider: null' in push_config_lower:
                return False
            # If it's a structured string, try to extract provider
            # Common format: "provider: xxx\nkey: yyy" or "provider=xxx"
            if 'provider' in push_config_lower:
                # More robust check: look for provider followed by null
                import re
                # Match "provider: null" or "provider:null" (case insensitive)
                if re.search(r'provider\s*[:=]\s*null', push_config_lower):
                    return False
        
        return True
    
    def _get_operation_coins_return_threshold(self):
        """
        Calculate the yellow coin return threshold for switching back to CL1.
        
        Returns:
            tuple: (return_threshold, cl1_preserve) or (None, cl1_preserve) if disabled
                - return_threshold: The threshold value, or None if check is disabled (value is 0)
                - cl1_preserve: The CL1 preserve value (cached for reuse)
        """
        if not self.is_cl1_enabled:
            return None, None

        # Scope switch: by default apply to all coin supplement tasks.
        # When disabled, only apply to OpsiMeowfficerFarming (短猫相接).
        if not self._is_operation_coins_return_threshold_applicable():
            cl1_preserve = self.config.cross_get(
                keys=self.CONFIG_PATH_CL1_PRESERVE,
                default=100000
            )
            logger.info('OperationCoinsReturnThreshold 适用范围开关关闭：仅短猫相接启用；当前任务跳过黄币返回检查')
            return None, cl1_preserve
        
        # Get and cache CL1 preserve value
        cl1_preserve = self.config.cross_get(
            keys=self.CONFIG_PATH_CL1_PRESERVE,
            default=100000
        )
        
        # Get OperationCoinsReturnThreshold from OpsiScheduling config
        # Always use cross_get to read from config file, because the config is under OpsiHazard1Leveling
        # which may not be in the bind list when running other tasks like OpsiAbyssal
        # This ensures we read the actual value from config file, not the default from config_generated.py
        return_threshold_config = self.config.cross_get(
            keys=self.CONFIG_PATH_RETURN_THRESHOLD,
            default=None
        )
        
        # If cross_get returns None, try direct attribute access as fallback
        # (in case the config path structure changes in the future)
        if return_threshold_config is None and hasattr(self.config, 'OpsiScheduling_OperationCoinsReturnThreshold'):
            attr_value = self.config.OpsiScheduling_OperationCoinsReturnThreshold
            if attr_value is not None:
                return_threshold_config = attr_value
        
        # Log the config value for debugging
        logger.info(f'OperationCoinsReturnThreshold 配置值: {return_threshold_config}, CL1保留值: {cl1_preserve}')
        
        # If value is 0, disable yellow coin check
        # Use explicit comparison with 0 (not just falsy check) to handle 0 correctly
        if return_threshold_config == 0:
            logger.info('OperationCoinsReturnThreshold 为 0，禁用黄币检查')
            return None, cl1_preserve
        
        # If value is None, use default (equal to cl1_preserve, resulting in 2x threshold)
        if return_threshold_config is None:
            return_threshold_config = cl1_preserve
        
        # Calculate final threshold: CL1 preserve + return threshold
        return_threshold = cl1_preserve + return_threshold_config
        
        return return_threshold, cl1_preserve

    def _get_current_coin_task_name(self):
        """
        Get current task name for scheduling scope checks.

        Returns:
            str: task command name (e.g., 'OpsiObscure') if available, otherwise class name.
        """
        if hasattr(self.config, 'task') and hasattr(self.config.task, 'command') and self.config.task.command:
            return self.config.task.command
        return self.__class__.__name__

    def _is_operation_coins_return_threshold_applicable(self):
        """
        Determine whether OperationCoinsReturnThreshold should be applied for current task.

        Config:
            OpsiScheduling.OperationCoinsReturnThresholdApplyToAllCoinTasks (bool)
                - True: apply to all coin supplement tasks
                - False: only apply to OpsiMeowfficerFarming (短猫相接)
        """
        apply_all = self.config.cross_get(
            keys=self.CONFIG_PATH_RETURN_THRESHOLD_APPLY_ALL,
            default=True
        )
        if apply_all:
            return True
        return self._get_current_coin_task_name() == self.TASK_NAME_MEOWFFICER_FARMING
    
    def _check_yellow_coins_and_return_to_cl1(self, context="循环中", task_display_name=None):
        """
        Check if yellow coins are sufficient and return to CL1 if so.
        
        This check only runs when smart scheduling is enabled. When smart scheduling
        is disabled, tasks should run independently without automatic switching.
        
        Args:
            context: Context string for logging (e.g., "任务开始前", "循环中")
            task_display_name: Display name for the task in notification (e.g., "隐秘海域")
        
        Returns:
            bool: True if returned to CL1, False otherwise
        """
        if not self.is_cl1_enabled:
            return False

        # Only perform yellow coin check when smart scheduling is enabled
        # When smart scheduling is disabled, tasks should run independently
        smart_enabled = getattr(self.config, 'OpsiScheduling_EnableSmartScheduling', False)
        if not smart_enabled:
            logger.info('智能调度未启用，跳过黄币检查，任务独立运行')
            return False

        if not self._is_operation_coins_return_threshold_applicable():
            # Scope switch off: only short cat checks coins.
            return False
        
        return_threshold, cl1_preserve = self._get_operation_coins_return_threshold()
        
        # If check is disabled (return_threshold is None), skip
        if return_threshold is None:
            logger.info('OperationCoinsReturnThreshold 为 0，跳过黄币检查，仅使用行动力阈值控制')
            return False
        
        yellow_coins = self.get_yellow_coins()
        logger.info(f'【{context}黄币检查】黄币={yellow_coins}, 阈值={return_threshold}')
        
        if yellow_coins >= return_threshold:
            logger.info(f'黄币充足 ({yellow_coins} >= {return_threshold})，切换回侵蚀1继续执行')
            
            # Get task display name
            if task_display_name is None:
                task_name = self.__class__.__name__
                task_display_name = self.TASK_NAMES.get(task_name, task_name)
            
            self.notify_push(
                title=f"[Alas] {task_display_name} - 黄币充足",
                content=f"黄币 {yellow_coins} 达到阈值 {return_threshold}\n切换回侵蚀1继续执行"
            )
            self._disable_all_coin_tasks_and_return_to_cl1()
            return True
        
        return False
    
    def _disable_all_coin_tasks_and_return_to_cl1(self):
        """
        Disable all coin supplement tasks and return to CL1.
        """
        with self.config.multi_set():
            # Disable all coin supplement task schedulers
            for task in self.ALL_COIN_TASKS:
                self.config.cross_set(keys=f'{task}.Scheduler.Enable', value=False)
            self.config.task_call('OpsiHazard1Leveling')
        self.config.task_stop()
    
    def _try_other_coin_tasks(self, current_task_name=None):
        """
        Try to call other coin supplement tasks.
        Uses fixed order: OpsiObscure -> OpsiAbyssal -> OpsiStronghold -> OpsiMeowfficerFarming
        
        Args:
            current_task_name: Name of current task (e.g., 'OpsiObscure')
        """
        if current_task_name is None:
            current_task_name = self.__class__.__name__
        
        # Find current task index
        try:
            current_index = self.ALL_COIN_TASKS.index(current_task_name)
        except ValueError:
            current_index = -1
        
        # Try tasks after current one
        for i in range(current_index + 1, len(self.ALL_COIN_TASKS)):
            task = self.ALL_COIN_TASKS[i]
            # Skip current task to prevent re-enabling it
            if task == current_task_name:
                continue
            if self.config.is_task_enabled(task):
                task_display = self.TASK_NAMES.get(task, task)
                logger.info(f'尝试调用黄币补充任务: {task_display}')
                self.config.task_call(task)
                return
        
        # If no tasks after current one, try tasks before (but skip self)
        for i in range(0, current_index):
            task = self.ALL_COIN_TASKS[i]
            # Skip current task to prevent re-enabling it
            if task == current_task_name:
                continue
            if self.config.is_task_enabled(task):
                task_display = self.TASK_NAMES.get(task, task)
                logger.info(f'尝试调用黄币补充任务: {task_display}')
                self.config.task_call(task)
                return
        
        # If all tasks are unavailable, return to CL1
        logger.warning('所有黄币补充任务都不可用，返回侵蚀1')
        self.config.task_call('OpsiHazard1Leveling')
        self.config.task_stop()
    
    def _finish_task_with_smart_scheduling(self, task_name, task_display_name=None, consider_reset_remain=True):
        """
        根据智能调度状态完成任务：智能调度开启时禁用任务，关闭时延迟任务。
        
        Args:
            task_name: 任务名称（如 'OpsiObscure'）
            task_display_name: 任务显示名称（如 '隐秘海域'），用于日志，如果为 None 则使用 task_name
            consider_reset_remain: 是否考虑大世界重置剩余时间（仅对 OpsiObscure 和 OpsiAbyssal 有效）
        
        Returns:
            bool: 是否已处理（True 表示已调用 task_stop，调用者应 return）
        """
        if task_display_name is None:
            task_display_name = task_name
        
        smart_enabled = getattr(self.config, 'OpsiScheduling_EnableSmartScheduling', False)
        
        if smart_enabled:
            # 智能调度开启：关闭任务，由智能调度统一管理
            logger.info(f'{task_display_name}任务完成（智能调度已启用），禁用任务调度')
            self.config.cross_set(keys=f'{task_name}.Scheduler.Enable', value=False)
            self.config.task_stop()
        else:
            # 智能调度关闭：推迟任务到下次运行
            if consider_reset_remain and task_name in ('OpsiObscure', 'OpsiAbyssal'):
                try:
                    from module.config.utils import get_os_reset_remain  # type: ignore
                    remain = get_os_reset_remain()
                    if remain == 0:
                        logger.info(f'{task_display_name}任务完成，距离大世界重置不足1天，延迟2.5小时后再运行')
                        self.config.task_delay(minute=150, server_update=True)
                    else:
                        logger.info(f'{task_display_name}任务完成，延迟到下次服务器刷新后再运行')
                        self.config.task_delay(server_update=True)
                except ImportError:
                    # 如果无法导入 get_os_reset_remain，使用默认延迟策略
                    logger.info(f'{task_display_name}任务完成，延迟到下次服务器刷新后再运行')
                    self.config.task_delay(server_update=True)
            else:
                # 默认：延迟到下次服务器刷新
                logger.info(f'{task_display_name}任务完成，延迟到下次服务器刷新后再运行')
                self.config.task_delay(server_update=True)
            self.config.task_stop()
        
        return True
    
    def _handle_no_content_and_try_other_tasks(self, task_display_name, log_message):
        """
        Handle case when task has no content to execute.
        If yellow coins are insufficient, try other coin tasks.
        Otherwise, disable current task.
        
        Args:
            task_display_name: Display name for logging (e.g., "隐秘海域")
            log_message: Log message when no content (e.g., "隐秘海域没有可执行内容")
        
        Returns:
            bool: True if handled (should return early), False otherwise
        """
        logger.info(f'{log_message}，准备结束当前任务')
        
        # Get the actual task name from config.task.command instead of class name
        # This ensures we get the correct task name even if self is an OperationSiren instance
        if hasattr(self.config, 'task') and hasattr(self.config.task, 'command'):
            task_name = self.config.task.command
        else:
            # Fallback to class name, but try to find the actual task class
            task_name = self.__class__.__name__
            # If it's OperationSiren, try to find the actual task from method resolution order
            if task_name == 'OperationSiren':
                # Find the first coin task class in MRO
                for cls in self.__class__.__mro__:
                    if cls.__name__ in self.ALL_COIN_TASKS:
                        task_name = cls.__name__
                        break
        
        logger.info(f'处理任务: {task_name}')
        
        # Check if we should try other tasks (yellow coins insufficient, only when smart scheduling enabled)
        should_try_other = False
        smart_enabled = getattr(self.config, 'OpsiScheduling_EnableSmartScheduling', False)
        if self.is_cl1_enabled and smart_enabled:
            yellow_coins = self.get_yellow_coins()
            cl1_preserve = self.config.cross_get(
                keys=self.CONFIG_PATH_CL1_PRESERVE,
                default=100000
            )
            if yellow_coins < cl1_preserve:
                should_try_other = True
                logger.info(f'黄币不足 ({yellow_coins} < {cl1_preserve})，尝试其他黄币补充任务')
        
        # 智能调度开启：关闭当前任务（并在需要时尝试其他补黄币任务）
        # 智能调度关闭：推迟当前任务到下次运行，而不是关闭
        with self.config.multi_set():
            if smart_enabled:
                # Disable current task and delay its NextRun to prevent immediate re-selection
                far_future = datetime.now() + timedelta(days=30)
                logger.info(f'智能调度已启用，禁用任务 {task_name} 并将下次运行时间延迟到 {far_future}')
                self.config.cross_set(keys=f'{task_name}.Scheduler.Enable', value=False)
                self.config.cross_set(keys=f'{task_name}.Scheduler.NextRun', value=far_future)
                
                if should_try_other:
                    # Try other tasks, but ensure current task stays disabled
                    self._try_other_coin_tasks(task_name)
                    # Re-disable current task and delay NextRun again to ensure it stays disabled
                    self.config.cross_set(keys=f'{task_name}.Scheduler.Enable', value=False)
                    self.config.cross_set(keys=f'{task_name}.Scheduler.NextRun', value=far_future)
            else:
                # 智能调度未启用：推迟当前任务，而不是关闭
                logger.info(f'智能调度未启用，对任务 {task_name} 执行延迟而非关闭')
                try:
                    # 针对不同任务做更友好的默认延迟策略
                    from module.config.utils import get_os_reset_remain  # type: ignore
                except ImportError:
                    get_os_reset_remain = None
                
                if task_name in ('OpsiObscure', 'OpsiAbyssal') and get_os_reset_remain is not None:
                    remain = get_os_reset_remain()
                    if remain == 0:
                        logger.info(f'{task_name} 没有更多可执行内容，距离大世界重置不足1天，延迟2.5小时后再运行')
                        self.config.task_delay(minute=150, server_update=True)
                    else:
                        logger.info(f'{task_name} 没有更多可执行内容，延迟到下次服务器刷新后再运行')
                        self.config.task_delay(server_update=True)
                else:
                    # 默认：延迟到下次服务器刷新
                    logger.info(f'{task_name} 没有更多可执行内容，延迟到下次服务器刷新后再运行')
                    self.config.task_delay(server_update=True)
        
        # Stop the current task
        self.config.task_stop()
        return True

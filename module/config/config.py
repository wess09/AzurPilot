"""配置管理核心模块。

定义 AzurLaneConfig 类，从 JSON 配置文件加载用户设置并与模板合并。
整合 ConfigUpdater、ManualConfig、GeneratedConfig、ConfigWatcher，
支持配置热重载、版本迁移和任务级配置绑定。
"""

import copy
import operator
import os
import platform
import sys
import threading
from datetime import datetime, timedelta

import pywebio

from module.base.filter import Filter
from module.config.config_generated import GeneratedConfig
from module.config.config_manual import ManualConfig, OutputConfig
from module.config.config_updater import ConfigUpdater, ensure_time, get_server_next_update, nearest_future
from module.config.deep import deep_get, deep_set
from module.config.time_source import now as current_time
from module.config.utils import DEFAULT_TIME, dict_to_kv, filepath_config, get_os_reset_remain, path_to_arg, is_good_gpu
from module.config.watcher import ConfigWatcher
from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger
from module.map.map_grids import SelectedGrids


class TaskEnd(Exception):
    """任务提前结束异常。

    当检测到需要延迟任务（如情绪不足）时抛出，
    由调度循环捕获并安排延迟重试。
    """
    pass


class Function:
    """任务调度函数描述对象。

    描述一个可调度任务的基本属性：是否启用、命令名称和下次执行时间。
    用于任务调度器的优先级排序和执行选择。

    Attributes:
        enable (bool): 任务是否启用。
        command (str): 任务命令名称，如 'Research'、'Commission'。
        next_run (datetime): 下次计划执行时间。
    """

    def __init__(self, data):
        self.enable = deep_get(data, keys="Scheduler.Enable", default=False)
        self.command = deep_get(data, keys="Scheduler.Command", default="Unknown")
        self.next_run = deep_get(data, keys="Scheduler.NextRun", default=DEFAULT_TIME)

    def __str__(self):
        enable = "Enable" if self.enable else "Disable"
        return f"{self.command} ({enable}, {str(self.next_run)})"

    __repr__ = __str__

    def __eq__(self, other):
        if not isinstance(other, Function):
            return False

        if self.command == other.command and self.next_run == other.next_run:
            return True
        else:
            return False


def name_to_function(name):
    """
    根据任务名称创建 Function 对象。

    Args:
        name (str): 任务名称。

    Returns:
        Function: 对应的 Function 实例。
    """
    function = Function({})
    function.command = name
    function.enable = True
    return function


class AzurLaneConfig(ConfigUpdater, ManualConfig, GeneratedConfig, ConfigWatcher):
    """碧蓝航线自动化配置管理器。

    项目的核心配置类，通过多重继承组合了：
    - ConfigUpdater: 配置版本升级和默认值合并
    - ManualConfig: 手动配置的属性访问
    - GeneratedConfig: 自动生成的配置属性（从 template.json 生成）
    - ConfigWatcher: 配置文件变更检测

    配置加载流程:
        1. 从 `config/{config_name}.json` 读取用户配置
        2. 与 args.json 默认值合并（ConfigUpdater.config_update）
        3. 执行版本迁移重定向（ConfigUpdater.config_redirect）
        4. 应用云手机覆盖值（_override）
        5. 绑定到当前任务（bind(task)）

    属性访问:
        配置路径格式为 `Task.Group.Argument`，通过 `__getattr__` 映射为
        `self.Group_Argument`（下划线分隔），如 `self.Research_PresetFilter`。

    属性修改:
        通过 `__setattr__` 拦截已绑定的属性，自动将修改写入配置文件。

    Attributes:
        stop_event (threading.Event | None): 停止事件，用于跨线程通知停止。
        bound (dict): 当前任务绑定的属性名到配置路径的映射。
        is_hoarding_task (bool): 是否为囤积任务（影响空闲行为）。
    """
    # 构造函数建立实例级 bound 前，__setattr__ 仍需要一个安全的查找兜底。
    # 这里只保存不可变语义上的空映射，不承载任何实例运行态。
    bound = {}

    def __setattr__(self, key, value):
        if key in self.bound:
            path = self.bound[key]
            self.modified[path] = value
            if self.auto_update:
                self.update()
        else:
            super().__setattr__(key, value)

    def __init__(self, config_name, task=None):
        # 读取 ./config/<config_name>.json
        self.config_name = config_name
        # 这些字段过去依赖子进程隔离而放在类上；单进程宿主必须每个实例独立。
        self.stop_event = None
        self.is_hoarding_task = True
        logger.attr("服务器", self.SERVER)
        # YAML 文件中的原始 JSON 数据
        self.data = {}
        # 已修改的参数。键：YAML 文件中的参数路径。值：修改后的值。
        # 所有变量修改都会记录在此处，并在 `save()` 方法中保存。
        self.modified = {}
        # 键：GeneratedConfig 中的参数名。值：`data` 中的路径。
        self.bound = {}
        # 是否在每次变量修改后立即写入
        self.auto_update = True
        # 强制覆盖的变量
        # 键：GeneratedConfig 中的参数名。值：修改后的值。
        self.overridden = {}
        # 调度器队列，在 `get_next_task()` 中更新，包含 Function 对象列表
        # pending_task：运行时间已到，但因任务调度尚未执行
        # waiting_task：运行时间未到，需要等待
        self.pending_task = []
        self.waiting_task = []
        # 待运行和绑定的任务
        # task 表示 AzurLaneAutoScript 类中要运行的函数名
        self.task: Function
        # 模板配置供开发工具使用
        self.is_template_config = config_name.startswith("template")

        if self.is_template_config:
            # 供开发工具使用
            logger.info("[配置] 使用模板配置，只读模式")
            self.auto_update = False
            self.task = name_to_function("template")
        elif not os.path.exists(filepath_config(config_name)):
            from module.config.utils import is_oobe_needed
            if is_oobe_needed():
                logger.warning(
                    "[配置] 未找到配置文件。"
                    "请运行 'python gui.py' 完成初始设置。"
                )
        self._disable_task_switch = False
        self.init_task(task)

    def init_task(self, task=None):
        if self.is_template_config:
            return

        self.load()
        if task is None:
            # 默认绑定 Alas，包含模拟器设置
            task = name_to_function("Alas")
        else:
            # 绑定特定任务，用于调试
            task = name_to_function(task)
        self.bind(task)
        self.task = task
        self.save()

    def load(self):
        self.data = self.read_file(self.config_name)
        self.config_override()

        for path, value in self.modified.items():
            deep_set(self.data, keys=path, value=value)

    def bind(self, func, func_list=None):
        """绑定任务及其配置参数。

        Args:
            func (str, Function): 要运行的任务名称或 Function 对象。
            func_list (list[str]): 需要绑定的任务列表。
        """
        if isinstance(func, Function):
            func = func.command
        # func_list: ["General", "Alas", <task_general>, <task>, *func_list]
        if func_list is None:
            func_list = []
        if func not in func_list:
            func_list.insert(0, func)
        if func.startswith("Opsi"):
            if "OpsiGeneral" not in func_list:
                func_list.insert(0, "OpsiGeneral")
        if (
            func.startswith("Event")
            or func.startswith("Raid")
            or func.startswith("Coalition")
            or func in ["MaritimeEscort", "GemsFarming", "ThreeOilLowCost"]
        ):
            if "EventGeneral" not in func_list:
                func_list.insert(0, "EventGeneral")
            if "TaskBalancer" not in func_list:
                func_list.insert(0, "TaskBalancer")
        if "Alas" not in func_list:
            func_list.insert(0, "Alas")
        if "General" not in func_list:
            func_list.insert(0, "General")
        logger.info(f"[配置] 绑定任务 {func_list}")

        # 绑定参数
        visited = set()
        self.bound.clear()
        for func in func_list:
            func_data = self.data.get(func, {})
            for group, group_data in func_data.items():
                for arg, value in group_data.items():
                    path = f"{group}.{arg}"
                    if path in visited:
                        continue
                    arg = path_to_arg(path)
                    super().__setattr__(arg, value)
                    self.bound[arg] = f"{func}.{path}"
                    visited.add(path)

        # 覆盖参数
        for arg, value in self.overridden.items():
            super().__setattr__(arg, value)


    @property
    def ocr_backend(self) -> str:
        val = self.Optimization_OcrBackend
        if val == 'auto':
            return 'onnxruntime'
        return val

    def ocr_model_version(self, name: str) -> str:
        if name == 'azur_lane':
            return self.Optimization_OcrModelVersionEnglish
        elif name == 'cn':
            return self.Optimization_OcrModelVersionChinese
        elif name in ['azur_lane_jp', 'jp']:
            return self.Optimization_OcrModelVersionJapanese
        elif name == 'tw':
            return self.Optimization_OcrModelVersionTraditionalChinese
        else:
            return 'auto'

    @property
    def ocr_device(self) -> str:
        val = self.Optimization_OcrDevice
        if val == 'auto':
            if self.ocr_backend == 'onnxruntime':
                if sys.platform == 'darwin' and platform.machine() == 'arm64':
                    return 'ane'
                if sys.platform == 'win32':
                    # Windows ML 会自行筛选 NPU、独显和 CPU，不应仅以显存决定是否尝试。
                    return 'auto'
                return 'gpu' if is_good_gpu() else 'cpu'
            else:
                # ncnn 后端：检查 Vulkan GPU 可用性
                from module.ocr.ncnn_ocr import has_ncnn_vulkan_gpu
                return 'gpu' if has_ncnn_vulkan_gpu() else 'cpu'

        if self.ocr_backend == 'ncnn' and val in {
            'qnn_npu',
            'openvino_npu',
            'openvino_gpu',
            'openvino_cpu',
        }:
            return 'cpu'
        return val

    @property
    def hoarding(self):
        minutes = int(
            deep_get(
                self.data, keys="Alas.Optimization.TaskHoardingDuration", default=0
            )
        )
        return timedelta(minutes=max(minutes, 0))

    @property
    def close_game(self):
        return deep_get(
            self.data, keys="Alas.Optimization.CloseGameDuringWait", default=False
        )

    @property
    def is_actual_task(self):
        return self.task.command.lower() not in ['alas', 'template']

    def get_next_task(self):
        """计算任务队列，设置 pending_task 和 waiting_task。"""
        pending = []
        waiting = []
        error = []
        now = current_time()
        if self.is_hoarding_task:
            now -= self.hoarding
        for func in self.data.values():
            func = Function(func)
            if not func.enable:
                continue
            if not isinstance(func.next_run, datetime):
                error.append(func)
            elif func.next_run < now:
                pending.append(func)
            else:
                waiting.append(func)

        f = Filter(regex=r"(.*)", attr=["command"])
        f.load(self.SCHEDULER_PRIORITY)
        if pending:
            pending = f.apply(pending)
        if waiting:
            waiting = f.apply(waiting)
            waiting = sorted(waiting, key=operator.attrgetter("next_run"))
        if error:
            pending = error + pending

        self.pending_task = pending
        self.waiting_task = waiting

    def get_next(self):
        """获取下一个待运行的任务。

        Returns:
            Function: 待运行的任务。
        """
        self.get_next_task()

        if self.pending_task:
            self.is_hoarding_task = False
            logger.info(f"[配置] 待处理任务: {[f.command for f in self.pending_task]}")
            task = self.pending_task[0]
            logger.attr("任务", task)
            return task
        else:
            self.is_hoarding_task = True

        if self.waiting_task:
            logger.info("[配置] 没有待处理任务")
            task = copy.deepcopy(self.waiting_task[0])
            task.next_run = (task.next_run + self.hoarding).replace(microsecond=0)
            logger.attr("任务", task)
            return task
        else:
            logger.critical("[Config] 没有等待或待处理的任务")
            logger.critical("[Config] 请启用至少一个任务")
            raise RequestHumanTakeover

    def save(self, mod_name='alas'):
        if not self.modified:
            return False

        for path, value in self.modified.items():
            deep_set(self.data, keys=path, value=value)

        logger.info(
            f"[配置] 保存配置 {filepath_config(self.config_name, mod_name)}, {dict_to_kv(self.modified)}"
        )
        # 不要使用 self.modified = {}，那会创建新对象。
        self.modified.clear()
        self.write_file(self.config_name, data=self.data)

    def update(self):
        self.load()
        self.config_override()
        self.bind(getattr(self, '_bind_task_override', self.task))
        self.save()

    def override(self, **kwargs):
        now = current_time().replace(microsecond=0)
        limited = set()

        def limit_next_run(tasks, limit):
            for task in tasks:
                if task in limited:
                    continue
                limited.add(task)
                next_run = deep_get(
                    self.data, keys=f"{task}.Scheduler.NextRun", default=None
                )
                if isinstance(next_run, datetime) and next_run > limit:
                    deep_set(self.data, keys=f"{task}.Scheduler.NextRun", value=now)

        limit_next_run(["Commission", "Reward"], limit=now + timedelta(hours=12, seconds=-1))
        limit_next_run(["Research"], limit=now + timedelta(hours=24, seconds=-1))
        limit_next_run(["OpsiExplore", "OpsiCrossMonth", "OpsiVoucher", "OpsiMonthBoss", "OpsiShop"],
                       limit=now + timedelta(days=31, seconds=-1))
        limit_next_run(["OpsiArchive"], limit=now + timedelta(days=7, seconds=-1))
        # 防溢出任务会按当前行动力恢复到 200 的时间延后，最长可能超过 24 小时。
        limit_next_run(["OpsiPreventActionPointOverflow"], limit=now + timedelta(hours=48, seconds=-1))
        # IslandPearlSell 按周调度，合法 NextRun 可能超过 24 小时。
        limit_next_run(["IslandPearlSell"], limit=now + timedelta(days=8, seconds=-1))
        # 通用兜底保留 24 小时调度的少量误差空间，避免刚好延后一天的任务被重置。
        limit_next_run(
            [task for task in self.args.keys() if task != "OpsiPreventActionPointOverflow"],
            limit=now + timedelta(hours=25, seconds=-1),
        )

        """
        强制覆盖任意配置项。

        被覆盖的变量即使从 YAML 文件重新加载配置也会保持覆盖状态。
        注意：此方法不可逆。
        """
        for arg, value in kwargs.items():
            self.overridden[arg] = value
            super().__setattr__(arg, value)

    config_override = override

    def set_record(self, **kwargs):
        """设置值并自动记录当前时间。

        Args:
            **kwargs: 例如 `Emotion1_Value=150` 会同时设置
                `Emotion1_Value=150` 和 `Emotion1_Record=now()`。
        """
        with self.multi_set():
            for arg, value in kwargs.items():
                record = arg.replace("Value", "Record")
                self.__setattr__(arg, value)
                self.__setattr__(record, current_time().replace(microsecond=0))

    def multi_set(self):
        """批量设置多个参数，但只保存一次。

        Examples:
            with self.config.multi_set():
                self.config.foo1 = 1
                self.config.foo2 = 2
        """
        return MultiSetWrapper(main=self)

    def cross_get(self, keys, default=None):
        """从其他任务获取配置。

        Args:
            keys (str, list[str]): 配置路径，如 `{task}.Scheduler.Enable`。
            default: 默认值。

        Returns:
            Any: 配置值。
        """
        return deep_get(self.data, keys=keys, default=default)

    def cross_set(self, keys, value):
        """设置其他任务的配置。

        Args:
            keys (str, list[str]): 配置路径，如 `{task}.Scheduler.Enable`。
            value (Any): 要设置的值。
        """
        self.modified[keys] = value
        if self.auto_update:
            self.update()

    def task_delay(self, success=None, server_update=None, target=None, minute=None, task=None):
        """设置 Scheduler.NextRun，延迟任务的下次运行时间。

        至少需要设置一个参数。如果设置了多个参数，取最近的时间。

        Args:
            success (bool):
                True 表示延迟 Scheduler.SuccessInterval，
                False 表示延迟 Scheduler.FailureInterval。
            server_update (bool, list, str):
                True 表示延迟到最近的 Scheduler.ServerUpdate。
                list 或 str 类型表示延迟到指定的服务器更新时间。
            target (datetime.datetime, str, list):
                延迟到指定时间。
            minute (int, float, tuple):
                延迟指定分钟数。
            task (str):
                跨任务设置。None 表示当前任务。
        """

        def ensure_delta(delay):
            return timedelta(seconds=int(ensure_time(delay, precision=3) * 60))

        run = []
        if success is not None:
            interval = (
                self.Scheduler_SuccessInterval
                if success
                else self.Scheduler_FailureInterval
            )
            run.append(current_time() + ensure_delta(interval))
        if server_update is not None:
            if server_update is True:
                server_update = self.Scheduler_ServerUpdate
            run.append(get_server_next_update(server_update))
        if target is not None:
            target = [target] if not isinstance(target, list) else target
            target = nearest_future(target)
            run.append(target)
        if minute is not None:
            run.append(current_time() + ensure_delta(minute))

        if len(run):
            run = min(run).replace(microsecond=0)
            kv = dict_to_kv(
                {
                    "success": success,
                    "server_update": server_update,
                    "target": target,
                    "minute": minute,
                },
                allow_none=False,
            )
            if task is None:
                task = self.task.command
            logger.info(f"[配置] 延迟任务 `{task}` 到 {run} ({kv})")
            self.modified[f'{task}.Scheduler.NextRun'] = run
            self.update()
        else:
            raise ScriptError(
                "[配置] delay_next_run 缺少参数，应至少设置一个"
            )

    def opsi_task_delay(
            self,
            recon_scan=False,
            submarine_call=False,
            ap_limit=False,
            cl1_preserve=False,
            ap_limit_minutes=None,
    ):
        """延迟大世界所有任务的 NextRun。

        Args:
            recon_scan (bool): True 表示延迟所有需要侦察扫描的任务 27 分钟。
            submarine_call (bool): True 表示延迟所有需要呼叫潜艇的任务 60 分钟。
            ap_limit (bool): True 表示延迟所有需要行动力的任务 360 分钟。
            cl1_preserve (bool): True 表示延迟所有需要大量行动力的任务 360 分钟。
            ap_limit_minutes (int): 已知行动力恢复时间时使用该值。
        """
        if not recon_scan and not submarine_call and not ap_limit and not cl1_preserve:
            return None
        kv = dict_to_kv(
            {
                "recon_scan": recon_scan,
                "submarine_call": submarine_call,
                "ap_limit": ap_limit,
                "cl1_preserve": cl1_preserve,
                "ap_limit_minutes": ap_limit_minutes,
            },
            allow_none=False,
        )

        def delay_tasks(task_list, minutes):
            next_run = current_time().replace(microsecond=0) + timedelta(
                minutes=minutes
            )
            for task in task_list:
                keys = f"{task}.Scheduler.NextRun"
                current = deep_get(self.data, keys=keys, default=DEFAULT_TIME)
                if current < next_run:
                    logger.info(f"[配置-大世界] 延迟任务 `{task}` 到 {next_run} ({kv})")
                    self.modified[keys] = next_run

        def is_submarine_call(task):
            return (
                deep_get(self.data, keys=f"{task}.OpsiFleet.Submarine", default=False)
                or "submarine"
                in deep_get(
                    self.data, keys=f"{task}.OpsiFleetFilter.Filter", default=""
                ).lower()
            )

        def is_force_run(task):
            return (
                deep_get(self.data, keys=f"{task}.OpsiExplore.ForceRun", default=False)
                or deep_get(
                    self.data, keys=f"{task}.OpsiObscure.ForceRun", default=False
                )
                or deep_get(
                    self.data, keys=f"{task}.OpsiAbyssal.ForceRun", default=False
                )
                or deep_get(
                    self.data, keys=f"{task}.OpsiStronghold.ForceRun", default=False
                )
            )

        def is_special_radar(task):
            return deep_get(
                self.data, keys=f"{task}.OpsiExplore.SpecialRadar", default=False
            )

        if recon_scan:
            tasks = SelectedGrids(["OpsiExplore", "OpsiObscure", "OpsiStronghold"])
            tasks = tasks.delete(tasks.filter(is_force_run)).delete(
                tasks.filter(is_special_radar)
            )
            delay_tasks(tasks, minutes=27)
        if submarine_call:
            tasks = SelectedGrids(
                [
                    "OpsiExplore",
                    "OpsiDaily",
                    "OpsiObscure",
                    "OpsiAbyssal",
                    "OpsiArchive",
                    "OpsiStronghold",
                    "OpsiMeowfficerFarming",
                    "OpsiMonthBoss",
                ]
            )
            tasks = tasks.filter(is_submarine_call).delete(tasks.filter(is_force_run))
            delay_tasks(tasks, minutes=60)
        if ap_limit:
            tasks = SelectedGrids(
                [
                    "OpsiExplore",
                    "OpsiDaily",
                    "OpsiObscure",
                    "OpsiAbyssal",
                    "OpsiStronghold",
                    # 延迟 OpsiArchive，因为 OpsiArchive 和 OpsiDaily 共享同一任务列表，
                    # 虽然进入不需要行动力。
                    "OpsiArchive",
                    "OpsiMeowfficerFarming",
                ]
            )
            if ap_limit_minutes is not None:
                delay_tasks(tasks, minutes=ap_limit_minutes)
            elif get_os_reset_remain() > 0:
                delay_tasks(tasks, minutes=360)
            else:
                logger.info("[配置-大世界] 距离大世界重置不足1天，延迟2.5小时")
                delay_tasks(tasks, minutes=150)
        if cl1_preserve:
            tasks = SelectedGrids(
                [
                    "OpsiObscure",
                    "OpsiAbyssal",
                    "OpsiStronghold",
                    "OpsiMeowfficerFarming",
                ]
            )
            delay_tasks(tasks, minutes=360)

        self.update()

    def task_call(self, task, force_call=True):
        """调用另一个任务运行。

        该任务会在当前任务完成后运行，但可能不会实际执行，因为：
        - 其他任务可能根据 SCHEDULER_PRIORITY 优先执行
        - 任务可能被用户禁用

        Args:
            task (str): 要调用的任务名称，如 `Restart`。
            force_call (bool): 是否强制调用。

        Returns:
            bool: 是否成功调用。
        """
        if deep_get(self.data, keys=f"{task}.Scheduler.NextRun", default=None) is None:
            raise ScriptError(f"[配置] 要调用的任务: `{task}` 在用户配置中不存在")

        if force_call or self.is_task_enabled(task):
            logger.info(f"[配置] 任务调用: {task}")
            self.modified[f"{task}.Scheduler.NextRun"] = current_time().replace(
                microsecond=0
            )
            self.modified[f"{task}.Scheduler.Enable"] = True
            if self.auto_update:
                self.update()
            return True
        else:
            logger.info(f"[配置] 任务调用: {task} (因用户禁用而跳过)")
            return False

    @staticmethod
    def task_stop(message=""):
        """停止当前任务。

        Raises:
            TaskEnd: 始终抛出此异常以中断任务。
        """
        try:
            from module.base.async_executor import async_executor
            async_executor.flush(timeout=2.0)
        except Exception:
            pass

        if message:
            raise TaskEnd(message)
        else:
            raise TaskEnd

    def task_switched(self):
        """检查是否需要切换任务。

        Returns:
            bool: 是否需要切换任务。
        """
        # 更新事件
        if self.stop_event is not None:
            if self.stop_event.is_set():
                return True
        prev = getattr(self, '_task_switch_owner', self.task)
        self.load()
        new = self.get_next()
        if prev == new:
            logger.info(f"[配置] 继续任务 `{new}`")
            return False
        else:
            logger.info(f"[配置] 切换任务 `{prev}` 到 `{new}`")
            return True

    def check_task_switch(self, message=""):
        """当任务切换时停止当前任务。

        Raises:
            TaskEnd: 任务已切换时抛出此异常。
        """
        # 如果设置了禁用任务切换标志，则跳过检查
        if getattr(self, '_disable_task_switch', False):
            logger.info('[配置] 任务切换检查已临时禁用')
            return
        
        if self.task_switched():
            self.task_stop(message=message)

    def is_task_enabled(self, task):
        return bool(self.cross_get(keys=[task, 'Scheduler', 'Enable'], default=False))

    @property
    def campaign_name(self):
        """保存掉落记录时使用的子目录名称。"""
        name = self.Campaign_Name.lower().replace("-", "_")
        if name[0].isdigit():
            name = "campaign_" + str(name)
        if self.Campaign_Mode == "hard":
            name += "_hard"
        return name

    """
    以下配置和方法用于兼容旧版本。
    """

    def merge(self, other):
        """合并另一个配置到当前配置。

        Args:
            other (AzurLaneConfig, Config): 要合并的配置对象。

        Returns:
            AzurLaneConfig: 合并后的配置。
        """
        # 由于所有任务独立运行，无需分离配置
        # config = copy.copy(self)
        config = self

        for attr in dir(config):
            if attr.endswith("__"):
                continue
            if hasattr(other, attr):
                value = other.__getattribute__(attr)
                if value is not None:
                    config.__setattr__(attr, value)

        return config

    @property
    def DEVICE_SCREENSHOT_METHOD(self):
        return self.Emulator_ScreenshotMethod

    @property
    def DEVICE_CONTROL_METHOD(self):
        return self.Emulator_ControlMethod

    @property
    def FLEET_1(self):
        return self.Fleet_Fleet1

    @property
    def FLEET_2(self):
        return self.Fleet_Fleet2

    @FLEET_2.setter
    def FLEET_2(self, value):
        self.override(Fleet_Fleet2=value)

    @property
    def SUBMARINE(self):
        return self.Submarine_Fleet

    @SUBMARINE.setter
    def SUBMARINE(self, value):
        self.override(Submarine_Fleet=value)

    _fleet_boss = 0

    @property
    def FLEET_BOSS(self):
        if self._fleet_boss:
            return self._fleet_boss
        if self.Fleet_Fleet2:
            if self.Fleet_FleetOrder in [
                "fleet1_mob_fleet2_boss",
                "fleet1_boss_fleet2_mob",
            ]:
                return 2
            else:
                return 1
        else:
            return 1

    @FLEET_BOSS.setter
    def FLEET_BOSS(self, value):
        self._fleet_boss = value

    def temporary(self, **kwargs):
        """临时覆盖部分设置，之后恢复。

        用法:
            backup = self.config.cover(ENABLE_DAILY_REWARD=False)
            # do_something()
            backup.recover()

        Args:
            **kwargs: 要临时覆盖的配置项。

        Returns:
            ConfigBackup: 备份对象，可用于恢复原配置。
        """
        backup = ConfigBackup(config=self)
        backup.cover(**kwargs)
        return backup


pywebio.output.Output = OutputConfig
pywebio.pin.Output = OutputConfig


class ConfigBackup:
    def __init__(self, config):
        """
        Args:
            config (AzurLaneConfig): 要备份的配置对象。
        """
        self.config = config
        self.backup = {}
        self.kwargs = {}

    def cover(self, **kwargs):
        self.kwargs = kwargs
        for key, value in kwargs.items():
            self.backup[key] = self.config.__getattribute__(key)
            self.config.__setattr__(key, value)

    def recover(self):
        for key, value in self.backup.items():
            self.config.__setattr__(key, value)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.recover()


class MultiSetWrapper:
    def __init__(self, main):
        """
        Args:
            main (AzurLaneConfig): 配置实例。
        """
        self.main = main
        self.in_wrapper = False

    def __enter__(self):
        if self.main.auto_update:
            self.main.auto_update = False
        else:
            self.in_wrapper = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.in_wrapper:
            self.main.update()
            self.main.auto_update = True

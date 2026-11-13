"""AzurPilot TUI 桥接后端。

负责与 ConfigService、RuntimeService、ProcessManager 及 State 对接，
为 TUI 前端提供多实例状态查询、任务计划时间表、日志增量拉取、
进程生命周期控制以及任务功能配置查看与修改能力。

前端定时器每秒都会触发状态刷新，因此这里把「轻量状态」与「完整总览」分开：
`list_statuses()` 只读取进程管理器内存状态，`get_overview()` 才会读取配置与统计库。
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from module.api.config_service import ConfigService
from module.api.protocol import ApiError
from module.api.runtime_service import STATES, RuntimeService
from module.runtime.process_manager import ProcessManager
from module.runtime.setting import State
from module.runtime.updater import updater
from module.submodule.utils import get_available_func

# 资源键 → 中文名。Dashboard 的 `_info.name` 翻译缺失时用来兜底，
# 避免资源看板把每项都显示成 "name"。
RESOURCE_LABELS = {
    "Oil": "石油",
    "Coin": "物资",
    "Gem": "钻石",
    "Cube": "心智魔方",
    "Pt": "活动 PT",
    "Core": "核心数据",
    "Medal": "荣誉勋章",
    "Merit": "功勋",
    "GuildCoin": "舰队币",
    "ActionPoint": "行动力",
    "YellowCoin": "作战补给凭证",
    "PurpleCoin": "特别兑换凭证",
}

# 只读、隐藏或内部状态存储，均不暴露给配置编辑器。
HIDDEN_DISPLAY = ('hide', 'disabled', 'readonly')
HIDDEN_TYPES = ('storage', 'stored', 'state', 'lock')
# 任务列表里排除的内部模块，它们没有可调度的 Scheduler 分组。
EXCLUDED_TASKS = ('Dashboard', 'Storage', 'Gui')


class TUIBackend:
    """TUI 运行时桥接后端。

    Attributes:
        config_service (ConfigService): 配置管理服务。
        runtime_service (RuntimeService): 运行时管理服务。
        current_instance (str): 当前选中的活动实例名称。
    """

    def __init__(self, root: Optional[Path] = None, default_instance: Optional[str] = None) -> None:
        """初始化 TUI 桥接后端并确保全局多进程管理器就绪。

        Args:
            root (Optional[Path]): 仓库根目录，缺省时使用 ConfigService 默认 ROOT。
            default_instance (Optional[str]): 启动时指定的默认实例名称。
        """
        # 确保 State.manager 跨进程环境完成初始化，避免启动子进程时报 NoneType Queue 异常
        self._ensure_runtime_state()

        self.config_service = ConfigService(root=root) if root else ConfigService()
        self.runtime_service = RuntimeService(self.config_service)

        # 确定初始活动实例
        instances = self.config_service.names()
        if default_instance and default_instance in instances:
            self.current_instance = default_instance
        elif instances:
            self.current_instance = instances[0]
        else:
            self.current_instance = "alas"

    @staticmethod
    def _ensure_runtime_state() -> None:
        """确保跨进程 SyncManager 及热重载事件已经初始化。"""
        if State.manager is None:
            try:
                State.init()
            except Exception:
                pass
        if State.manager is None:
            import multiprocessing
            try:
                State.manager = multiprocessing.Manager()
            except Exception:
                pass
        if State.manager is not None and getattr(updater, "event", None) is None:
            updater.event = State.manager.Event()

    # ------------------------------------------------------------------
    # 实例与状态
    # ------------------------------------------------------------------
    def list_instances(self) -> List[Dict[str, Any]]:
        """获取所有可用配置实例的状态与元数据列表。"""
        try:
            return self.runtime_service.instances()
        except Exception:
            names = self.config_service.names()
            return [
                {"name": name, "status": "stopped", "currentTask": None, "serial": "auto", "server": "cn"}
                for name in names
            ]

    def list_statuses(self) -> List[Dict[str, Any]]:
        """只读取进程管理器内存状态，供高频轮询使用。

        相比 `list_instances()`，本方法不读取任何配置文件，
        可以安全地每秒调用而不会造成 IO 抖动。

        Returns:
            List[Dict[str, Any]]: 每项包含 name、status、currentTask。
        """
        result: List[Dict[str, Any]] = []
        try:
            names = self.config_service.names()
        except (OSError, ApiError):
            return result

        for name in names:
            manager = ProcessManager._processes.get(name)
            try:
                state = manager.state if manager is not None else 2
            except Exception:
                state = 3
            status = STATES.get(state, "stopped")
            current_task = getattr(manager, "current_task", None) if status == "running" else None
            result.append({"name": name, "status": status, "currentTask": current_task})
        return result

    def get_status(self, instance: Optional[str] = None) -> Dict[str, Any]:
        """获取单个实例的轻量状态。"""
        target = instance or self.current_instance
        for item in self.list_statuses():
            if item["name"] == target:
                return item
        return {"name": target, "status": "stopped", "currentTask": None}

    def switch_instance(self, instance: str) -> bool:
        """切换当前活动实例。"""
        try:
            names = self.config_service.names()
        except (OSError, ApiError):
            return False
        if instance in names:
            self.current_instance = instance
            return True
        return False

    def load_dashboard(self, instance: Optional[str] = None) -> Dict[str, Any]:
        """一次性收集完整总览与全部实例状态，供后台线程调用。

        Args:
            instance (Optional[str]): 目标实例，缺省使用当前活动实例。

        Returns:
            Dict[str, Any]: 包含 instance、instances、overview 三个键的字典。
        """
        target = instance or self.current_instance
        return {
            "instance": target,
            "instances": self.list_statuses(),
            "overview": self.get_overview(target),
        }

    def get_overview(self, instance: Optional[str] = None) -> Dict[str, Any]:
        """获取指定实例的总览信息。

        在运行时服务的基础上补充未启用任务，使前端可以重新启用它们；
        每个任务都会带上 `enabled` 与翻译后的 `title`。
        """
        target = instance or self.current_instance
        try:
            data = self.runtime_service.overview(target)
        except ApiError as e:
            return self._empty_overview(target, e.message)
        except Exception as e:
            return self._empty_overview(target, str(e))

        schedulable = self._schedulable_tasks()
        # 只保留仍能通过 args.json 校验的任务，避免历史任务出现在表格里却无法开关。
        data["tasks"] = [task for task in data.get("tasks", []) if task.get("name") in schedulable]
        for task_item in data["tasks"]:
            task_item["title"] = self.get_task_title(task_item.get("name", ""))
            task_item["enabled"] = True

        for resource in data.get("resources", []):
            resource["label"] = self._resource_label(resource)

        known = {task.get("name") for task in data["tasks"]}
        data["tasks"].extend(self._disabled_tasks(target, known, schedulable))
        return data

    @staticmethod
    def _resource_label(resource: Dict[str, Any]) -> str:
        """返回资源显示名，翻译缺失时退回内置中文映射或原始键名。"""
        label = str(resource.get("label") or "")
        name = str(resource.get("name") or "")
        if label and label not in ("name", name):
            return label
        return RESOURCE_LABELS.get(name, name or "资源")

    def _schedulable_tasks(self) -> set:
        """收集所有带 Scheduler.Enable 的任务名。"""
        result = set()
        for task, groups in self.config_service.args.items():
            if not isinstance(groups, dict):
                continue
            scheduler = groups.get("Scheduler")
            if isinstance(scheduler, dict) and "Enable" in scheduler:
                result.add(task)
        return result

    def _empty_overview(self, target: str, message: str) -> Dict[str, Any]:
        """构造占位总览，保证前端始终拿到固定结构。"""
        return {
            "instance": target,
            "status": "error",
            "error": message,
            "tasks": [],
            "resources": [],
            "emulator": {},
        }

    def _disabled_tasks(self, instance: str, known: set, schedulable: set) -> List[Dict[str, Any]]:
        """从配置中补齐未启用的可调度任务。"""
        try:
            data, _ = self.config_service.read(instance)
        except (ApiError, OSError, ValueError):
            return []

        tasks: List[Dict[str, Any]] = []
        for name, groups in data.items():
            if name in known or name not in schedulable or not isinstance(groups, dict):
                continue
            scheduler = groups.get("Scheduler")
            if not isinstance(scheduler, dict) or "Enable" not in scheduler:
                continue
            tasks.append({
                "name": name,
                "title": self.get_task_title(name),
                "nextRun": str(scheduler.get("NextRun", "")),
                "pending": False,
                "state": "disabled",
                "enabled": False,
            })
        tasks.sort(key=lambda item: item["name"])
        return tasks

    # ------------------------------------------------------------------
    # 国际化标题
    # ------------------------------------------------------------------
    def get_task_title(self, task: str) -> str:
        """获取任务的人类友好中文标题。"""
        if not task:
            return ""
        translations = getattr(self.config_service, "translations", {})
        task_info = translations.get("Task", {}).get(task)
        if isinstance(task_info, dict) and task_info.get("name"):
            return task_info["name"]
        translated = self.config_service.translate(f"{task}._info.name")
        return translated if translated and translated != "_info.name" else task

    def get_group_title(self, group: str) -> str:
        """获取参数组的中文标题。"""
        translations = getattr(self.config_service, "translations", {})
        group_info = translations.get(group, {}).get("_info")
        if isinstance(group_info, dict) and group_info.get("name"):
            return group_info["name"]
        return group

    def get_arg_title_and_help(self, group: str, arg: str) -> Tuple[str, str]:
        """获取参数项的中文显示名与帮助说明。"""
        translations = getattr(self.config_service, "translations", {})
        arg_info = translations.get(group, {}).get(arg, {})
        title = arg_info.get("name", arg) if isinstance(arg_info, dict) else arg
        help_text = arg_info.get("help", "") if isinstance(arg_info, dict) else ""
        return title, help_text

    def get_option_title(self, group: str, arg: str, opt: Any) -> str:
        """获取下拉选项在国际化字典中的翻译。"""
        opt_str = str(opt)
        translations = getattr(self.config_service, "translations", {})
        arg_info = translations.get(group, {}).get(arg, {})
        if isinstance(arg_info, dict) and opt_str in arg_info:
            return arg_info[opt_str]
        return opt_str

    # ------------------------------------------------------------------
    # 运行控制
    # ------------------------------------------------------------------
    def start_scheduler(self, instance: Optional[str] = None) -> Tuple[bool, str]:
        """启动实例的主调度器。"""
        self._ensure_runtime_state()
        target = instance or self.current_instance
        try:
            self.runtime_service.start(target, task=None)
            return True, f"实例 [{target}] 主调度器已启动"
        except ApiError as e:
            return False, f"启动失败: {e.message}"
        except Exception as e:
            return False, f"启动异常: {e}"

    def start_task(self, task: str, instance: Optional[str] = None) -> Tuple[bool, str]:
        """单独执行指定的功能任务。"""
        self._ensure_runtime_state()
        target = instance or self.current_instance
        try:
            self.runtime_service.start(target, task=task)
            task_title = self.get_task_title(task)
            return True, f"实例 [{target}] 单任务 [{task_title}] 已启动"
        except ApiError as e:
            return False, f"任务启动失败: {e.message}"
        except Exception as e:
            return False, f"任务启动异常: {e}"

    def stop_instance(self, instance: Optional[str] = None) -> Tuple[bool, str]:
        """停止指定实例的运行。"""
        target = instance or self.current_instance
        try:
            self.runtime_service.stop(target)
            return True, f"实例 [{target}] 已停止"
        except ApiError as e:
            return False, f"停止失败: {e.message}"
        except Exception as e:
            return False, f"停止异常: {e}"

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def get_logs_delta(
        self, instance: Optional[str] = None, after: int = 0
    ) -> Tuple[int, List[Dict[str, Any]], bool]:
        """增量拉取日志，并显式区分「无新增」与「缓存已重置」。

        Args:
            instance (Optional[str]): 实例名称；缺省使用当前活动实例。
            after (int): 客户端持有的日志序列号。

        Returns:
            Tuple[int, List[Dict[str, Any]], bool]: (最新游标, 新增条目, 是否重置)。
        """
        target = instance or self.current_instance
        try:
            res = self.runtime_service.logs(target, after=after)
            cursor = int(res.get("cursor", after))
            entries = list(res.get("entries") or [])
            return cursor, entries, bool(res.get("reset", False))
        except Exception:
            return after, [], False

    def get_logs(self, instance: Optional[str] = None, after: int = 0) -> Tuple[int, List[Dict[str, Any]]]:
        """增量拉取指定实例的新日志记录。"""
        cursor, entries, _ = self.get_logs_delta(instance, after)
        return cursor, entries

    # ------------------------------------------------------------------
    # 任务与配置
    # ------------------------------------------------------------------
    def get_available_tasks(self) -> List[Tuple[str, str]]:
        """获取支持单独执行的功能任务列表。"""
        try:
            funcs = get_available_func()
        except Exception:
            return []
        return [(func, self.get_task_title(func)) for func in funcs]

    def get_all_configurable_tasks(self) -> List[Tuple[str, str]]:
        """获取所有可供配置的任务模块列表（按主功能优先级排序）。"""
        tasks: List[Tuple[str, str]] = []
        menu = getattr(self.config_service, "menu", {})
        seen = set()

        # 核心常用任务优先置顶
        priority_tasks = [
            "Main", "Commission", "Research", "Daily", "Hard", "Exercise",
            "Dorm", "Meowfficer", "Reward", "GeneralShop", "GuildLogistics",
            "OpsiGeneral", "OpsiExplore", "Alas", "General", "Restart"
        ]
        for t in priority_tasks:
            if t in self.config_service.args:
                seen.add(t)
                tasks.append((t, self.get_task_title(t)))

        # 按照 menu 结构加载其余任务
        for _, group_info in menu.items():
            if isinstance(group_info, dict):
                sub_tasks = group_info.get("tasks", [])
                if isinstance(sub_tasks, list):
                    for t in sub_tasks:
                        if t not in seen and t in self.config_service.args:
                            seen.add(t)
                            tasks.append((t, self.get_task_title(t)))

        # 补全其余合法任务
        for t in self.config_service.args.keys():
            if t not in seen and t not in EXCLUDED_TASKS:
                seen.add(t)
                tasks.append((t, self.get_task_title(t)))

        return tasks

    def get_task_config_schema(self, task: str, instance: Optional[str] = None) -> List[Dict[str, Any]]:
        """解析指定任务的所有可配置分组与参数项。

        Args:
            task (str): 任务名称（如 Commission、Research、Combat 等）。
            instance (Optional[str]): 实例名称；缺省使用当前活动实例。

        Returns:
            List[Dict[str, Any]]: 包含各分组及各参数详情的字典列表。
        """
        target = instance or self.current_instance
        task_meta = self.config_service.args.get(task, {})
        current_data, _ = self.config_service.read(target)
        task_data = current_data.get(task, {})

        groups_result = []
        for group_name, args_dict in task_meta.items():
            if not isinstance(args_dict, dict) or group_name == "Storage":
                continue

            group_title = self.get_group_title(group_name)
            items = []
            for arg_name, meta in args_dict.items():
                if not isinstance(meta, dict):
                    continue

                display = meta.get("display")
                kind = meta.get("type", "input")
                # 过滤只读、隐藏与内部状态存储
                if display in HIDDEN_DISPLAY or kind in HIDDEN_TYPES:
                    continue

                arg_title, arg_help = self.get_arg_title_and_help(group_name, arg_name)
                current_val = task_data.get(group_name, {}).get(arg_name, meta.get("value"))

                # 选项翻译
                options = meta.get("option")
                option_list = None
                if options:
                    option_list = [(opt, self.get_option_title(group_name, arg_name, opt)) for opt in options]

                items.append({
                    "path": f"{task}.{group_name}.{arg_name}",
                    "group": group_name,
                    "arg": arg_name,
                    "title": arg_title,
                    "help": arg_help,
                    "type": kind,
                    "mode": meta.get("mode"),
                    "valuetype": meta.get("valuetype"),
                    "value": current_val,
                    "default": meta.get("value"),
                    "options": option_list,
                })

            if items:
                groups_result.append({
                    "group_name": group_name,
                    "group_title": group_title,
                    "items": items,
                })

        return groups_result

    def toggle_task_enable(self, task: str, instance: Optional[str] = None) -> Tuple[bool, str, bool]:
        """一键切换指定任务的启用/禁用状态 (Scheduler.Enable)。

        Args:
            task (str): 任务名称。
            instance (Optional[str]): 实例名称；缺省使用当前活动实例。

        Returns:
            Tuple[bool, str, bool]: (是否成功, 提示消息, 切换后的新状态)。
        """
        target = instance or self.current_instance
        title = self.get_task_title(task)

        scheduler = self.config_service.args.get(task, {}).get("Scheduler", {})
        if not isinstance(scheduler, dict) or "Enable" not in scheduler:
            return False, f"任务 [{title}] 不支持计划开关", False

        try:
            data, revision = self.config_service.read(target)
            curr_enable = bool(data.get(task, {}).get("Scheduler", {}).get("Enable", False))
            new_enable = not curr_enable

            path = f"{task}.Scheduler.Enable"
            self.config_service.patch(target, revision, [SimpleNamespace(path=path, value=new_enable)])
            status_desc = "已启用" if new_enable else "已禁用"
            return True, f"任务 [{title}] {status_desc}", new_enable
        except ApiError as e:
            return False, f"切换任务开关失败: {e.message}", False
        except Exception as e:
            return False, f"切换任务开关失败: {e}", False

    def save_task_config(self, changes: List[Dict[str, Any]], instance: Optional[str] = None) -> Tuple[bool, str]:
        """批量提交保存任务配置修改。

        Args:
            changes (List[Dict[str, Any]]): 包含 path 和 value 的修改项列表。
            instance (Optional[str]): 实例名称；缺省使用当前活动实例。

        Returns:
            Tuple[bool, str]: (是否成功, 提示消息)。
        """
        target = instance or self.current_instance
        if not changes:
            return True, "配置未发生变更"
        try:
            _, revision = self.config_service.read(target)
            wrapped_changes = [SimpleNamespace(path=c["path"], value=c["value"]) for c in changes]
            self.config_service.patch(target, revision, wrapped_changes)
            return True, f"实例 [{target}] 配置修改已成功保存生效"
        except ApiError as e:
            return False, f"保存失败: {e.message}"
        except Exception as e:
            return False, f"保存异常: {e}"

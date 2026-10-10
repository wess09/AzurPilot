"""TUI 全功能配置编辑器模态弹窗组件。

支持动态切换任务、实时解析配置项元数据与国际化翻译、
提供 Switch 开关、Select 下拉单选和 Input 输入框编辑，并支持原子事务保存。
"""

from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Switch

from module.tui.backend import TUIBackend


class ConfigModal(ModalScreen[bool]):
    """全功能任务配置编辑模态弹窗。"""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "关闭", priority=True),
        Binding("ctrl+s", "save_and_exit", "保存", priority=True),
    ]

    DEFAULT_CSS = """
    ConfigModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.75);
    }
    #config-dialog {
        width: 90;
        height: 85%;
        background: #161b22;
        border: thick $primary;
        padding: 1 2;
    }
    #config-title-box {
        height: 3;
        align: left middle;
        border-bottom: solid $primary-darken-3;
        margin-bottom: 1;
    }
    #config-title {
        text-style: bold;
        color: $accent;
        margin-right: 2;
    }
    #task-selector-box {
        height: 4;
        margin-bottom: 1;
        align: left middle;
    }
    #select-task {
        width: 100%;
    }
    #form-scroll {
        height: 1fr;
        background: #0d1117;
        border: solid #30363d;
        padding: 1;
        margin-bottom: 1;
    }
    .group-header {
        text-style: bold;
        color: #58a6ff;
        background: #21262d;
        padding: 0 1;
        margin-top: 1;
        margin-bottom: 1;
    }
    .field-row {
        height: auto;
        margin-bottom: 1;
        padding: 0 1;
        border-bottom: dashed #21262d;
    }
    .field-label {
        text-style: bold;
        color: #e6edf3;
    }
    .field-help {
        color: #8b949e;
        margin-bottom: 1;
    }
    .field-ctrl {
        margin-bottom: 1;
    }
    #config-action-bar {
        height: 3;
        align: right middle;
    }
    .config-btn {
        margin-left: 2;
        min-width: 16;
    }
    """

    def __init__(
        self,
        backend: TUIBackend,
        initial_task: Optional[str] = None,
        instance: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.instance = instance or backend.current_instance
        self.configurable_tasks = backend.get_all_configurable_tasks()

        # 确定初始选中的任务
        task_codes = [t[0] for t in self.configurable_tasks]
        if initial_task and initial_task in task_codes:
            self.current_task = initial_task
        elif task_codes:
            self.current_task = task_codes[0]
        else:
            self.current_task = "Alas"

        # 暂存当前正在编辑的表单项信息：{path: metadata}
        self.active_fields: Dict[str, Dict[str, Any]] = {}
        self._edited_emotion_values: set[str] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="config-dialog"):
            with Horizontal(id="config-title-box"):
                yield Label(f"⚙ 功能配置中心 ─ [{self.instance}]", id="config-title")
                yield Label("支持 Switch 开关 / Select 下拉 / Input 输入", classes="field-help")

            with Horizontal(id="task-selector-box"):
                options = [(f"{title} ({code})", code) for code, title in self.configurable_tasks]
                yield Select(options=options, value=self.current_task, id="select-task", allow_blank=False)

            yield VerticalScroll(id="form-scroll")

            with Horizontal(id="config-action-bar"):
                yield Button("💾 保存并生效 [Ctrl+S]", id="btn-save", variant="success", classes="config-btn")
                yield Button("✕ 取消 [Esc]", id="btn-cancel", variant="default", classes="config-btn")

    def on_mount(self) -> None:
        """初次挂载加载当前任务的参数表单。"""
        self.render_task_form(self.current_task)

    def on_select_changed(self, event: Select.Changed) -> None:
        """切换任务下拉项时，重绘该任务的配置表单。"""
        # 严格限定：只有顶部的任务选择下拉框能够触发表单重绘，拦截表单内部所有参数字段的冒泡事件
        if getattr(event.select, "id", None) != "select-task":
            return
        if event.value and event.value != Select.BLANK and event.value != self.current_task:
            self.current_task = str(event.value)
            self.render_task_form(self.current_task)

    def render_task_form(self, task: str) -> None:
        """根据后端元数据动态生成配置表单控件。"""
        scroll = self.query_one("#form-scroll", VerticalScroll)
        scroll.remove_children()
        self.active_fields.clear()
        self._edited_emotion_values.clear()

        groups = self.backend.get_task_config_schema(task, instance=self.instance)
        if not groups:
            scroll.mount(Label("该任务暂无可修改的配置项", classes="field-help"))
            return

        for g in groups:
            group_name = g["group_name"]
            group_title = g["group_title"]
            scroll.mount(Label(f"── {group_title} ({group_name}) ──", classes="group-header"))

            for item in g["items"]:
                path = item["path"]
                title = item["title"]
                arg_name = item["arg"]
                help_text = item["help"]
                kind = item["type"]
                current_val = item["value"]
                options = item.get("options")

                self.active_fields[path] = item

                children = [Label(f"{title} ({arg_name})", classes="field-label")]
                if help_text:
                    children.append(Label(help_text, classes="field-help"))

                # 生成对应的 Textual 交互控件
                if kind == "checkbox" or isinstance(current_val, bool):
                    children.append(
                        Switch(value=bool(current_val), id=self._ctrl_id("switch", path), classes="field-ctrl")
                    )
                elif options:
                    # 下拉选择控件
                    select_options = [(label, opt) for opt, label in options]
                    valid_values = [opt for opt, label in options]
                    val = current_val
                    if val not in valid_values:
                        val = valid_values[0] if valid_values else Select.BLANK

                    children.append(
                        Select(
                            options=select_options,
                            value=val,
                            id=self._ctrl_id("select", path),
                            allow_blank=False,
                            classes="field-ctrl",
                        )
                    )
                else:
                    # 文本/数字输入框
                    val_str = "" if current_val is None else str(current_val)
                    children.append(
                        Input(
                            value=val_str,
                            id=self._ctrl_id("input", path),
                            classes="field-ctrl",
                        )
                    )

                scroll.mount(Vertical(*children, classes="field-row"))

    @staticmethod
    def _ctrl_id(prefix: str, path: str) -> str:
        """根据配置路径生成合法安全的控件 ID。"""
        safe_path = path.replace(".", "_").replace("-", "_")
        return f"{prefix}_{safe_path}"

    def _emotion_input_path(self, input_widget: Input) -> Optional[str]:
        for path in self.active_fields:
            parts = path.split('.')
            if (len(parts) == 3 and ((parts[1] == 'Emotion' and parts[2] in ('Fleet1Value', 'Fleet2Value'))
                                    or (parts[1] == 'PublicEmotion' and parts[2] == 'FleetValue'))
                    and input_widget.id == self._ctrl_id('input', path)):
                return path
        return None

    def on_input_changed(self, event: Input.Changed) -> None:
        path = self._emotion_input_path(event.input)
        # 初次挂载的 Input.Changed 不能把未测量的旧值当作一次校准。
        if path and event.value.strip() != str(self.active_fields[path]['value']):
            self._edited_emotion_values.add(path)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        path = self._emotion_input_path(event.input)
        if path:
            self._edited_emotion_values.add(path)

    def collect_changes(self) -> List[Dict[str, Any]]:
        """从当前表单控件中提取已修改的值。"""
        changes = []
        for path, item in self.active_fields.items():
            kind = item["type"]
            original_val = item["value"]
            options = item.get("options")

            new_val: Any = None
            if kind == "checkbox" or isinstance(original_val, bool):
                ctrl = self.query(f"#{self._ctrl_id('switch', path)}").first(Switch)
                if ctrl:
                    new_val = bool(ctrl.value)
            elif options:
                ctrl = self.query(f"#{self._ctrl_id('select', path)}").first(Select)
                if ctrl and ctrl.value != Select.BLANK:
                    new_val = ctrl.value
            else:
                ctrl = self.query(f"#{self._ctrl_id('input', path)}").first(Input)
                if ctrl:
                    raw_text = ctrl.value.strip()
                    # 尝试还原整型或浮点数类型
                    if isinstance(original_val, int) and not isinstance(original_val, bool):
                        try:
                            new_val = int(raw_text)
                        except ValueError:
                            new_val = raw_text
                    elif isinstance(original_val, float):
                        try:
                            new_val = float(raw_text)
                        except ValueError:
                            new_val = raw_text
                    else:
                        new_val = raw_text

            if new_val is not None and (new_val != original_val or path in self._edited_emotion_values):
                changes.append({"path": path, "value": new_val})

        return changes

    def action_save_and_exit(self) -> None:
        """保存配置并退出。"""
        changes = self.collect_changes()
        if not changes:
            self.app.notify("配置未发生变更", severity="information")
            self.dismiss(False)
            return

        success, msg = self.backend.save_task_config(changes, instance=self.instance)
        if success:
            self.app.notify(f"✅ {self.current_task} 配置已保存生效", severity="information")
            self.dismiss(True)
        else:
            self.app.notify(f"❌ {msg}", severity="error")

    def action_dismiss_modal(self) -> None:
        """按 Esc 取消退出。"""
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮点击事件处理。"""
        if event.button.id == "btn-save":
            self.action_save_and_exit()
        elif event.button.id == "btn-cancel":
            self.action_dismiss_modal()

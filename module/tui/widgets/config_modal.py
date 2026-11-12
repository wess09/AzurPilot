"""TUI 全功能配置编辑器模态弹窗组件。

支持动态切换任务、实时解析配置项元数据与国际化翻译、
提供 Switch 开关、Select 下拉、Input 输入框、TextArea 多行文本编辑，
并支持原子事务保存。按类型识别多选与日期字段，避免把结构化参数退化成裸字符串。
"""

import re
from typing import Any, Dict, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Switch, TextArea

from module.tui.backend import TUIBackend

TEXTAREA_TYPES = ('textarea', 'task_priority')
MULTISELECT_SEPARATOR = re.compile(r'[,，\s]+')


class ConfigModal(ModalScreen[bool]):
    """全功能任务配置编辑模态弹窗。"""

    BINDINGS = [
        Binding("escape", "dismiss_modal", "关闭", priority=True),
        Binding("ctrl+s", "save_and_exit", "保存", priority=True),
        Binding("ctrl+r", "reload_form", "重载", priority=True),
    ]

    DEFAULT_CSS = """
    ConfigModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.75);
    }
    #config-dialog {
        width: 90%;
        max-width: 100;
        height: 90%;
        background: #161b22;
        border: thick $primary;
        padding: 1 2;
    }
    #config-title-box {
        height: 2;
        align: left middle;
        border-bottom: solid $primary-darken-3;
        margin-bottom: 0;
    }
    #config-title {
        text-style: bold;
        color: $accent;
        margin-right: 2;
    }
    #config-help {
        color: $text-muted;
        width: 1fr;
        text-align: right;
        text-overflow: ellipsis;
    }
    #task-selector-box {
        height: 3;
        margin-bottom: 0;
        align: left middle;
    }
    #select-task {
        width: 100%;
    }
    #form-scroll {
        height: 1fr;
        min-height: 3;
        background: #0d1117;
        border: solid #30363d;
        padding: 0 1;
        margin-bottom: 0;
    }
    .group-header {
        text-style: bold;
        color: #58a6ff;
        background: #21262d;
        padding: 0 1;
        margin-top: 0;
        margin-bottom: 0;
    }
    .field-row {
        height: auto;
        padding: 0 1;
        border-bottom: dashed #21262d;
    }
    .field-label {
        text-style: bold;
        color: #e6edf3;
        text-wrap: wrap;
        height: auto;
        width: 1fr;
    }
    .field-help {
        color: #8b949e;
        text-wrap: wrap;
        height: auto;
        width: 1fr;
    }
    .field-textarea {
        height: 6;
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
        self._confirm_discard = False
        self._render_token = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="config-dialog"):
            with Horizontal(id="config-title-box"):
                yield Label(f"⚙ 功能配置中心 ─ [{self.instance}]", id="config-title", markup=False)
                yield Label("Ctrl+S 保存 · Ctrl+R 重载 · Esc 取消", id="config-help")

            with Horizontal(id="task-selector-box"):
                # Text 提示不会被当作 Rich markup 解析，避免标题里的方括号被吞掉。
                options = [(Text(f"{title} ({code})"), code) for code, title in self.configurable_tasks]
                yield Select(options=options, value=self.current_task, id="select-task", allow_blank=False)

            yield VerticalScroll(id="form-scroll")

            with Horizontal(id="config-action-bar"):
                yield Button(Text("💾 保存并生效 [Ctrl+S]"), id="btn-save", variant="success", classes="config-btn")
                yield Button(Text("✕ 取消 [Esc]"), id="btn-cancel", variant="default", classes="config-btn")

    async def on_mount(self) -> None:
        """初次挂载加载当前任务的参数表单。"""
        await self.render_task_form(self.current_task)

    async def on_select_changed(self, event: Select.Changed) -> None:
        """切换任务下拉项时，重绘该任务的配置表单。"""
        # 严格限定：只有顶部的任务选择下拉框能够触发表单重绘，拦截表单内部所有参数字段的冒泡事件
        if getattr(event.select, "id", None) != "select-task":
            return
        if event.value and event.value != Select.BLANK and event.value != self.current_task:
            self.current_task = str(event.value)
            self._confirm_discard = False
            await self.render_task_form(self.current_task)

    # ------------------------------------------------------------------
    # 表单渲染
    # ------------------------------------------------------------------
    async def render_task_form(self, task: str) -> None:
        """根据后端元数据动态生成配置表单控件。

        Args:
            task (str): 任务名称。
        """
        self._render_token += 1
        token = self._render_token
        scroll = self.query_one("#form-scroll", VerticalScroll)

        try:
            groups = self.backend.get_task_config_schema(task, instance=self.instance)
        except Exception as e:
            scroll.remove_children()
            self.active_fields.clear()
            await scroll.mount(Label(f"读取任务配置失败：{e}", classes="field-help", markup=False))
            return

        controls: List[Any] = []
        self.active_fields.clear()
        self._edited_emotion_values.clear()

        if not groups:
            controls.append(Label("该任务暂无可修改的配置项", classes="field-help"))
        else:
            for group in groups:
                controls.append(
                    Label(
                        f"── {group['group_title']} ({group['group_name']}) ──",
                        classes="group-header",
                        markup=False,
                    )
                )
                for item in group["items"]:
                    controls.extend(self._build_field(item))

        # 期间用户又切换了任务，丢弃本次渲染结果。
        if token != self._render_token:
            return

        scroll.remove_children()
        await scroll.mount_all(controls)
        scroll.scroll_home(animate=False)

    def _build_field(self, item: Dict[str, Any]) -> List[Any]:
        """构造单个参数项的控件列表。"""
        path = item["path"]
        title = item["title"]
        arg_name = item["arg"]
        help_text = item["help"]
        kind = item["type"]
        mode = item.get("mode")
        current_val = item["value"]
        options = item.get("options")

        self.active_fields[path] = item
        children: List[Any] = [Label(f"{title} ({arg_name})", classes="field-label", markup=False)]
        hints = [help_text] if help_text else []

        # 生成对应的 Textual 交互控件
        if kind == "checkbox" or isinstance(current_val, bool):
            children.append(
                Switch(value=bool(current_val), id=self._ctrl_id("switch", path), classes="field-ctrl")
            )
        elif kind == "multiselect" and options:
            values = current_val if isinstance(current_val, list) else []
            hints.append("多选：用逗号分隔可选值 " + "、".join(str(opt) for opt, _ in options))
            children.append(
                Input(
                    value=", ".join(str(value) for value in values),
                    placeholder=", ".join(str(opt) for opt, _ in options),
                    id=self._ctrl_id("input", path),
                    classes="field-ctrl",
                )
            )
        elif options:
            valid_values = [opt for opt, _ in options]
            val = current_val
            if val not in valid_values:
                val = valid_values[0] if valid_values else Select.BLANK
            children.append(
                Select(
                    options=[(Text(label), opt) for opt, label in options],
                    value=val,
                    id=self._ctrl_id("select", path),
                    allow_blank=False,
                    classes="field-ctrl",
                )
            )
        elif kind in TEXTAREA_TYPES or mode == "yaml":
            hints.append("多行编辑：Tab 切换到下一个控件")
            children.append(
                TextArea(
                    "" if current_val is None else str(current_val),
                    id=self._ctrl_id("textarea", path),
                    classes="field-textarea",
                )
            )
        else:
            if kind == "datetime":
                hints.append("格式 YYYY-MM-DD HH:MM:SS")
            children.append(
                Input(
                    value="" if current_val is None else str(current_val),
                    placeholder="YYYY-MM-DD HH:MM:SS" if kind == "datetime" else "",
                    id=self._ctrl_id("input", path),
                    classes="field-ctrl",
                )
            )

        if hints:
            children.insert(
                1,
                Label("  ".join(hint for hint in hints if hint), classes="field-help", markup=False),
            )
        return [Vertical(*children, classes="field-row")]

    @staticmethod
    def _ctrl_id(prefix: str, path: str) -> str:
        """根据配置路径生成合法安全的控件 ID。"""
        safe_path = path.replace(".", "_").replace("-", "_")
        return f"{prefix}_{safe_path}"

    # ------------------------------------------------------------------
    # 情绪校准联动（与 WebUI 记录时间语义保持一致）
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 取值与保存
    # ------------------------------------------------------------------
    def _control_for(self, prefix: str, path: str, widget_type: Any) -> Any:
        try:
            return self.query(f"#{self._ctrl_id(prefix, path)}").first(widget_type)
        except Exception:
            return None

    def _parse_value(self, item: Dict[str, Any], raw: Any) -> Any:
        """按参数类型还原控件取值，无法解析时抛出 ValueError。"""
        kind = item["type"]
        options = item.get("options")
        title = item.get("title") or item["arg"]

        if kind == "multiselect" and options:
            tokens = [token for token in MULTISELECT_SEPARATOR.split(str(raw)) if token]
            value_map = {str(opt): opt for opt, _ in options}
            label_map = {str(label): opt for opt, label in options}
            result: List[Any] = []
            for token in tokens:
                if token in value_map:
                    option = value_map[token]
                elif token in label_map:
                    option = label_map[token]
                else:
                    raise ValueError(f"{title}：无效选项 {token}")
                if option not in result:
                    result.append(option)
            return result

        text = raw.strip() if isinstance(raw, str) else raw

        valuetype = str(item.get("valuetype") or "").lower()
        original = item["value"]
        # 空输入且原本就是空值，视为未修改，避免可空数值字段一保存就报类型错误。
        if text == "" and original is None:
            return None
        wants_int = valuetype == "int" or (
            not valuetype and isinstance(original, int) and not isinstance(original, bool)
        )
        wants_float = valuetype in ("float", "number") or (
            not valuetype and isinstance(original, float)
        )

        if wants_int:
            if isinstance(text, int) and not isinstance(text, bool):
                return text
            if text == "":
                raise ValueError(f"{title}：需要填写整数")
            try:
                return int(str(text))
            except ValueError:
                try:
                    number = float(str(text))
                except ValueError:
                    raise ValueError(f"{title}：需要填写整数") from None
                if number.is_integer():
                    return int(number)
                raise ValueError(f"{title}：需要填写整数") from None
        if wants_float:
            if isinstance(text, (int, float)) and not isinstance(text, bool):
                return float(text)
            if text == "":
                raise ValueError(f"{title}：需要填写数字")
            try:
                return float(str(text))
            except ValueError:
                raise ValueError(f"{title}：需要填写数字") from None
        if text == "" and original is None:
            return None
        return text

    def collect_changes(self) -> List[Dict[str, Any]]:
        """从当前表单控件中提取已修改的值。

        Raises:
            ValueError: 控件内容无法转换为参数要求的类型。
        """
        changes: List[Dict[str, Any]] = []
        for path, item in self.active_fields.items():
            kind = item["type"]
            original_val = item["value"]
            options = item.get("options")

            new_val: Any = None
            if kind == "checkbox" or isinstance(original_val, bool):
                ctrl = self._control_for("switch", path, Switch)
                if ctrl is None:
                    continue
                new_val = bool(ctrl.value)
            elif options and kind != "multiselect":
                ctrl = self._control_for("select", path, Select)
                if ctrl is None or ctrl.value == Select.BLANK:
                    continue
                new_val = ctrl.value
            elif kind == "multiselect":
                ctrl = self._control_for("input", path, Input)
                if ctrl is None:
                    continue
                new_val = self._parse_value(item, ctrl.value)
            elif kind in TEXTAREA_TYPES or item.get("mode") == "yaml":
                ctrl = self._control_for("textarea", path, TextArea)
                if ctrl is None:
                    continue
                text = ctrl.text
                new_val = None if (text == "" and original_val is None) else text
            else:
                ctrl = self._control_for("input", path, Input)
                if ctrl is None:
                    continue
                new_val = self._parse_value(item, ctrl.value)

            if not self._same_value(new_val, original_val) or path in self._edited_emotion_values:
                changes.append({"path": path, "value": new_val})

        return changes

    @staticmethod
    def _same_value(new_val: Any, original_val: Any) -> bool:
        """比较新旧值，忽略字符串首尾空白造成的假差异。

        多行 YAML 等参数在配置文件里常带结尾换行，TextArea 回读时会丢失，
        若不归一化会把「未修改」误判成「已修改」，导致保存脏数据。
        """
        if new_val == original_val:
            return True
        if isinstance(new_val, str) and isinstance(original_val, str):
            return new_val.strip() == original_val.strip()
        return False

    def _has_unsaved(self) -> bool:
        try:
            return bool(self.collect_changes())
        except ValueError:
            return True

    def _friendly_error(self, message: str) -> str:
        """把错误里的配置路径替换成可读的参数名。"""
        for path, item in self.active_fields.items():
            if path in message:
                title = item.get("title") or item.get("arg") or path
                message = message.replace(path, f"{title}[{path}]")
        return message

    def action_save_and_exit(self) -> None:
        """保存配置并退出。"""
        try:
            changes = self.collect_changes()
        except ValueError as e:
            self.app.notify(f"❌ {e}", severity="error", timeout=6, markup=False)
            return

        if not changes:
            self.app.notify("配置未发生变更", severity="information", markup=False)
            self.dismiss(False)
            return

        success, msg = self.backend.save_task_config(changes, instance=self.instance)
        if success:
            self.app.notify(
                f"✅ {self.current_task} 配置已保存生效",
                severity="information",
                markup=False,
            )
            self.dismiss(True)
        else:
            self.app.notify(
                f"❌ {self._friendly_error(msg)}",
                severity="error",
                timeout=8,
                markup=False,
            )

    def action_reload_form(self) -> None:
        """丢弃未保存的修改并重新读取配置。"""
        self._confirm_discard = False
        self.run_worker(
            self.render_task_form(self.current_task),
            group="config-form",
            exclusive=True,
            exit_on_error=False,
        )
        self.app.notify("已重新载入配置", severity="information", timeout=2, markup=False)

    def action_dismiss_modal(self) -> None:
        """按 Esc 取消退出；有未保存修改时需再确认一次。"""
        if self._confirm_discard or not self._has_unsaved():
            self.dismiss(False)
            return
        self._confirm_discard = True
        self.app.notify("有未保存的修改，再按一次 Esc 放弃", severity="warning", timeout=4, markup=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮点击事件处理。"""
        if event.button.id == "btn-save":
            self.action_save_and_exit()
        elif event.button.id == "btn-cancel":
            self.action_dismiss_modal()

import copy
# 此文件定义了 WebUI 中使用的各种自定义交互图形组件（Widgets）。
# 包含彩色实时日志渲染器（RichLog）、状态感知切换按钮以及图标按钮组等高度定制化的可视化组件。
import html
import json
import pywebio.pin
import random
import re
import string
from typing import Any, Callable, Dict, Generator, List, Optional, TYPE_CHECKING, Union

from pywebio.exceptions import SessionException
from pywebio.io_ctrl import Output
from pywebio.output import *
from pywebio.session import eval_js, local, run_js
from rich.console import Console
from rich.console import ConsoleRenderable

from module.logger import HTMLConsole, Highlighter, WEB_THEME
from module.webui.lang import t
from module.webui.pin import put_checkbox, put_input, put_select, put_textarea
from module.webui.process_manager import ProcessManager
from module.webui.setting import State
from module.webui.utils import (
    DARK_TERMINAL_THEME,
    LIGHT_TERMINAL_THEME,
    LOG_CODE_FORMAT,
    Switch,
    Icon
)

if TYPE_CHECKING:
    from module.webui.app import AlasGUI


class ScrollableCode:
    """
    https://github.com/pywebio/PyWebIO/discussions/21
    Deprecated
    """

    def __init__(self, keep_bottom: bool = True) -> None:
        self.keep_bottom = keep_bottom

        self.id = "".join(random.choice(string.ascii_letters) for _ in range(10))
        self.html = (
                """<pre id="%s" class="container-log"><code style="white-space:break-spaces;"></code></pre>"""
                % self.id
        )

    def output(self):
        # .style("display: grid; overflow-y: auto;")
        return put_html(self.html)

    def append(self, text: str) -> None:
        if text:
            run_js(
                """$("#{dom_id}>code").append(text);
            """.format(
                    dom_id=self.id
                ),
                text=str(text),
            )
            if self.keep_bottom:
                self.scroll()

    def scroll(self) -> None:
        run_js(
            r"""$("\#{dom_id}").animate({{scrollTop: $("\#{dom_id}").prop("scrollHeight")}}, 0);
        """.format(
                dom_id=self.id
            )
        )

    def reset(self) -> None:
        run_js(r"""$("\#{dom_id}>code").empty();""".format(dom_id=self.id))

    def set_scroll(self, b: bool) -> None:
        # use for lambda callback function
        self.keep_bottom = b


class RichLog:
    last_display_time: dict
    KEYWORD_TITLE_MAP = [
        (("侵蚀 1", "侵蚀1", "hazard 1 leveling", "cl1"), "OpsiHazard1Leveling"),
        (("短猫", "meowfficer farming"), "OpsiMeowfficerFarming"),
        (("深渊", "abyssal"), "OpsiAbyssal"),
        (("隐秘", "obscure"), "OpsiObscure"),
        (("要塞", "stronghold"), "OpsiStronghold"),
        (("委托", "commission"), "Commission"),
        (("科研", "research"), "Research"),
        (("演习", "exercise"), "Exercise"),
        (("宿舍", "dorm"), "Dorm"),
        (("收获", "reward", "领取奖励", "get items"), "Reward"),
        (("商店", "shop"), "ShopFrequent"),
        (("免费", "freebies"), "Freebies"),
        (("公会", "guild"), "Guild"),
        (("建造", "gacha"), "Gacha"),
        (("重启", "restart", "app login", "app restart"), "Restart"),
    ]

    def __init__(self, scope, font_width="0.559") -> None:
        self.scope = scope
        self.font_width = font_width
        self.console = HTMLConsole(
            force_terminal=False,
            force_interactive=False,
            width=80,
            color_system="truecolor",
            markup=False,
            record=True,
            safe_box=False,
            highlighter=Highlighter(),
            theme=WEB_THEME,
        )
        # self.callback_id = output_register_callback(
        #     self._callback_set_width, serial_mode=True)
        # self._callback_thread = None
        # self._width = 80
        self.keep_bottom = True
        self.display_dashboard = True
        self.first_display = True
        self.last_display_time = {}
        self.dashboard_arg_group = None
        self.text_console = Console(
            force_terminal=False,
            force_interactive=False,
            no_color=True,
            highlight=False,
            width=120,
            soft_wrap=True,
        )
        self.timeline_steps = []
        self.timeline_steps_max_length = 800
        self.timeline_steps_reduce_length = 200
        self.detail_lines_max_length = 120
        self.processed_renderables_total = 0
        if State.theme == "dark":
            self.terminal_theme = DARK_TERMINAL_THEME
        else:
            self.terminal_theme = LIGHT_TERMINAL_THEME

    def render(self, renderable: ConsoleRenderable) -> str:
        with self.console.capture():
            self.console.print(renderable)

        html = self.console.export_html(
            theme=self.terminal_theme,
            clear=True,
            code_format=LOG_CODE_FORMAT,
            inline_styles=True,
        )
        # print(html)
        return html

    def extend(self, text):
        if text:
            run_js(
                """$("#pywebio-scope-{scope}>div").append(text);
            """.format(
                    scope=self.scope
                ),
                text=str(text),
            )
            if self.keep_bottom:
                self.scroll()

    def reset(self):
        self.timeline_steps = []
        self.processed_renderables_total = 0
        run_js(f"""$("#pywebio-scope-{self.scope}>div").empty();""")

    def scroll(self) -> None:
        run_js(
            """$("#pywebio-scope-{scope}").scrollTop($("#pywebio-scope-{scope}").prop("scrollHeight"));
        """.format(
                scope=self.scope
            )
        )

    def set_scroll(self, b: bool) -> None:
        # use for lambda callback function
        self.keep_bottom = b

    def _render_text(self, renderable: ConsoleRenderable) -> str:
        with self.text_console.capture() as capture:
            self.text_console.print(renderable)
        return capture.get()

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _map_task_name(cls, task_name: str) -> str:
        translated = t(f"Task.{task_name}.name")
        if translated == f"Task.{task_name}.name":
            return task_name
        return translated

    @classmethod
    def _keyword_category(cls, text: str) -> Optional[str]:
        lowered = text.lower()
        for keywords, task_name in cls.KEYWORD_TITLE_MAP:
            if any(keyword.lower() in lowered for keyword in keywords):
                return cls._map_task_name(task_name)
        return None

    def _extract_task_title(self, text: str) -> tuple[Optional[str], bool]:
        scheduler_start = re.search(r"调度器:\s*开始任务\s*`?([A-Za-z0-9_]+)`?", text)
        if scheduler_start:
            return self._map_task_name(scheduler_start.group(1)), True

        task_bind = re.search(r"\[Task\]\s*([A-Za-z0-9_]+)", text)
        if task_bind:
            return self._map_task_name(task_bind.group(1)), True

        category = self._keyword_category(text)
        if category:
            return category, False

        for raw_line in text.splitlines():
            line = self._normalize_spaces(raw_line)
            if not line:
                continue

            matched = re.search(r"<<<\s*(.*?)\s*>>>", line)
            if matched:
                title = self._normalize_spaces(matched.group(1))
                if title:
                    category = self._keyword_category(title)
                    if category:
                        return category, False

            if any(char in raw_line for char in ("═", "─")):
                stripped = re.sub(r"^[\s═─\-│]+|[\s═─\-│]+$", "", raw_line).strip()
                stripped = self._normalize_spaces(stripped)
                if 2 <= len(stripped) <= 80:
                    category = self._keyword_category(stripped)
                    if category:
                        return category, False

        return None, False

    @staticmethod
    def _is_error_text(text: str) -> bool:
        return any(
            token in text
            for token in (
                " ERROR ",
                " CRITICAL ",
                "Traceback",
                "Exception",
                "RuntimeError",
                "ValueError",
                "AssertionError",
                "更新失败",
                "执行失败",
                "崩溃",
                "报错",
            )
        )

    def _create_step(self, title: str, status: str = "active") -> Dict[str, Any]:
        return {
            "title": title,
            "status": status,
            "line_count": 0,
            "last_message": "",
            "summary_message": "",
            "detail_lines": [],
            "has_error": False,
        }

    def _finalize_step(self, step: Dict[str, Any], terminal_status: Optional[str] = None) -> None:
        status = terminal_status or ("warning" if step.get("has_error") else "completed")
        step["status"] = status

    @classmethod
    def _trim_timeline_steps(cls, timeline_steps: List[Dict[str, Any]], max_length: int, reduce_length: int) -> None:
        if len(timeline_steps) > max_length:
            del timeline_steps[:reduce_length]

    def _ensure_step(self, title: Optional[str] = None) -> Dict[str, Any]:
        if not self.timeline_steps:
            self.timeline_steps.append(
                self._create_step(title or "启动中", status="active")
            )
        elif title and self.timeline_steps[-1]["title"] != title:
            if self.timeline_steps[-1]["status"] == "active":
                self._finalize_step(self.timeline_steps[-1])
            self.timeline_steps.append(self._create_step(title, status="active"))
        elif title and self.timeline_steps[-1]["title"] == title:
            if self.timeline_steps[-1]["status"] != "failed":
                self.timeline_steps[-1]["status"] = "active"
        self._trim_timeline_steps(
            self.timeline_steps,
            self.timeline_steps_max_length,
            self.timeline_steps_reduce_length,
        )
        return self.timeline_steps[-1]

    def _pick_summary_message(self, detail_lines: List[str], fallback: str = "") -> str:
        for line in reversed(detail_lines):
            if self._is_error_text(line):
                return line
        return detail_lines[-1] if detail_lines else fallback

    def _append_detail_lines(self, step: Dict[str, Any], raw_lines: List[str]) -> None:
        lines = step["detail_lines"]
        lines.extend(raw_lines)
        if len(lines) > self.detail_lines_max_length:
            del lines[: len(lines) - self.detail_lines_max_length]

    def _ingest_renderable(self, renderable: ConsoleRenderable) -> None:
        text_content = self._render_text(renderable)
        task_title, is_strong_boundary = self._extract_task_title(text_content)

        if not self.timeline_steps:
            step = self._ensure_step(task_title)
        elif is_strong_boundary and task_title:
            step = self._ensure_step(task_title)
        else:
            step = self.timeline_steps[-1]

        raw_lines = [line.rstrip() for line in text_content.splitlines()]
        raw_lines = [line for line in raw_lines if line.strip()]
        detail_lines = [self._normalize_spaces(line) for line in raw_lines]
        step["line_count"] += len(raw_lines)

        if detail_lines:
            step["last_message"] = detail_lines[-1]
            step["summary_message"] = self._pick_summary_message(
                detail_lines,
                fallback=step["summary_message"],
            )
            self._append_detail_lines(step, raw_lines)

        if self._is_error_text(text_content):
            step["has_error"] = True
            if step["status"] == "active":
                step["status"] = "warning"

    def _sync_process_state(self, pm: ProcessManager) -> None:
        if not self.timeline_steps:
            if pm.alive:
                self.timeline_steps.append(self._create_step("运行中", status="active"))
            elif pm.state == 3:
                self.timeline_steps.append(self._create_step("运行失败", status="failed"))
            return

        last_step = self.timeline_steps[-1]
        if pm.alive:
            if last_step["status"] not in ("failed", "warning"):
                last_step["status"] = "active"
            return

        if pm.state == 3:
            last_step["status"] = "failed"
            last_step["has_error"] = True
        else:
            self._finalize_step(last_step)

    @staticmethod
    def _status_meta(status: str) -> Dict[str, str]:
        if status == "failed":
            return {
                "class_name": "is-failed",
                "label": "执行失败",
                "icon": "x",
            }
        if status == "warning":
            return {
                "class_name": "is-warning",
                "label": "需关注",
                "icon": "warn",
            }
        if status == "active":
            return {
                "class_name": "is-active",
                "label": "正在执行",
                "icon": "spinner",
            }
        return {
            "class_name": "is-completed",
            "label": "已完成",
            "icon": "dot",
        }

    def _render_timeline_html(self) -> str:
        if not self.timeline_steps:
            return (
                '<div class="alas-log-empty">'
                '<div class="alas-log-empty-title">暂无运行任务</div>'
                '<div class="alas-log-empty-subtitle">任务开始后会在这里显示时间线</div>'
                "</div>"
            )

        items = []
        for index, step in enumerate(self.timeline_steps, start=1):
            status = self._status_meta(step["status"])
            summary_text = step["summary_message"] or step["last_message"] or "等待更多日志..."
            summary_text = html.escape(summary_text[:140])
            title = html.escape(step["title"])
            log_count = f"{step['line_count']} 条"
            detail_section = ""

            if step["status"] == "failed" and step["detail_lines"]:
                detail_text = "\n".join(step["detail_lines"])
                detail_html = html.escape(detail_text)
                detail_section = (
                    f'<details class="alas-log-step-details" data-step-index="{index}" open>'
                    '<summary>详细日志</summary>'
                    f'<div class="alas-log-step-details-body"><div class="alas-log-entry"><pre>{detail_html}</pre></div></div>'
                    '</details>'
                )

            items.append(
                f"""
                <div class="alas-log-step {status['class_name']}">
                    <div class="alas-log-step-marker">
                        <span class="alas-log-step-icon {status['icon']}"></span>
                    </div>
                    <div class="alas-log-step-main">
                        <div class="alas-log-step-head">
                            <div class="alas-log-step-title">{title}</div>
                            <div class="alas-log-step-badge">{status['label']}</div>
                        </div>
                        <div class="alas-log-step-subtitle">步骤 {index} · {log_count}</div>
                        <div class="alas-log-step-summary">{summary_text}</div>
                        {detail_section}
                    </div>
                </div>
                """
            )

        return '<div class="alas-log-timeline">' + "".join(items) + "</div>"

    def _refresh_timeline(self) -> None:
        run_js(
            """
            const container = $("#pywebio-scope-{scope}>div");
            const openStepIndexes = container
                .find(".alas-log-step-details[open]")
                .map(function () {{ return $(this).attr("data-step-index"); }})
                .get();
            container.html(html);
            openStepIndexes.forEach(function (stepIndex) {{
                container
                    .find('.alas-log-step-details[data-step-index="' + stepIndex + '"]')
                    .prop("open", true);
            }});
            """.format(scope=self.scope),
            html=self._render_timeline_html(),
        )
        if self.keep_bottom:
            self.scroll()

    def _rebuild_timeline(self, renderables: List[ConsoleRenderable], pm: ProcessManager) -> None:
        self.timeline_steps = []
        self.processed_renderables_total = 0
        for renderable in renderables:
            self._ingest_renderable(renderable)
        self._sync_process_state(pm)
        self.processed_renderables_total = getattr(pm, "renderables_total", len(renderables))
        self._refresh_timeline()

    def _catch_up_timeline(self, renderables: List[ConsoleRenderable], pm: ProcessManager) -> None:
        for renderable in renderables:
            self._ingest_renderable(renderable)
        self.processed_renderables_total = getattr(pm, "renderables_total", len(pm.renderables))
        self._sync_process_state(pm)
        self._refresh_timeline()

    def set_dashboard_display(self, b: bool) -> None:
        # use for lambda callback function. Copied.
        self.display_dashboard = b
        self.first_display = True

    def get_width(self):
        js = """
        let canvas = document.createElement('canvas');
        canvas.style.position = "absolute";
        let ctx = canvas.getContext('2d');
        document.body.appendChild(canvas);
        ctx.font = `16px Menlo, consolas, DejaVu Sans Mono, Courier New, monospace`;
        document.body.removeChild(canvas);
        let text = ctx.measureText('0');
        ctx.fillText('0', 50, 50);

        ($('#pywebio-scope-{scope}').width()-16)/\
        $('#pywebio-scope-{scope}').css('font-size').slice(0, -2)/text.width*16;\
        """.format(
            scope=self.scope
        )
        width = eval_js(js)
        return 80 if width is None else 128 if width > 128 else int(width)

    # def _register_resize_callback(self):
    #     js = """
    #     WebIO.pushData(
    #         ($('#pywebio-scope-log').width()-16)/$('#pywebio-scope-log').css('font-size').slice(0, -2)/0.55,
    #         {callback_id}
    #     )""".format(callback_id=self.callback_id)

    # def _callback_set_width(self, width):
    #     self._width = width
    #     if self._callback_thread is None:
    #         self._callback_thread = Thread(target=self._callback_width_checker)
    #         self._callback_thread.start()

    # def _callback_width_checker(self):
    #     last_modify = time.time()
    #     _width = self._width
    #     while True:
    #         if time.time() - last_modify > 1:
    #             break
    #         if self._width == _width:
    #             time.sleep(0.1)
    #             continue
    #         else:
    #             _width = self._width
    #             last_modify = time.time()

    #     self._callback_thread = None
    #     self.console.width = int(_width)

    def put_log(self, pm: ProcessManager) -> Generator:
        yield
        try:
            last_snapshot = None
            while True:
                total_renderables = getattr(pm, "renderables_total", len(pm.renderables))
                snapshot = (total_renderables, pm.alive, pm.state)
                if snapshot != last_snapshot:
                    if self.processed_renderables_total == 0:
                        self._rebuild_timeline(pm.renderables[:], pm)
                    else:
                        new_count = total_renderables - self.processed_renderables_total
                        if new_count < 0:
                            self._rebuild_timeline(pm.renderables[:], pm)
                        elif new_count > len(pm.renderables):
                            self._catch_up_timeline(pm.renderables[:], pm)
                        else:
                            for renderable in pm.renderables[-new_count:] if new_count else []:
                                self._ingest_renderable(renderable)
                            self.processed_renderables_total = total_renderables
                            self._sync_process_state(pm)
                            self._refresh_timeline()
                    last_snapshot = snapshot
                yield
        except SessionException:
            pass


class BinarySwitchButton(Switch):
    def __init__(
            self,
            get_state,
            label_on,
            label_off,
            onclick_on,
            onclick_off,
            scope,
            color_on="success",
            color_off="secondary",
    ):
        """
        Args:
            get_state:
                (Callable):
                    return True to represent state `ON`
                    return False tp represent state `OFF`
                (Generator):
                    yield True to change btn state to `ON`
                    yield False to change btn state to `OFF`
            label_on: label to show when state is `ON`
            label_off:
            onclick_on: function to call when state is `ON`
            onclick_off:
            color_on: button color when state is `ON`
            color_off:
            scope: scope for button, just for button **only**
        """
        self.scope = scope
        status = {
            0: {
                "func": self.update_button,
                "args": (
                    label_off,
                    onclick_off,
                    color_off,
                ),
            },
            1: {
                "func": self.update_button,
                "args": (
                    label_on,
                    onclick_on,
                    color_on,
                ),
            },
        }
        super().__init__(status=status, get_state=get_state, name=scope)

    def update_button(self, label, onclick, color):
        clear(self.scope)
        put_button(label=label, onclick=onclick, color=color, scope=self.scope)


# aside buttons


def put_icon_buttons(
        icon_html: str,
        signal: str,
        buttons: List[Dict[str, str]],
        onclick: Union[List[Callable[[], None]], Callable[[], None]],
) -> Output:
    value = buttons[0]["value"]
    circle_c = ""
    status_html = ""
    state = 2
    if signal == "true":
        state = ProcessManager.get_manager(value).state
        if state == 1:
            circle_c = "RUNNING"
        elif state == 3:
            circle_c = "ERROR"
        elif state == 4:
            circle_c = "UPDATE"
    if circle_c != "":
        status_html = getattr(Icon, circle_c)

    put_column(
        [
            put_html(
                f'<div style="position: relative; width: 4rem; display: flex; justify-content: center; pointer-events: none;">'
                f'<div style="z-index: 3;">{icon_html}</div>'
                f'<div style="z-index: 4; position: absolute; margin-left: 24px;">{status_html}</div>'
                f'</div>'
            ),
            put_buttons(buttons, onclick).style(f"z-index: 2; --aside-{value}--;"),
        ],
        size="0",
    )

    return state


def put_none() -> Output:
    return put_html("<div></div>")


T_Output_Kwargs = Dict[str, Union[str, Dict[str, Any]]]


def get_title_help(kwargs: T_Output_Kwargs) -> Output:
    title: str = kwargs.get("title")
    help_text: str = kwargs.get("help")

    if help_text:
        res = put_column(
            [
                put_text(title).style("--arg-title--"),
                put_text(help_text).style("--arg-help--"),
            ],
            size="auto 1fr",
        )
    else:
        res = put_text(title).style("--arg-title--")

    return res


# args input widget
def put_arg_input(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    options: List = kwargs.get("options")
    if options is not None:
        kwargs.setdefault("datalist", options)

    return put_scope(
        f"arg_container-input-{name}",
        [
            get_title_help(kwargs),
            put_input(**kwargs).style("--input--"),
        ],
    )


def product_stored_row(kwargs: T_Output_Kwargs, key, value):
    kwargs = copy.copy(kwargs)
    kwargs["name"] += f'_{key}'
    kwargs["value"] = value
    return put_input(**kwargs).style("--input--")


def put_arg_stored(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    kwargs["disabled"] = True

    values = kwargs.pop("value", {})
    if not isinstance(values, dict):
        values = {}
    time_ = values.pop("time", "")

    rows = [product_stored_row(kwargs, key, value) for key, value in values.items() if value]
    if time_:
        rows += [product_stored_row(kwargs, "time", time_)]
    return put_scope(
        f"arg_container-stored-{name}",
        [
            get_title_help(kwargs),
            put_scope(
                f"arg_stored-stored-value-{name}",
                rows,
            )
        ]
    )


def put_arg_select(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    value: str = kwargs["value"]
    options: List[str] = kwargs["options"]
    options_label: List[str] = kwargs.pop("options_label", [])
    disabled: bool = kwargs.pop("disabled", False)
    _: str = kwargs.pop("invalid_feedback", None)

    if disabled:
        option = [{
            "label": next((opt_label for opt, opt_label in zip(options, options_label) if opt == value), value),
            "value": value,
            "selected": True,
        }]
    else:
        option = [{
            "label": opt_label,
            "value": opt,
            "select": opt == value,
        } for opt, opt_label in zip(options, options_label)]
    kwargs["options"] = option

    return put_scope(
        f"arg_container-select-{name}",
        [
            get_title_help(kwargs),
            put_select(**kwargs).style("--input--"),
        ],
    )


def put_arg_state(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    value: str = kwargs["value"]
    options: List[str] = kwargs["options"]
    options_label: List[str] = kwargs.pop("options_label", [])
    _: str = kwargs.pop("invalid_feedback", None)
    bold: bool = value in kwargs.pop("option_bold", [])
    light: bool = value in kwargs.pop("option_light", [])

    option = [{
        "label": next((opt_label for opt, opt_label in zip(options, options_label) if opt == value), value),
        "value": value,
        "selected": True,
    }]
    if bold:
        kwargs["class"] = "form-control state state-bold"
    elif light:
        kwargs["class"] = "form-control state state-light"
    else:
        kwargs["class"] = "form-control state"
    kwargs["options"] = option

    return put_scope(
        f"arg_container-select-{name}",
        [
            get_title_help(kwargs),
            put_select(**kwargs).style("--input--"),
        ],
    )


def put_arg_textarea(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    mode: str = kwargs.pop("mode", None)
    kwargs.setdefault(
        "code", {"lineWrapping": True, "lineNumbers": False, "mode": mode}
    )

    return put_scope(
        f"arg_contianer-textarea-{name}",
        [
            get_title_help(kwargs),
            put_textarea(**kwargs),
        ],
    )


def put_arg_checkbox(kwargs: T_Output_Kwargs) -> Output:
    # Not real checkbox, use as a switch (on/off)
    name: str = kwargs["name"]
    value: str = kwargs["value"]
    _: str = kwargs.pop("invalid_feedback", None)

    kwargs["options"] = [{"label": "", "value": True, "selected": value}]
    return put_scope(
        f"arg_container-checkbox-{name}",
        [
            get_title_help(kwargs),
            put_checkbox(**kwargs).style("text-align: center"),
        ],
    )


def put_arg_datetime(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    return put_scope(
        f"arg_container-datetime-{name}",
        [
            get_title_help(kwargs),
            put_input(**kwargs).style("--input--"),
        ],
    )


def put_arg_storage(kwargs: T_Output_Kwargs) -> Optional[Output]:
    name: str = kwargs["name"]
    if kwargs["value"] == {}:
        return None

    kwargs["value"] = json.dumps(
        kwargs["value"], indent=2, ensure_ascii=False, sort_keys=False, default=str
    )
    kwargs.setdefault(
        "code", {"lineWrapping": True, "lineNumbers": False, "mode": "json"}
    )

    def clear_callback():
        alasgui: "AlasGUI" = local.gui
        alasgui.modified_config_queue.put(
            {"name": ".".join(name.split("_")), "value": {}}
        )
        # https://github.com/pywebio/PyWebIO/issues/459
        # pin[name] = "{}"

    return put_scope(
        f"arg_container-storage-{name}",
        [
            put_textarea(**kwargs),
            put_html(
                f'<button class="btn btn-outline-warning btn-block">{t("Gui.Text.Clear")}</button>'
            ).onclick(clear_callback),
        ],
    )


_widget_type_to_func: Dict[str, Callable] = {
    "input": put_arg_input,
    "lock": put_arg_state,
    "datetime": put_arg_input,  # TODO
    "select": put_arg_select,
    "textarea": put_arg_textarea,
    "checkbox": put_arg_checkbox,
    "storage": put_arg_storage,
    "state": put_arg_state,
    "stored": put_arg_stored,
}


def put_output(output_kwargs: T_Output_Kwargs) -> Optional[Output]:
    return _widget_type_to_func[output_kwargs["widget_type"]](output_kwargs)


def get_loading_style(shape: str, fill: bool) -> str:
    if fill:
        return f"--loading-{shape}-fill--"
    else:
        return f"--loading-{shape}--"


def put_loading_text(
        text: str,
        shape: str = "border",
        color: str = "dark",
        fill: bool = False,
        size: str = "auto 2px 1fr",
):
    loading_style = get_loading_style(shape=shape, fill=fill)
    return put_row(
        [
            put_loading(shape=shape, color=color).style(loading_style),
            None,
            put_text(text),
        ],
        size=size,
    )

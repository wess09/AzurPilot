import copy
# 此文件定义了 WebUI 中使用的各种自定义交互图形组件（Widgets）。
# 包含彩色实时日志渲染器（RichLog）、状态感知切换按钮以及图标按钮组等高度定制化的可视化组件。
import html
import json
import pywebio.pin
import random
import string
import time
from typing import Any, Callable, Dict, Generator, List, Optional, TYPE_CHECKING, Union

from pywebio.exceptions import SessionException
from pywebio.io_ctrl import output_register_callback
from pywebio.io_ctrl import Output
from pywebio.output import *
from pywebio.session import eval_js, local, run_js
from rich.console import ConsoleRenderable

from module.config.deep import deep_get
from module.config.task_priority import (
    get_scheduler_tasks,
    merge_task_priority,
    parse_task_priority,
)
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
    可滚动的代码显示组件。

    参考 https://github.com/pywebio/PyWebIO/discussions/21
    已废弃，建议使用 RichLog 替代。
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

    last_display_time: dict

    def set_scroll(self, b: bool) -> None:
        # 用于 lambda 回调函数中设置是否保持滚动到底部
        self.keep_bottom = b


class RichLog:
    # run_js 是阻塞的前后端往返，滚动操作需要节流以保持界面响应。
    LOG_SCROLL_MIN_INTERVAL = 0.5

    last_display_time: dict

    def __init__(self, scope, font_width="0.559") -> None:
        self.scope = scope
        self.font_width = font_width
        self._last_scroll_time = 0.0
        self._sync_dirty = True
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
        # 以下为已废弃的宽度回调相关代码，保留供参考
        # self.callback_id = output_register_callback(
        #     self._callback_set_width, serial_mode=True)
        # self._callback_thread = None
        # self._width = 80
        self.keep_bottom = True
        self.display_dashboard = True
        self.first_display = True
        self.last_display_time = {}
        self.dashboard_arg_group = None
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
        # 调试：打印生成的 HTML
        return html

    def extend(self, text, scroll: bool = True):
        if text:
            run_js(
                """$("#pywebio-scope-{scope}>div").append(text);
            """.format(
                    scope=self.scope
                ),
                text=str(text),
            )
            if scroll and self.keep_bottom:
                self._scroll_throttled()

    def set_content(self, html: str, scroll: bool = True) -> None:
        if not html:
            self.reset()
            return
        run_js(
            """$("#pywebio-scope-{scope}>div").html(text);
        """.format(
                scope=self.scope
            ),
            text=str(html),
        )
        if scroll and self.keep_bottom:
            self._scroll_throttled(force=True)

    def set_dashboard_display(self, b: bool) -> None:
        # use for lambda callback function. Copied.
        self.display_dashboard = b
        self.first_display = True

    def reset(self):
        run_js(f"""$("#pywebio-scope-{self.scope}>div").empty();""")

    def scroll(self) -> None:
        run_js(
            """$("#pywebio-scope-{scope}").scrollTop($("#pywebio-scope-{scope}").prop("scrollHeight"));
        """.format(
                scope=self.scope
            )
        )

    def _scroll_throttled(self, force: bool = False) -> None:
        now = time.time()
        if force or now - self._last_scroll_time >= self.LOG_SCROLL_MIN_INTERVAL:
            self.scroll()
            self._last_scroll_time = now

    def set_scroll(self, b: bool) -> None:
        # 用于 lambda 回调函数中设置是否保持滚动到底部
        self.keep_bottom = b

    def set_dashboard_display(self, b: bool) -> None:
        # 用于 lambda 回调函数中设置是否显示仪表盘
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

    # 以下为已废弃的窗口宽度自适应回调代码，保留供参考
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

    def put_log(
        self,
        pm: ProcessManager,
        get_visible: Optional[Callable[[], bool]] = None,
    ) -> Generator:
        yield
        last_idx = 0
        try:
            while True:
                idx = len(pm.renderables)
                visible = get_visible() if get_visible else True

                if not visible:
                    if idx != last_idx:
                        self._sync_dirty = True
                    yield
                    continue

                if idx < last_idx:
                    last_idx -= pm.renderables_reduce_length
                    self._sync_dirty = True

                if self._sync_dirty:
                    html = "".join(map(self.render, pm.renderables[:]))
                    self.set_content(html)
                    last_idx = idx
                    self._sync_dirty = False
                elif idx != last_idx:
                    html = "".join(map(self.render, pm.renderables[last_idx:idx]))
                    self.extend(html)
                    last_idx = idx

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
        初始化二态切换按钮。

        Args:
            get_state: 获取当前状态。
                (Callable): 返回 True 表示开启状态，返回 False 表示关闭状态。
                (Generator): yield True 切换到开启状态，yield False 切换到关闭状态。
            label_on: 开启状态时显示的按钮文本。
            label_off: 关闭状态时显示的按钮文本。
            onclick_on: 开启状态时的点击回调函数。
            onclick_off: 关闭状态时的点击回调函数。
            color_on: 开启状态时的按钮颜色。
            color_off: 关闭状态时的按钮颜色。
            scope: 按钮的 PyWebIO 作用域，仅用于此按钮。
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


# 侧边栏图标按钮


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


# 参数输入组件
def put_arg_input(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    after: Optional[Output] = kwargs.pop("after", None)
    options: List = kwargs.get("options")
    if options is not None:
        kwargs.setdefault("datalist", options)
    input_output = put_input(**kwargs).style("--input--")
    if after is not None:
        input_output = put_column([input_output, after], size="auto auto")

    return put_scope(
        f"arg_container-input-{name}",
        [
            get_title_help(kwargs),
            input_output,
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


def put_arg_task_priority(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    value: str = kwargs.get("value", "")
    alasgui: "AlasGUI" = local.gui
    path = ".".join(name.split("_"))
    default = deep_get(alasgui.ALAS_ARGS, f"{path}.value", "")
    available_tasks = get_scheduler_tasks(alasgui.ALAS_ARGS)
    value = merge_task_priority(value, default, available_tasks)
    ordered_tasks = parse_task_priority(value)
    hidden_pin = put_textarea(name=name, value=value).style("display:none;--task-priority-pin--")

    task_set = set(ordered_tasks)
    task_items = []
    for index, task in enumerate(ordered_tasks, start=1):
        display_name = t(f"Task.{task}.name")
        if display_name == f"Task.{task}.name":
            display_name = task
        task_items.append(
            f"""
            <li class="task-priority-item" data-task="{html.escape(task, quote=True)}">
                <span class="task-priority-rank">{index}</span>
                <span class="task-priority-handle" aria-hidden="true">≡</span>
                <span class="task-priority-name">{html.escape(display_name)}</span>
                <span class="task-priority-code">{html.escape(task)}</span>
            </li>
            """
        )
    missing_tasks = [task for task in available_tasks if task not in task_set]
    for task in missing_tasks:
        display_name = t(f"Task.{task}.name")
        if display_name == f"Task.{task}.name":
            display_name = task
        task_items.append(
            f"""
            <li class="task-priority-item task-priority-item-new" data-task="{html.escape(task, quote=True)}">
                <span class="task-priority-rank"></span>
                <span class="task-priority-handle" aria-hidden="true">≡</span>
                <span class="task-priority-name">{html.escape(display_name)}</span>
                <span class="task-priority-code">{html.escape(task)}</span>
            </li>
            """
        )

    container_id = f"task-priority-{name}"
    content_id = f"task_priority_content_{name}"
    outer_id = f"task_priority_container_{name}"

    def save_priority(new_value):
        local.gui.modified_config_queue.put({"name": path, "value": str(new_value or "")})

    callback_id = output_register_callback(save_priority)
    html_output = put_html(
        f"""
        <ol id="{container_id}" class="task-priority-list" data-pin-name="{html.escape(name, quote=True)}" data-callback-id="{html.escape(callback_id, quote=True)}">
            {''.join(task_items)}
        </ol>
        """
    )
    run_js(
        r"""
        (function(containerId, outerId, contentId) {
            var attempts = 0;

            function setup() {
                var list = document.getElementById(containerId);
                if (!list) {
                    attempts += 1;
                    if (attempts < 80) setTimeout(setup, 50);
                    return;
                }
                if (list.dataset.ready === "1") return;
                list.dataset.ready = "1";

                var outer = document.getElementById("pywebio-scope-" + outerId);
                var content = document.getElementById("pywebio-scope-" + contentId);
                var pinWrapper = content ? content.querySelector('*[style*="--task-priority-pin--"]') : null;
                if (pinWrapper) {
                    pinWrapper.classList.add("task-priority-pin");
                    pinWrapper.style.setProperty("display", "none", "important");
                }
                if (outer) {
                    outer.classList.add("task-priority-container");
                    outer.style.setProperty("display", "grid", "important");
                    outer.style.setProperty("grid-template-columns", "minmax(0, 1fr)", "important");
                    outer.style.setProperty("width", "100%", "important");
                    outer.style.setProperty("min-width", "0", "important");
                }
                if (content) {
                    content.classList.add("task-priority-content");
                    content.style.setProperty("width", "100%", "important");
                    content.style.setProperty("min-width", "0", "important");
                }

                function renumber() {
                    Array.prototype.forEach.call(list.querySelectorAll(".task-priority-item"), function(item, index) {
                        var rank = item.querySelector(".task-priority-rank");
                        if (rank) rank.textContent = String(index + 1);
                    });
                }

                function serialize() {
                    return Array.prototype.map.call(list.querySelectorAll(".task-priority-item"), function(item) {
                        return item.dataset.task;
                    }).filter(Boolean).join("\n> ");
                }

                function syncPin(shouldNotify) {
                    renumber();
                    var pinName = list.dataset.pinName;
                    var value = serialize();
                    var input = document.querySelector('[name="' + pinName + '"]');
                    if (input) {
                        input.value = value;
                    }
                    if (shouldNotify) {
                        if (input) {
                            input.dispatchEvent(new Event("change", { bubbles: true }));
                        }
                        if (window.WebIO && list.dataset.callbackId) {
                            WebIO.pushData(value, list.dataset.callbackId);
                        }
                    }
                }

                var autoScrollTimer = null;
                var autoScrollSpeed = 0;
                var dragState = null;
                var framePending = false;
                var latestClientY = 0;

                function stopAutoScroll() {
                    autoScrollSpeed = 0;
                    if (autoScrollTimer !== null) {
                        clearInterval(autoScrollTimer);
                        autoScrollTimer = null;
                    }
                }

                function startAutoScroll(speed) {
                    autoScrollSpeed = speed;
                    if (autoScrollTimer !== null) return;
                    autoScrollTimer = setInterval(function() {
                        if (!autoScrollSpeed) {
                            stopAutoScroll();
                            return;
                        }
                        list.scrollTop += autoScrollSpeed;
                        scheduleMove(latestClientY);
                    }, 16);
                }

                function updateAutoScroll(clientY) {
                    var rect = list.getBoundingClientRect();
                    var threshold = Math.min(120, Math.max(48, rect.height * 0.18));
                    var topDistance = clientY - rect.top;
                    var bottomDistance = rect.bottom - clientY;
                    var speed = 0;
                    if (topDistance < threshold) {
                        speed = -Math.ceil((threshold - topDistance) / threshold * 24);
                    } else if (bottomDistance < threshold) {
                        speed = Math.ceil((threshold - bottomDistance) / threshold * 24);
                    }

                    if (speed) {
                        startAutoScroll(speed);
                    } else {
                        stopAutoScroll();
                    }
                }

                function getInsertBefore(y) {
                    var candidates = Array.prototype.filter.call(
                        list.querySelectorAll(".task-priority-item:not(.task-priority-floating)"),
                        function(item) { return item.offsetParent !== null; }
                    );
                    return candidates.reduce(function(closest, child) {
                        var box = child.getBoundingClientRect();
                        var offset = y - box.top - box.height / 2;
                        if (offset < 0 && offset > closest.offset) {
                            return { offset: offset, element: child };
                        }
                        return closest;
                    }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
                }

                function clearFloatingStyle(item) {
                    item.style.position = "";
                    item.style.left = "";
                    item.style.top = "";
                    item.style.width = "";
                    item.style.height = "";
                    item.style.zIndex = "";
                    item.style.transform = "";
                    item.style.pointerEvents = "";
                }

                function scheduleMove(clientY) {
                    latestClientY = clientY;
                    if (framePending || !dragState) return;
                    framePending = true;
                    requestAnimationFrame(function() {
                        framePending = false;
                        if (!dragState) return;

                        var dy = latestClientY - dragState.startY;
                        dragState.item.style.transform = "translate3d(0, " + dy + "px, 0)";
                        updateAutoScroll(latestClientY);

                        var before = getInsertBefore(latestClientY);
                        var placeholder = dragState.placeholder;
                        if (before === placeholder || before === placeholder.nextSibling) return;
                        if (before == null) {
                            if (placeholder.nextSibling !== null) {
                                list.appendChild(placeholder);
                            }
                        } else {
                            list.insertBefore(placeholder, before);
                        }
                    });
                }

                function cleanupDrag(shouldNotify) {
                    if (!dragState) return;
                    var state = dragState;
                    dragState = null;
                    stopAutoScroll();
                    window.removeEventListener("pointermove", onPointerMove);
                    window.removeEventListener("pointerup", onPointerUp);
                    window.removeEventListener("pointercancel", onPointerCancel);
                    document.body.classList.remove("task-priority-drag-active");
                    try {
                        state.item.releasePointerCapture(state.pointerId);
                    } catch (error) {}
                    if (shouldNotify) {
                        state.placeholder.replaceWith(state.item);
                    } else {
                        state.placeholder.remove();
                    }
                    clearFloatingStyle(state.item);
                    state.item.classList.remove("task-priority-floating");
                    if (shouldNotify) {
                        syncPin(true);
                    } else {
                        renumber();
                    }
                }

                function onPointerMove(event) {
                    if (!dragState || event.pointerId !== dragState.pointerId) return;
                    event.preventDefault();
                    scheduleMove(event.clientY);
                }

                function onPointerUp(event) {
                    if (!dragState || event.pointerId !== dragState.pointerId) return;
                    event.preventDefault();
                    cleanupDrag(true);
                }

                function onPointerCancel(event) {
                    if (!dragState || event.pointerId !== dragState.pointerId) return;
                    cleanupDrag(false);
                }

                function beginDrag(event) {
                    if (dragState) return;
                    if (event.button !== undefined && event.button !== 0) return;
                    var item = event.target.closest(".task-priority-item");
                    if (!item) return;
                    event.preventDefault();

                    var rect = item.getBoundingClientRect();
                    var placeholder = document.createElement("li");
                    placeholder.className = "task-priority-placeholder";
                    placeholder.style.height = rect.height + "px";
                    item.after(placeholder);

                    item.classList.add("task-priority-floating");
                    item.style.position = "fixed";
                    item.style.left = rect.left + "px";
                    item.style.top = rect.top + "px";
                    item.style.width = rect.width + "px";
                    item.style.height = rect.height + "px";
                    item.style.zIndex = "2147483646";
                    item.style.pointerEvents = "none";
                    item.style.transform = "translate3d(0, 0, 0)";

                    dragState = {
                        item: item,
                        placeholder: placeholder,
                        pointerId: event.pointerId,
                        startY: event.clientY
                    };
                    latestClientY = event.clientY;
                    document.body.classList.add("task-priority-drag-active");
                    try {
                        item.setPointerCapture(event.pointerId);
                    } catch (error) {}
                    window.addEventListener("pointermove", onPointerMove, { passive: false });
                    window.addEventListener("pointerup", onPointerUp, { passive: false });
                    window.addEventListener("pointercancel", onPointerCancel, { passive: false });
                }

                list.addEventListener("pointerdown", beginDrag);
                list.addEventListener("dragstart", function(event) {
                    event.preventDefault();
                });

                renumber();
                syncPin(false);
            }

            setup();
        })(containerId, outerId, contentId);
        """,
        containerId=container_id,
        outerId=outer_id,
        contentId=content_id,
    )
    priority_content = put_scope(
        content_id,
        [
            hidden_pin,
            html_output,
        ],
    ).style("width:100%;min-width:0;box-sizing:border-box;")

    return put_scope(
        outer_id,
        [
            get_title_help(kwargs),
            priority_content,
        ],
    ).style("--task-priority-container--")


def put_arg_checkbox(kwargs: T_Output_Kwargs) -> Output:
    # 非真正复选框，用作开关（开/关）
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


def put_arg_multiselect(kwargs: T_Output_Kwargs) -> Output:
    """多选组件：使用竖向复选框组实现多选，交互直观。

    支持 options 和 options_label，value 为选中值的列表（如 [1, 3, 5]）。
    每个选项渲染为一个独立的 checkbox，竖向排列避免横向布局的点击区域冲突。
    """
    name: str = kwargs["name"]
    value: list = kwargs.get("value", [])
    if not isinstance(value, list):
        value = [value] if value else []
    options: List[str] = kwargs.get("options", [])
    options_label: List[str] = kwargs.pop("options_label", [])
    _: str = kwargs.pop("invalid_feedback", None)
    # 从 kwargs 中移除多余的键，避免传递给 put_checkbox 造成冲突
    for key in ("disabled", "value", "options"):
        kwargs.pop(key, None)

    checkbox_options = [{
        "label": opt_label,
        "value": opt,
        "selected": opt in value,
    } for opt, opt_label in zip(options, options_label)]

    return put_scope(
        f"arg_container-multiselect-{name}",
        [
            get_title_help(kwargs),
            put_checkbox(**kwargs, options=checkbox_options, value=value).style("--input--"),
        ],
    )


_widget_type_to_func: Dict[str, Callable] = {
    "input": put_arg_input,
    "lock": put_arg_state,
    "datetime": put_arg_input,  # TODO
    "select": put_arg_select,
    "multiselect": put_arg_multiselect,
    "textarea": put_arg_textarea,
    "task_priority": put_arg_task_priority,
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

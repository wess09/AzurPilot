"""TUI 快捷键与使用说明弹层。"""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

HELP_TEXT = """[b]全局快捷键[/b]
  Space        启动 / 停止当前实例的调度器
  Q            退出 TUI（已在运行的实例进程会继续运行）
  ?  /  F1     打开本帮助
  1 - 9        切换到第 N 个配置实例
  Tab / Shift+Tab  在实例列表、任务表、按钮之间移动焦点

[b]任务与配置[/b]
  Enter        在任务表上开启 / 关闭选中任务的计划
  E            编辑选中任务的详细参数
  C            打开功能配置中心（可选择任意任务）
  T            选择并单独执行一次任务功能
  R            立即刷新实例状态、任务计划与资源看板

[b]日志[/b]
  L            清空日志视窗
  P            开启 / 关闭自动滚屏（关闭后可自由向上翻阅）

[b]配置编辑器[/b]
  Ctrl+S       校验并保存全部修改
  Ctrl+R       丢弃修改并重新读取配置
  Esc          关闭；有未保存修改时需要再按一次确认

[b]说明[/b]
  · 实例状态每秒刷新，任务计划与资源看板每 5 秒刷新，日志约每 0.35 秒增量拉取。
  · 启停、单任务执行与保存均在后台线程进行，界面不会卡死；操作进行中按钮会暂时禁用。
  · 任务表中已禁用的任务以暗色显示，按回车可重新启用，不会被隐藏。
  · 配置项按类型提供开关、下拉、文本、多行文本与多选输入；日期格式为 YYYY-MM-DD HH:mm:ss。
  · 启动方式：uv run python gui.py --tui 实例名（实例名可省略）
"""


class HelpScreen(ModalScreen[None]):
    """快捷键与使用说明弹层。"""

    BINDINGS = [
        Binding("escape", "close", "关闭", priority=True),
        Binding("question_mark", "close", "关闭", show=False),
        Binding("f1", "close", "关闭", show=False),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.75);
    }
    #help-dialog {
        width: 90%;
        max-width: 100;
        height: 85%;
        background: #161b22;
        border: thick $primary;
        padding: 1 2;
    }
    #help-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #help-scroll {
        height: 1fr;
        background: #0d1117;
        border: solid #30363d;
        padding: 1;
        margin-bottom: 1;
    }
    #help-body {
        color: #c9d1d9;
    }
    #help-button-box {
        height: 3;
        align: right middle;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("❓ AzurPilot TUI 使用说明", id="help-title")
            with VerticalScroll(id="help-scroll"):
                yield Static(HELP_TEXT, id="help-body")
            with Horizontal(id="help-button-box"):
                yield Button(Text("关闭 [Esc]"), id="btn-help-close", variant="primary")

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-help-close":
            self.dismiss(None)

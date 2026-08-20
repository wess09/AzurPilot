"""AzurPilot 日志（Logger）系统模块。

基于 Rich 库构建的多目标日志系统，支持控制台彩色输出、文件轮转记录
和 WebUI 流式渲染。全局 logger 实例（alas）被整个框架共享使用。

主要组件：
    - RichFileHandler: 文件日志处理器（基于 Rich 格式化）。
    - RichRenderableHandler: 将日志渲染为可渲染对象传递给回调，用于 WebUI 实时展示。
    - RichTimedRotatingHandler: 按时间轮转的文件日志处理器，支持跨平台多进程。
    - HTMLConsole: 输出 HTML 格式的 Rich Console，用于 WebUI 渲染。
    - Highlighter: 自定义正则高亮器，高亮路径、URL、Python 布尔值/None 等。

提供的辅助函数：
    - hr(): 分节标题输出（支持 4 级标题）。
    - attr() / attr_align(): 属性对齐输出。
    - error_context() / exception_context(): 结构化错误信息输出。

全局 logger 实例通过 monkey-patch 方式扩展了上述方法，作为整个框架的
统一日志入口。
"""

import datetime
import io
import json
import logging
import multiprocessing
import os
import shutil
import sys
import tarfile
import threading
import time
import zipfile
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Callable, List

from rich.console import Console, ConsoleOptions, ConsoleRenderable, NewLine
from rich.highlighter import NullHighlighter, RegexHighlighter
from rich.logging import RichHandler
from rich.rule import Rule
from rich.style import Style
from rich.theme import Theme
from rich.traceback import Traceback

from module.base.runtime_context import get_runtime_context, runtime_state

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


def empty_function(*args, **kwargs):
    pass


# cnocr 会在 cnocr.utils 中设置 root logger
# 删除 logging.basicConfig 以避免日志消息重复输出。
logging.basicConfig = empty_function
logging.raiseExceptions = True  # 设为 True 可在控制台看到编码错误

# 移除 HTTP 关键字（GET、POST 等）避免日志高亮误判
RichHandler.KEYWORDS = []


class RichFileHandler(RichHandler):
    # 重命名，用于区分文件日志处理器
    pass


class RichRenderableHandler(RichHandler):
    """将渲染对象传递给回调函数的日志处理器。"""

    def __init__(self, *args, func: Callable[[ConsoleRenderable], None] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._func = func

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        traceback = None
        if (
                self.rich_tracebacks
                and record.exc_info
                and record.exc_info != (None, None, None)
        ):
            exc_type, exc_value, exc_traceback = record.exc_info
            assert exc_type is not None
            assert exc_value is not None
            traceback = Traceback.from_exception(
                exc_type,
                exc_value,
                exc_traceback,
                width=self.tracebacks_width,
                extra_lines=self.tracebacks_extra_lines,
                theme=self.tracebacks_theme,
                word_wrap=self.tracebacks_word_wrap,
                show_locals=self.tracebacks_show_locals,
                locals_max_length=self.locals_max_length,
                locals_max_string=self.locals_max_string,
            )
            message = record.getMessage()
            if self.formatter:
                record.message = record.getMessage()
                formatter = self.formatter
                if hasattr(formatter, "usesTime") and formatter.usesTime():
                    record.asctime = formatter.formatTime(
                        record, formatter.datefmt)
                message = formatter.formatMessage(record)

        message_renderable = self.render_message(record, message)
        log_renderable = self.render(
            record=record, traceback=traceback, message_renderable=message_renderable
        )

        # 直接将渲染对象传入回调函数
        self._func(log_renderable)

    def handle(self, record: logging.LogRecord) -> bool:
        if not self._func:
            return True
        super().handle(record)


class RichTimedRotatingHandler(TimedRotatingFileHandler):
    ZIPMAP = {
        "gzip": "gz",
        "gz" : "gz",
        "bz2" : "bz2",
        "xz": "xz",
        "zip": "zip",
    }
    def __init__(self, pname:str, *args, **kwargs) -> None:
        count, bak_method, zip_method = self._read_file_logger_config(pname)
        TimedRotatingFileHandler.__init__(self, backupCount=count,* args, **kwargs)
        self.console = Console(file=io.StringIO(), no_color=True, highlight=False, width=119)
        self.richd = RichHandler(
            console=self.console,
            show_path=False,
            show_time=False,
            show_level=False,
            rich_tracebacks=True,
            tracebacks_show_locals=True,
            tracebacks_extra_lines=3,
            highlighter=NullHighlighter(),
        )
        # 保持一致的日志格式
        self.richd.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s.%(msecs)03d | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        # 用于兼容 alas.save_error_log() 接口
        self.log_file = None
        # 用于 expire 方法
        self.pname = pname
        self.bak = bak_method.lower()
        self.compression = zip_method.lower()

        # 覆盖初始 rolloverAt 和 rich.console.file
        self.rolloverAt = time.time()
        self.doRollover()

        # 关闭不必要的文件流
        self.stream.close()
        self.stream = None
    
    def _read_file_logger_config(self, process_name):
        cfg_name = "alas" if process_name == "gui" else process_name
        config_file = Path("./config").joinpath(f"{cfg_name}.json")
        if config_file.exists():
            try:
                with config_file.open("r", encoding="utf-8") as f:
                    config = json.load(f)
                    log_config = config.get("General", {}).get("Log", {})
                    count = log_config.get("LogKeepCount", 7)
                    bak_method = log_config.get("LogBackUpMethod", "copy")
                    zip_method = log_config.get("ZipMethod", "bz2")
            except Exception as e:
                logging.exception(e)
                count = 7
                bak_method = "copy"
                zip_method = "bz2"
        else:
            count = 7
            bak_method = "zip" if process_name == "gui" else "copy"
            zip_method = "bz2"
        return count, bak_method, zip_method

    def getFilesToDelete(self) -> List[Path]:
        """确定日志轮转时需要删除的旧日志文件。

        覆盖原始方法，使用 RichHandler 并保持统一的日志格式。
        """
        dirName, baseName = os.path.split(self.baseFilename)
        fileNames = os.listdir(dirName)
        result = []
        suffix = "_" + baseName
        plen = len(suffix)
        for fileName in fileNames:
            if fileName[-plen:] == suffix:
                prefix = fileName[:-plen]
                if self.extMatch.match(prefix):
                    result.append(Path(dirName).joinpath(fileName).resolve())
        if len(result) < self.backupCount:
            result = []
        else:
            result.sort()
            result = result[: len(result) - self.backupCount]
        return result

    def doRollover(self) -> None:
        """执行日志轮转。

        覆盖原始方法，使用 RichHandler 处理日志输出。
        """
        if self.richd.console:
            self.richd.console.file.close()
            self.richd.console.file = None

        currentTime = int(time.time())
        dstNow = time.localtime(currentTime)[-1]
        t = self.rolloverAt
        if self.utc:
            timeTuple = time.gmtime(t)
        else:
            timeTuple = time.localtime(t)
            dstThen = timeTuple[-1]
            if dstNow != dstThen:
                if dstNow:
                    addend = 3600
                else:
                    addend = -3600
                timeTuple = time.localtime(t + addend)

        path = Path(self.baseFilename)
        # 2021-08-01 + _ + alas.txt -> "2021-08-01_alas.txt"
        newPath = path.with_name(
            time.strftime(self.suffix, timeTuple) + "_" + path.name
        )
        self.richd.console.file = open(newPath, "a", encoding="utf-8")

        if self.backupCount > 0:
            files = self.getFilesToDelete()
            if files:
                threading.Thread(target=self.expire, args=(files,), daemon=True).start()
                # self.expire(files)

        newRolloverAt = self.computeRollover(currentTime)
        while newRolloverAt <= currentTime:
            newRolloverAt = newRolloverAt + self.interval
        # 如果跨越夏令时边界且为午夜或周轮转，需要调整时间
        if (self.when == "MIDNIGHT" or self.when.startswith("W")) and not self.utc:
            dstAtRollover = time.localtime(newRolloverAt)[-1]
            if dstNow != dstAtRollover:
                if (
                    not dstNow
                ):  # 夏令时在下次轮转前生效，需要减去一小时
                    addend = -3600
                else:  # 夏令时在下次轮转前结束，需要加上一小时
                    addend = 3600
                newRolloverAt += addend
        self.rolloverAt = newRolloverAt

        self.log_file = str(newPath.resolve())

    def expire(self, files: List[Path]) -> None:
        """删除或备份过期的日志文件。

        处理模板:
            2021-08-01_alas.txt...2021-08-07_alas.txt   ->  bak/2021-08-01~2021-08-07_alas.tar.bz2
            2021-08-01_gui.txt                          ->  bak/2021-08-01_gui.zip
            2021-08-01_gui.txt(copy)                    ->  bak/2021-08-01_gui.txt(copy)
        """
        basePath = Path(self.baseFilename)
        bakPath = basePath.parent / "bak"
        bakPath.mkdir(parents=True, exist_ok=True)
        if self.bak == "delete":
            for file in files:
                file.unlink()
            return
        elif self.bak == "copy":
            for file in files:
                dst = bakPath.joinpath(file.name)
                if not dst.exists():
                    shutil.copy2(file, dst)
                file.unlink()
            return
        try:
            dates = [file.stem.split("_")[0] for file in files]
            name = (
                min(dates) + "~" + max(dates) + "_" + basePath.name
                if len(dates) > 1
                else files[0].name
            )
            ext = self.ZIPMAP[self.compression]
            if ext == "zip":
                zipFile = bakPath.joinpath(name).with_suffix(".zip")
                with zipfile.ZipFile(zipFile, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for file in files:
                        zipf.write(file, arcname=file.name)
                        file.unlink()
            else:
                zipFile = bakPath.joinpath(name).with_suffix(".tar." + ext)
                with tarfile.open(zipFile, "w:" + ext) as tar:
                    for file in files:
                        tar.add(file, arcname=file.name)
                        file.unlink()
        except Exception as e:
            logger.exception(e)

    def print(self, *objects: ConsoleRenderable, **kwargs) -> None:
        Console.print(self.console, *objects, **kwargs)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.shouldRollover(record):
                self.doRollover()
            RichHandler.emit(self.richd, record)
        except Exception:
            RichHandler.handleError(self.richd, record)


class _RuntimeLogState:
    """单进程宿主中一个 worker 的日志输出目标。"""

    __slots__ = ('config_name', 'renderable_sink', 'file_handler', 'log_file')

    def __init__(self):
        self.config_name = ''
        self.renderable_sink = None
        self.file_handler = None
        self.log_file = None


_RUNTIME_LOG_OWNER = object()
_runtime_log_handler_lock = threading.RLock()


def _get_runtime_log_state():
    """返回当前 worker 的日志状态；传统进程模式返回 ``None``。"""
    if get_runtime_context() is None:
        return None
    return runtime_state(_RUNTIME_LOG_OWNER, 'logger', _RuntimeLogState)


class RuntimeFileHandler(logging.Handler):
    """将全局 logger 的记录路由到当前 worker 的独立日志文件。"""

    def emit(self, record: logging.LogRecord) -> None:
        state = _get_runtime_log_state()
        if state is None or state.file_handler is None:
            return
        state.file_handler.emit(record)


class RuntimeRichRenderableHandler(RichRenderableHandler):
    """将 WebUI 渲染对象路由到当前 worker 的队列。"""

    def emit(self, record: logging.LogRecord) -> None:
        state = _get_runtime_log_state()
        if state is None or state.renderable_sink is None:
            return
        super().emit(record)

    @staticmethod
    def _dispatch(renderable: ConsoleRenderable) -> None:
        state = _get_runtime_log_state()
        if state is None or state.renderable_sink is None:
            return
        try:
            state.renderable_sink(renderable)
        except Exception:
            # WebUI 队列关闭不能反向终止自动化线程。
            pass


class HTMLConsole(Console):
    """强制启用完整功能的控制台（用于 Web 输出）。

    注意：目前部分功能尚未生效。
    """

    @property
    def options(self) -> ConsoleOptions:
        return ConsoleOptions(
            max_height=self.size.height,
            size=self.size,
            legacy_windows=False,
            min_width=1,
            max_width=self.width,
            encoding='utf-8',
            is_terminal=False,
        )


class Highlighter(RegexHighlighter):
    base_style = 'web.'
    highlights = [
        # (r'(?P<datetime>(\d{2}|\d{4})(?:\-)?([0]{1}\d{1}|[1]{1}[0-2]{1})'
        #  r'(?:\-)?([0-2]{1}\d{1}|[3]{1}[0-1]{1})(?:\s)?([0-1]{1}\d{1}|'
        #  r'[2]{1}[0-3]{1})(?::)?([0-5]{1}\d{1})(?::)?([0-5]{1}\d{1}).\d+\b)'),
        (r'(?P<time>([0-1]{1}\d{1}|[2]{1}[0-3]{1})(?::)?'
         r'([0-5]{1}\d{1})(?::)?([0-5]{1}\d{1})(.\d+\b))'),
        r"(?P<brace>[\{\[\(\)\]\}])",
        r"\b(?P<bool_true>True)\b|\b(?P<bool_false>False)\b|\b(?P<none>None)\b",
        r"(?P<path>(([A-Za-z]\:)|.)?\B([\/\\][\w\.\-\_\+]+)*[\/\\])(?P<filename>[\w\.\-\_\+]*)?",
        # r"(?<![\\\w])(?P<str>b?\'\'\'.*?(?<!\\)\'\'\'|b?\'.*?(?<!\\)\'|b?\"\"\".*?(?<!\\)\"\"\"|b?\".*?(?<!\\)\")",
    ]


WEB_THEME = Theme({
    "web.brace": Style(bold=True),
    "web.bool_true": Style(color="bright_green", italic=True),
    "web.bool_false": Style(color="bright_red", italic=True),
    "web.none": Style(color="magenta", italic=True),
    "web.path": Style(color="magenta"),
    "web.filename": Style(color="bright_magenta"),
    "web.str": Style(color="green", italic=False, bold=False),
    "web.time": Style(color="cyan"),
    "rule.text": Style(bold=True),
})

# 日志初始化
logger_debug = False
logger = logging.getLogger('alas')
logger.setLevel(logging.DEBUG if logger_debug else logging.INFO)
file_formatter = logging.Formatter(
    fmt='%(asctime)s.%(msecs)03d | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
console_formatter = logging.Formatter(
    fmt='%(asctime)s.%(msecs)03d │ %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
web_formatter = logging.Formatter(
    fmt='%(asctime)s.%(msecs)03d │ %(message)s', datefmt='%H:%M:%S')

# 添加控制台日志处理器
# console = logging.StreamHandler(stream=sys.stdout)
# console.setFormatter(formatter)
# console.flush = sys.stdout.flush
# logger.addHandler(console)

# 添加 Rich 控制台日志处理器
stdout_console = console = Console()
console_hdlr = RichHandler(
    show_path=False,
    show_time=False,
    rich_tracebacks=True,
    tracebacks_show_locals=True,
    tracebacks_extra_lines=3,
)
console_hdlr.setFormatter(console_formatter)
logger.addHandler(console_hdlr)

# 确保运行在 AzurPilot 根目录下
os.chdir(os.path.join(os.path.dirname(__file__), '../'))

# 添加文件日志处理器
pyw_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]


def _set_file_logger(name=pyw_name):
    if '_' in name:
        name = name.split('_', 1)[0]
    log_file = f'./log/{datetime.date.today()}_{name}.txt'
    try:
        file = logging.FileHandler(log_file, encoding='utf-8')
    except FileNotFoundError:
        os.mkdir('./log')
        file = logging.FileHandler(log_file, encoding='utf-8')
    file.setFormatter(file_formatter)

    logger.handlers = [h for h in logger.handlers if not isinstance(
        h, (logging.FileHandler, RichFileHandler))]
    logger.addHandler(file)
    logger.log_file = log_file


def set_file_logger(name=pyw_name):
    if _get_runtime_log_state() is not None:
        # 单进程宿主会由 set_runtime_log_context() 为每个 worker 配置独立文件。
        # 这里不能替换全局 handler，否则后启动实例会劫持已有实例的日志。
        return
    if "_" in name:
        name = name.split("_", 1)[0]
    # Windows 下有 "SyncManager-N:N"、"MainProcess"、"Process-N"、"gui" 四种进程
    # Linux 下没有 "SyncManager" 进程，只有 "MainProcess"
    if os.name == "nt":
        # Windows 下这些进程无需保存日志文件
        processes = ["SyncManager-", "MainProcess", "Process-"]
        pname = multiprocessing.current_process().name.replace(":", "_")
        # 每个进程在 AzurPilot 启动时只应调用一次。
        if any(isinstance(hdlr, RichTimedRotatingHandler) for hdlr in logger.handlers):
            return
    else:
        processes = []
        pname = name
        for hdlr in logger.handlers:
            if isinstance(hdlr, RichTimedRotatingHandler):
                # 每个进程在 AzurPilot 启动时只应调用一次。
                if hdlr.pname == name:
                    return
                else:
                    logger.handlers = [h for h in logger.handlers if not isinstance(
                        h, (logging.FileHandler, RichTimedRotatingHandler, RichFileHandler))]
    
    log_dir = Path("./log")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir.joinpath(f"{pname}.txt" if name == "gui" else f"{name}.txt")
    if any(p in log_file.name for p in processes):
        return

    hdlr = RichTimedRotatingHandler(
        pname=name,
        filename=str(log_file),
        when="midnight",
        interval=1,
        encoding="utf-8",
    )

    logger.addHandler(hdlr)
    logger.log_file = hdlr.log_file
    try:
        if log_file.exists():
            log_file.unlink()
    except Exception:
        pass


def _ensure_runtime_log_handlers() -> None:
    """安装一次按 ContextVar 路由的日志处理器。"""
    with _runtime_log_handler_lock:
        if not any(isinstance(hdlr, RuntimeFileHandler) for hdlr in logger.handlers):
            logger.addHandler(RuntimeFileHandler())

        if any(
            isinstance(hdlr, RuntimeRichRenderableHandler) for hdlr in logger.handlers
        ):
            return

        console = HTMLConsole(
            force_terminal=False,
            force_interactive=False,
            width=80,
            color_system='truecolor',
            markup=False,
            safe_box=False,
            highlighter=Highlighter(),
            theme=WEB_THEME,
        )
        hdlr = RuntimeRichRenderableHandler(
            func=RuntimeRichRenderableHandler._dispatch,
            console=console,
            show_path=False,
            show_time=False,
            show_level=True,
            rich_tracebacks=True,
            tracebacks_show_locals=True,
            tracebacks_extra_lines=2,
            highlighter=Highlighter(),
        )
        hdlr.setFormatter(web_formatter)
        logger.addHandler(hdlr)


def set_runtime_log_context(
    name: str,
    renderable_sink: Callable[[ConsoleRenderable], None],
) -> str:
    """为当前单进程 worker 设置隔离的文件与 WebUI 日志目标。

    调用方必须已进入 ``runtime_scope(name)``。文件 handler 仅保存在该上下文，
    不会改变其他 worker 的 logger 配置。
    """
    state = _get_runtime_log_state()
    if state is None:
        raise RuntimeError('单进程日志上下文必须在 runtime_scope 内设置')

    if state.file_handler is not None:
        reset_runtime_log_context()
        state = _get_runtime_log_state()
        assert state is not None

    log_dir = Path('./log')
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir.joinpath(f'{name}.txt')
    file_handler = RichTimedRotatingHandler(
        pname=name,
        filename=str(log_file),
        when='midnight',
        interval=1,
        encoding='utf-8',
    )
    try:
        if log_file.exists():
            log_file.unlink()
    except Exception:
        pass

    state.config_name = name
    state.renderable_sink = renderable_sink
    state.file_handler = file_handler
    state.log_file = file_handler.log_file
    _ensure_runtime_log_handlers()
    return state.log_file


def get_runtime_log_file(default=None):
    """返回当前 worker 的日志文件，非单进程模式回退到传入默认值。"""
    state = _get_runtime_log_state()
    if state is None or not state.log_file:
        return default
    return state.log_file


def reset_runtime_log_context() -> None:
    """释放当前 worker 的文件 handler，避免重启实例时重复写入和句柄泄漏。"""
    state = _get_runtime_log_state()
    if state is None:
        return

    file_handler = state.file_handler
    state.renderable_sink = None
    state.file_handler = None
    state.log_file = None
    if file_handler is None:
        return
    try:
        console_file = file_handler.richd.console.file
        if console_file is not None:
            console_file.close()
            file_handler.richd.console.file = None
    except Exception:
        pass
    try:
        file_handler.close()
    except Exception:
        pass


def set_func_logger(func):
    if _get_runtime_log_state() is not None:
        # 单进程宿主已通过 RuntimeRichRenderableHandler 按上下文分流。
        return
    console = HTMLConsole(
        force_terminal=False,
        force_interactive=False,
        width=80,
        color_system='truecolor',
        markup=False,
        safe_box=False,
        highlighter=Highlighter(),
        theme=WEB_THEME
    )
    hdlr = RichRenderableHandler(
        func=func,
        console=console,
        show_path=False,
        show_time=False,
        show_level=True,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        tracebacks_extra_lines=2,
        highlighter=Highlighter(),
    )
    hdlr.setFormatter(web_formatter)
    logger.handlers = [h for h in logger.handlers if not isinstance(
        h, RichRenderableHandler)]
    logger.addHandler(hdlr)


def _get_renderables(
        self: Console, *objects, sep=" ", end="\n", justify=None, emoji=None, markup=None, highlight=None,
) -> List[ConsoleRenderable]:
    """获取可渲染对象列表。

    参考 rich.console.Console.print() 的实现。
    """
    if not objects:
        objects = (NewLine(),)

    render_hooks = self._render_hooks[:]
    with self:
        renderables = self._collect_renderables(
            objects,
            sep,
            end,
            justify=justify,
            emoji=emoji,
            markup=markup,
            highlight=highlight,
        )
        for hook in render_hooks:
            renderables = hook.process_renderables(renderables)
    return renderables


def print(*objects: ConsoleRenderable, **kwargs):
    for hdlr in logger.handlers:
        if isinstance(hdlr, RuntimeRichRenderableHandler):
            state = _get_runtime_log_state()
            if state is None or state.renderable_sink is None:
                continue
            for renderable in _get_renderables(hdlr.console, *objects, **kwargs):
                RuntimeRichRenderableHandler._dispatch(renderable)
        elif isinstance(hdlr, RichRenderableHandler):
            for renderable in _get_renderables(hdlr.console, *objects, **kwargs):
                hdlr._func(renderable)
        elif isinstance(hdlr, RichHandler):
            hdlr.console.print(*objects)
        elif isinstance(hdlr, RichTimedRotatingHandler):
            hdlr.print(*objects, **kwargs)
        elif isinstance(hdlr, RuntimeFileHandler):
            state = _get_runtime_log_state()
            if state is not None and state.file_handler is not None:
                state.file_handler.print(*objects, **kwargs)


def rule(title="", *, characters="─", style="rule.line", end="\n", align="center"):
    rule = Rule(title=title, characters=characters,
                style=style, end=end, align=align)
    print(rule)


def hr(title, level=3):
    title = str(title).upper()
    if level == 1:
        logger.rule(title, characters='═')
        logger.info(title)
    if level == 2:
        logger.rule(title, characters='─')
        logger.info(title)
    if level == 3:
        logger.info(f"[bold]<<< {title} >>>[/bold]", extra={"markup": True})
    if level == 0:
        logger.rule(characters='═')
        logger.rule(title, characters=' ')
        logger.rule(characters='═')


def attr(name, text):
    logger.info('[%s] %s' % (str(name), str(text)))


def attr_align(name, text, front='', align=22):
    name = str(name).rjust(align)
    if front:
        name = front + name[len(front):]
    logger.info('%s: %s' % (name, str(text)))


def show():
    logger.info('INFO')
    logger.warning('WARNING')
    logger.debug('DEBUG')
    logger.error('ERROR')
    logger.critical('CRITICAL')
    logger.hr('hr0', 0)
    logger.hr('hr1', 1)
    logger.hr('hr2', 2)
    logger.hr('hr3', 3)
    logger.info(r'大括号 { [ ( ) ] }')
    logger.info(r'True, False, None')
    logger.info(r'E:/path\\to/alas/alas.exe, /root/alas/, ./relative/path/log.txt')
    local_var1 = 'This is local variable'
    # 异常发生前的行
    raise Exception("Exception")
    # 异常发生后的行


def error_context(title, reason, impact, action, exc=None, level=logging.ERROR, with_traceback=None):
    """输出包含原因、影响和处理建议的统一错误信息。

    ``with_traceback`` 为 ``None`` 时，保持原有行为：传入异常对象则输出完整堆栈。
    """
    message = '\n'.join([
        f'[错误] {title}',
        f'原因：{reason}',
        f'影响：{impact}',
        f'建议：{action}',
    ])
    if exc is not None:
        message += f'\n异常：{type(exc).__name__}: {exc}'
    if with_traceback is None:
        with_traceback = exc is not None
    logger.log(level, message, exc_info=with_traceback)


def exception_context(title, exc, impact, action, level=logging.ERROR):
    """输出未知异常的统一错误信息并保留完整堆栈。"""
    error_context(
        title=title,
        reason=f'程序抛出了 {type(exc).__name__}，具体原因需要结合下方堆栈定位。',
        impact=impact,
        action=action,
        exc=exc,
        level=level,
    )


logger.error_context = error_context
logger.exception_context = exception_context
logger.hr = hr
logger.attr = attr
logger.attr_align = attr_align
logger.set_file_logger = set_file_logger
logger.set_func_logger = set_func_logger
logger.set_runtime_log_context = set_runtime_log_context
logger.reset_runtime_log_context = reset_runtime_log_context
logger.get_runtime_log_file = get_runtime_log_file
logger.rule = rule
logger.print = print
logger.log_file: str

logger.set_file_logger()
logger.hr('启动', level=0)

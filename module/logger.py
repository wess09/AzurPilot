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

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


def empty_function(*args, **kwargs):
    """空操作占位函数，用于屏蔽三方库无意覆盖的 logging 配置。"""
    pass


# cnocr 会在 cnocr.utils 中设置 root logger
# 删除 logging.basicConfig 以避免日志消息重复输出。
logging.basicConfig = empty_function
logging.raiseExceptions = True  # 设为 True 可在控制台看到编码错误

# 移除 HTTP 关键字（GET、POST 等）避免日志高亮误判
RichHandler.KEYWORDS = []


class RichFileHandler(RichHandler):
    """基于 Rich 格式化的文件日志处理器类型标记。"""
    pass


class RichRenderableHandler(RichHandler):
    """将渲染对象传递给回调函数的日志处理器。

    用于捕获 Rich 渲染后的对象并传递给外部流式处理管道（如 WebUI 日志推送）。
    """

    def __init__(self, *args, func: Callable[[ConsoleRenderable], None] = None, **kwargs):
        """初始化可渲染对象日志处理器。

        Args:
            *args: 透传给父类 RichHandler 的位置参数。
            func (Callable[[ConsoleRenderable], None], optional): 接收渲染对象的回调函数。默认为 None。
            **kwargs: 透传给父类 RichHandler 的关键字参数。
        """
        super().__init__(*args, **kwargs)
        self._func = func

    def emit(self, record: logging.LogRecord) -> None:
        """处理日志记录并将渲染结果回调给注册函数。

        Args:
            record (logging.LogRecord): 日志记录对象。
        """
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
        """条件处理单条日志记录。

        Args:
            record (logging.LogRecord): 日志记录对象。

        Returns:
            bool: 回调不存在时直接返回 True，否则执行父类处理。
        """
        if not self._func:
            return True
        return super().handle(record)


class RichTimedRotatingHandler(TimedRotatingFileHandler):
    """按时间轮转并结合 Rich 格式化输出的文件日志处理器。

    支持根据配置文件自动轮转、保留指定历史数量、压缩备份等特性。
    """
    ZIPMAP = {
        "gzip": "gz",
        "gz": "gz",
        "bz2": "bz2",
        "xz": "xz",
        "zip": "zip",
    }

    def __init__(self, pname: str, *args, **kwargs) -> None:
        """初始化时间轮转日志处理器。

        Args:
            pname (str): 进程或配置实例名称。
            *args: 透传给 TimedRotatingFileHandler 的位置参数。
            **kwargs: 透传给 TimedRotatingFileHandler 的关键字参数。
        """
        count, bak_method, zip_method = self._read_file_logger_config(pname)
        # 实际输出直接写入带日期的文件，父类无需创建共享的无日期占位文件。
        kwargs['delay'] = True
        TimedRotatingFileHandler.__init__(self, backupCount=count, *args, **kwargs)
        self.console = Console(file=io.StringIO(), no_color=True, highlight=False, width=119)
        self.richd = RichHandler(
            console=self.console,
            show_path=False,
            show_time=False,
            show_level=False,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
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


    def _read_file_logger_config(self, process_name):
        """读取日志相关配置项。

        Args:
            process_name (str): 进程名称。

        Returns:
            tuple[int, str, str]: 日志保留数、备份方式、压缩格式。
        """
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
        """确定日志轮转时需要删除或归档的旧日志文件。

        覆盖原始方法，使用 RichHandler 并保持统一的日志格式。

        Returns:
            List[Path]: 需要删除或归档的文件路径列表。
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
        """执行日志轮转并创建新的日志文件。

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

        newRolloverAt = self.computeRollover(currentTime)
        while newRolloverAt <= currentTime:
            newRolloverAt = newRolloverAt + self.interval
        # 如果跨越夏令时边界且为午夜或周轮转，需要调整时间
        if (self.when == "MIDNIGHT" or self.when.startswith("W")) and not self.utc:
            dstAtRollover = time.localtime(newRolloverAt)[-1]
            if dstNow != dstAtRollover:
                if not dstNow:  # 夏令时在下次轮转前生效，需要减去一小时
                    addend = -3600
                else:  # 夏令时在下次轮转前结束，需要加上一小时
                    addend = 3600
                newRolloverAt += addend
        self.rolloverAt = newRolloverAt

        self.log_file = str(newPath.resolve())
        # 文件轮转后，归档等读取方需要跟随已绑定处理器的写入路径。
        if self in logger.handlers:
            logger.log_file = self.log_file

    def expire(self, files: List[Path]) -> None:
        """删除或备份过期的日志文件。

        处理模板:
            2021-08-01_alas.txt...2021-08-07_alas.txt   ->  bak/2021-08-01~2021-08-07_alas.tar.bz2
            2021-08-01_gui.txt                          ->  bak/2021-08-01_gui.zip
            2021-08-01_gui.txt(copy)                    ->  bak/2021-08-01_gui.txt(copy)

        Args:
            files (List[Path]): 待清理或归档的文件列表。
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
        """通过内置控制台打印可渲染对象。

        Args:
            *objects (ConsoleRenderable): 可渲染对象。
            **kwargs: 透传给 Console.print 的参数。
        """
        Console.print(self.console, *objects, **kwargs)

    def emit(self, record: logging.LogRecord) -> None:
        """输出日志记录，并在需要时触发日志轮转。

        Args:
            record (logging.LogRecord): 日志记录对象。
        """
        try:
            if self.shouldRollover(record):
                self.doRollover()
            RichHandler.emit(self.richd, record)
        except Exception:
            RichHandler.handleError(self.richd, record)


class HTMLConsole(Console):
    """强制启用完整功能的控制台（用于 Web 输出）。

    注意：目前部分功能尚未生效。
    """

    @property
    def options(self) -> ConsoleOptions:
        """获取适用于 Web 渲染的控制台配置选项。

        Returns:
            ConsoleOptions: 控制台配置选项对象。
        """
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
    """用于 Web 控制台的高亮语法规则解析器。"""
    base_style = 'web.'
    highlights = [
        (r'(?P<time>([0-1]{1}\d{1}|[2]{1}[0-3]{1})(?::)?'
         r'([0-5]{1}\d{1})(?::)?([0-5]{1}\d{1})(.\d+\b))'),
        r"(?P<brace>[\{\[\(\)\]\}])",
        r"\b(?P<bool_true>True)\b|\b(?P<bool_false>False)\b|\b(?P<none>None)\b",
        r"(?P<path>(([A-Za-z]\:)|.)?\B([\/\\][\w\.\-\_\+]+)*[\/\\])(?P<filename>[\w\.\-\_\+]*)?",
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

# 添加 Rich 控制台日志处理器
stdout_console = console = Console()
console_hdlr = RichHandler(
    show_path=False,
    show_time=False,
    rich_tracebacks=True,
    tracebacks_show_locals=False,
    tracebacks_extra_lines=3,
)
console_hdlr.setFormatter(console_formatter)
logger.addHandler(console_hdlr)

# 确保运行在 AzurPilot 根目录下
os.chdir(os.path.join(os.path.dirname(__file__), '../'))

# 添加文件日志处理器
pyw_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]


def get_log_file_path(name, root='.', day=None):
    """按完整实例名定位日志，不将下划线当作任务名分隔符。

    Args:
        name (str): 实例名称。
        root (str, optional): 根目录路径。默认为 '.'。
        day (datetime.date | str, optional): 日期。默认为当天。

    Returns:
        Path: 日志文件路径对象。
    """
    return Path(root) / 'log' / f'{day or datetime.date.today()}_{name}.txt'


def _set_file_logger(name=pyw_name):
    """内部函数：按名称配置简单的单文件日志处理器。

    Args:
        name (str, optional): 实例名称。默认为当前主程序名。
    """
    log_file = str(get_log_file_path(name))
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


def set_file_logger(name=None):
    """绑定完整实例名；只有自动 GUI 日志按 Windows 进程身份过滤。

    Args:
        name (str, optional): 实例名称。若为 None 则自动推断。
    """
    automatic = name is None
    if automatic:
        name = pyw_name
    pname = name
    if os.name == "nt" and automatic and name == "gui":
        pname = multiprocessing.current_process().name.replace(":", "_")
        if pname == "MainProcess" or pname.startswith(("SyncManager-", "Process-", "dependency-sync")):
            return

    log_dir = Path("./log")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir.joinpath(f"{pname}.txt")
    for hdlr in logger.handlers:
        if isinstance(hdlr, RichTimedRotatingHandler) and Path(hdlr.baseFilename) == log_file.resolve():
            return
    # 自动日志之后可能才确定实例身份；切换时关闭旧文件，避免继续写入其他实例。
    for hdlr in logger.handlers[:]:
        if isinstance(hdlr, (logging.FileHandler, RichTimedRotatingHandler, RichFileHandler)):
            logger.removeHandler(hdlr)
            if isinstance(hdlr, RichTimedRotatingHandler):
                hdlr.richd.console.file.close()
            hdlr.close()

    hdlr = RichTimedRotatingHandler(
        pname=name,
        filename=str(log_file),
        when="midnight",
        interval=1,
        encoding="utf-8",
    )

    logger.addHandler(hdlr)
    logger.log_file = hdlr.log_file


def set_console_logger(enabled=True):
    """开关当前进程的控制台日志处理器；WebUI 子进程关闭后只把日志写进文件。

    Args:
        enabled (bool, optional): True 添加控制台处理器，False 移除。默认为 True。
    """
    if enabled:
        if console_hdlr not in logger.handlers:
            logger.addHandler(console_hdlr)
    elif console_hdlr in logger.handlers:
        logger.removeHandler(console_hdlr)


def set_func_logger(func):
    """设置将日志输出传递给回调函数的处理器（用于 WebUI 实时展示）。

    Args:
        func (Callable[[ConsoleRenderable], None]): 接收渲染对象的回调函数。
    """
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
        tracebacks_show_locals=False,
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

    Args:
        self (Console): Console 实例。
        *objects: 待渲染对象。
        sep (str, optional): 分隔符。默认为 " "。
        end (str, optional): 结尾符。默认为 "\\n"。
        justify (str, optional): 对齐方式。默认为 None。
        emoji (bool, optional): 是否开启 emoji。默认为 None。
        markup (bool, optional): 是否解析标记。默认为 None。
        highlight (bool, optional): 是否高亮。默认为 None。

    Returns:
        List[ConsoleRenderable]: 可渲染对象列表。
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
    """统一向当前配置的所有输出处理器打印可渲染对象。

    Args:
        *objects (ConsoleRenderable): 可渲染对象。
        **kwargs: 附加格式化参数。
    """
    for hdlr in logger.handlers:
        if isinstance(hdlr, RichRenderableHandler):
            for renderable in _get_renderables(hdlr.console, *objects, **kwargs):
                hdlr._func(renderable)
        elif isinstance(hdlr, RichHandler):
            hdlr.console.print(*objects)
        elif isinstance(hdlr, RichTimedRotatingHandler):
            hdlr.print(*objects, **kwargs)


def rule(title="", *, characters="─", style="rule.line", end="\n", align="center"):
    """输出横向分隔分割线。

    Args:
        title (str, optional): 标题文字。默认为空。
        characters (str, optional): 组成线条的字符。默认为 "─"。
        style (str, optional): 富文本样式。默认为 "rule.line"。
        end (str, optional): 结尾字符。默认为 "\\n"。
        align (str, optional): 对齐方式。默认为 "center"。
    """
    rule = Rule(title=title, characters=characters,
                style=style, end=end, align=align)
    print(rule)


def hr(title, level=3):
    """分节标题输出（支持 4 级标题）。

    Args:
        title: 标题内容。
        level (int, optional): 标题级别（0~3）。默认为 3。
    """
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
    """输出单行属性名称与对应内容。

    Args:
        name: 属性名。
        text: 属性值。
    """
    logger.info('[%s] %s' % (str(name), str(text)))


def attr_align(name, text, front='', align=22):
    """按固定宽度右对齐输出属性名称与内容。

    Args:
        name: 属性名。
        text: 属性值。
        front (str, optional): 前置补充内容。默认为 ''。
        align (int, optional): 对齐列宽。默认为 22。
    """
    name = str(name).rjust(align)
    if front:
        name = front + name[len(front):]
    logger.info('%s: %s' % (name, str(text)))


def show():
    """测试日志输出样式与示例信息。"""
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

    Args:
        title (str): 错误标题。
        reason (str): 发生原因。
        impact (str): 产生影响。
        action (str): 处理建议。
        exc (Exception, optional): 关联的异常对象。默认为 None。
        level (int, optional): 日志等级。默认为 logging.ERROR。
        with_traceback (bool, optional): 是否包含完整异常堆栈。默认为 None。
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
    """输出未知异常的统一错误信息并保留完整堆栈。

    Args:
        title (str): 错误标题。
        exc (Exception): 异常对象。
        impact (str): 产生影响。
        action (str): 建议操作。
        level (int, optional): 日志级别。默认为 logging.ERROR。
    """
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
logger.rule = rule
logger.print = print
logger.log_file: str

logger.set_file_logger()
logger.hr('启动', level=0)

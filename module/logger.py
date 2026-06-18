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



def set_func_logger(func):
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
        if isinstance(hdlr, RichRenderableHandler):
            for renderable in _get_renderables(hdlr.console, *objects, **kwargs):
                hdlr._func(renderable)
        elif isinstance(hdlr, RichHandler):
            hdlr.console.print(*objects)
        elif isinstance(hdlr, RichTimedRotatingHandler):
            hdlr.print(*objects, **kwargs)


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
    logger.info(r'Brace { [ ( ) ] }')
    logger.info(r'True, False, None')
    logger.info(r'E:/path\\to/alas/alas.exe, /root/alas/, ./relative/path/log.txt')
    local_var1 = 'This is local variable'
    # 异常发生前的行
    raise Exception("Exception")
    # 异常发生后的行


def aggressive_convert(func, level='error'):
    def aggressive_wrapper(msg, *args, **kwargs):
        if isinstance(msg, Exception):
            msg = f'{type(msg).__name__}: {msg}'

        if isinstance(msg, str) and any('\u4e00' <= char <= '\u9fff' for char in msg):
            # 已经包含傲娇语气或特殊字符的消息，不重复叠加
            if '杂鱼' in msg or '哒内' in msg or '大叔' in msg or '笨蛋' in msg:
                return func(msg, *args, **kwargs)

            import random
            if level == 'critical':
                prefixes = [
                    "杂鱼杂鱼~ 没用的大叔这就顶不住了吗？",
                    "哈？连这种小事都报错。真是逊、爆、了！",
                    "噗噗~ 没救了呢，大叔连这点打击都受不了？",
                    "笨——蛋——大叔！报错了啦：",
                ]
                msg = f"{random.choice(prefixes)}\n{msg}"
                if not msg.endswith(('？', '！', '。', '❤')):
                    msg += " ~真是没用呢❤"
            elif level == 'error':
                prefixes = ["杂鱼报错：", "废柴大叔的报错：", "逊毙了："]
                msg = f"{random.choice(prefixes)}{msg} ~杂鱼❤"

        return func(msg, *args, **kwargs)

    return aggressive_wrapper


logger.error = aggressive_convert(logger.error, level='error')
logger.critical = aggressive_convert(logger.critical, level='critical')
logger.hr = hr
logger.attr = attr
logger.attr_align = attr_align
logger.set_file_logger = set_file_logger
logger.set_func_logger = set_func_logger
logger.rule = rule
logger.print = print
logger.log_file: str

logger.set_file_logger()
logger.hr('Start', level=0)

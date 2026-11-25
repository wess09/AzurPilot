"""OCR RPC 服务模块。

基于 zerorpc 实现的 OCR 分布式推理框架，支持将 OCR 识别任务分发到独立的服务器进程。
客户端通过 ModelProxyFactory 获取对应语言的代理对象，自动处理连接失败的回退逻辑。
"""

import argparse
import multiprocessing
import pickle
import signal
import threading
import time

from module.logger import logger
from module.runtime.setting import State

process: multiprocessing.Process = None


class ModelProxy:
    """OCR 模型的 RPC 代理客户端。

    通过 zerorpc 连接远程 OCR 服务器，当服务器不可用时自动回退到本地模型。
    """
    client = None
    online = False
    _address = None
    _owner_thread = None
    _retry_at = 0.0
    _retry_interval = 30.0
    _connection_lock = threading.Lock()

    @classmethod
    def _disconnect(cls):
        """在持锁且属于客户端线程时释放连接。

        关闭异常不影响本地回退。
        """
        client, cls.client = cls.client, None
        cls.online = False
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.warning("关闭OCR服务器连接失败，已弃用该连接")

    @classmethod
    def init(cls, address="127.0.0.1:22268"):
        """在当前线程尝试一次连接，显式调用可跳过故障冷却期。

        zerorpc 的 gevent 客户端不能跨原生线程使用。其他线程或并发调用
        直接回退本地；非阻塞锁也避免同线程 greenlet 等待时互相阻塞。

        Args:
            address (str): OCR 服务器地址，形如 'ip:port'。默认 '127.0.0.1:22268'。

        Returns:
            bool: 连接成功返回 True，失败或跳过返回 False。
        """
        if not cls._connection_lock.acquire(blocking=False):
            return False
        try:
            owner = threading.get_native_id()
            if cls._owner_thread not in (None, owner):
                return False
            cls._disconnect()
            cls._owner_thread = owner
            cls._address = address
            try:
                import zerorpc

                logger.info(f"连接OCR服务器 {address}")
                cls.client = zerorpc.Client(timeout=5)
                cls.client.connect(f"tcp://{address}")
                cls.client.hello()
            except Exception:
                cls._disconnect()
                cls._retry_at = time.monotonic() + cls._retry_interval
                logger.warning("OCR服务器不可用，冷却后重试，暂时使用本地模型")
                return False
            cls.online = True
            cls._retry_at = 0.0
            logger.info("成功连接OCR服务器")
            return True
        finally:
            cls._connection_lock.release()

    @classmethod
    def _ensure_client(cls):
        """所有代理共用健康状态，冷却结束后由调用线程最多尝试一次重连。

        Returns:
            bool: 客户端当前是否可用。
        """
        if cls._owner_thread not in (None, threading.get_native_id()):
            return False
        if cls.online and cls.client is not None:
            return True
        if time.monotonic() < cls._retry_at:
            return False
        address = cls._address or State.deploy_config.OcrClientAddress
        return cls.init(address=address)

    @classmethod
    def close(cls):
        """在客户端所属线程关闭连接，允许后续访问重新初始化。

        Returns:
            bool: 关闭成功返回 True，未获取到锁返回 False。
        """
        if not cls._connection_lock.acquire(blocking=False):
            return False
        try:
            if cls._owner_thread not in (None, threading.get_native_id()):
                return False
            cls._disconnect()
            cls._owner_thread = None
            cls._address = None
            cls._retry_at = 0.0
            return True
        finally:
            cls._connection_lock.release()

    def _call(self, method, *args):
        """统一远程调用、共享故障清理与本地回退，保留本地参数原貌。

        Args:
            method (str): 调用的 OCR 方法名。
            *args: 方法参数。

        Returns:
            Any: OCR 识别结果。
        """
        cls = ModelProxy
        if cls._ensure_client() and cls._connection_lock.acquire(blocking=False):
            try:
                if cls.online and cls.client is not None:
                    remote_args = args
                    if method != "set_cand_alphabet":
                        if method in ("ocr_for_single_lines", "atomic_ocr_for_single_lines", "debug"):
                            images = [image.dumps() for image in args[0]]
                        else:
                            images = args[0].dumps()
                        remote_args = (images, *args[1:])
                    try:
                        return cls.client(method, self.lang, *remote_args)
                    except Exception:
                        cls._disconnect()
                        cls._retry_at = time.monotonic() + cls._retry_interval
                        logger.warning("OCR远程调用失败，冷却后重试，暂时使用本地模型")
            finally:
                cls._connection_lock.release()
        from module.ocr.models import OCR_MODEL
        return getattr(getattr(OCR_MODEL, self.lang), method)(*args)

    def __init__(self, lang) -> None:
        """初始化模型代理。

        Args:
            lang: OCR 模型语言标识，如 'azur_lane'、'ppocr_v6'、'cnocr'、'jp'、'tw'。
        """
        self.lang = lang

    def ocr(self, img_fp):
        """对图像执行 OCR 文本识别。

        Args:
            img_fp: 输入图像，numpy 数组格式。

        Returns:
            OCR 识别结果。
        """
        return self._call("ocr", img_fp)

    def ocr_for_single_line(self, img_fp):
        """对单行文本图像执行 OCR 识别。

        Args:
            img_fp: 输入图像，numpy 数组格式。

        Returns:
            单行 OCR 识别结果。
        """
        return self._call("ocr_for_single_line", img_fp)

    def ocr_for_single_lines(self, img_list):
        """对多张单行文本图像批量执行 OCR 识别。

        Args:
            img_list: 输入图像列表，每项为 numpy 数组格式。

        Returns:
            各图像对应的 OCR 识别结果列表。
        """
        return self._call("ocr_for_single_lines", img_list)

    def set_cand_alphabet(self, cand_alphabet: str):
        """设置 OCR 识别的候选字符集。

        Args:
            cand_alphabet: 候选字符集字符串。

        Returns:
            设置结果。
        """
        return self._call("set_cand_alphabet", cand_alphabet)

    def atomic_ocr(self, img_fp, cand_alphabet=None):
        """使用候选字符集对图像执行原子 OCR 识别。

        Args:
            img_fp: 输入图像，numpy 数组格式。
            cand_alphabet: 候选字符集，为 None 时使用默认字符集。

        Returns:
            OCR 识别结果。
        """
        return self._call("atomic_ocr", img_fp, cand_alphabet)

    def atomic_ocr_for_single_line(self, img_fp, cand_alphabet=None):
        """使用候选字符集对单行文本图像执行原子 OCR 识别。

        Args:
            img_fp: 输入图像，numpy 数组格式。
            cand_alphabet: 候选字符集，为 None 时使用默认字符集。

        Returns:
            单行 OCR 识别结果。
        """
        return self._call("atomic_ocr_for_single_line", img_fp, cand_alphabet)

    def atomic_ocr_for_single_lines(self, img_list, cand_alphabet=None):
        """使用候选字符集对多张单行文本图像批量执行原子 OCR 识别。

        Args:
            img_list: 输入图像列表，每项为 numpy 数组格式。
            cand_alphabet: 候选字符集，为 None 时使用默认字符集。

        Returns:
            各图像对应的 OCR 识别结果列表。
        """
        return self._call("atomic_ocr_for_single_lines", img_list, cand_alphabet)

    def debug(self, img_list):
        """对图像列表执行调试模式 OCR 识别。

        Args:
            img_list: 输入图像列表，每项为 numpy 数组格式。

        Returns:
            调试信息。
        """
        return self._call("debug", img_list)


class ModelProxyFactory:
    """OCR 模型代理工厂。

    通过 __getattribute__ 拦截语言模型属性访问，返回对应的 ModelProxy 实例。
    支持的语言模型：azur_lane、ppocr_v6、cnocr、jp、tw、azur_lane_jp。
    """

    def __getattribute__(self, __name: str) -> ModelProxy:
        """获取指定语言的 OCR 模型代理。

        Args:
            __name: 模型语言标识。

        Returns:
            对应语言的 ModelProxy 实例，或父类属性。
        """
        if __name in ["azur_lane", "ppocr_v6", "cnocr", "jp", "tw", "azur_lane_jp"]:
            ModelProxy._ensure_client()
            return ModelProxy(lang=__name)
        else:
            return super().__getattribute__(__name)

    def close(self):
        """关闭底层 RPC 客户端连接。"""
        ModelProxy.close()


def start_ocr_server(port=22268):
    """启动 OCR RPC 服务器。

    创建 zerorpc 服务器实例并绑定到指定端口，提供远程 OCR 识别服务。
    所有图像数据通过 pickle 序列化传输。

    Args:
        port: 服务器监听端口，默认 22268。
    """
    import zerorpc
    import zmq
    from module.ocr.al_ocr import AlOcr
    from module.ocr.models import OcrModel

    class OCRServer(OcrModel):
        """OCR RPC 服务端实现，继承 OcrModel 以复用模型加载逻辑。"""

        def hello(self):
            """心跳检测，用于客户端验证服务器是否存活。

            Returns:
                str: 固定返回 'hello'。
            """
            return "hello"

        def ocr(self, lang, img_fp):
            """通用 OCR 文本识别。

            Args:
                lang: 模型语言标识。
                img_fp: pickle 序列化的图像数据。

            Returns:
                OCR 识别结果。
            """
            img_fp = pickle.loads(img_fp)
            cnocr: AlOcr = self.__getattribute__(lang)
            return cnocr.ocr(img_fp)

        def ocr_for_single_line(self, lang, img_fp):
            """单行文本 OCR 识别。

            Args:
                lang: 模型语言标识。
                img_fp: pickle 序列化的图像数据。

            Returns:
                单行 OCR 识别结果。
            """
            img_fp = pickle.loads(img_fp)
            cnocr: AlOcr = self.__getattribute__(lang)
            return cnocr.ocr_for_single_line(img_fp)

        def ocr_for_single_lines(self, lang, img_list):
            """多张单行文本图像批量 OCR 识别。

            Args:
                lang: 模型语言标识。
                img_list: pickle 序列化的图像数据列表。

            Returns:
                各图像对应的 OCR 识别结果列表。
            """
            img_list = [pickle.loads(img_fp) for img_fp in img_list]
            cnocr: AlOcr = self.__getattribute__(lang)
            return cnocr.ocr_for_single_lines(img_list)

        def set_cand_alphabet(self, lang, cand_alphabet):
            """设置 OCR 识别的候选字符集。

            Args:
                lang: 模型语言标识。
                cand_alphabet: 候选字符集字符串。

            Returns:
                设置结果。
            """
            cnocr: AlOcr = self.__getattribute__(lang)
            return cnocr.set_cand_alphabet(cand_alphabet)

        def atomic_ocr(self, lang, img_fp, cand_alphabet):
            """使用候选字符集执行原子 OCR 识别。

            Args:
                lang: 模型语言标识。
                img_fp: pickle 序列化的图像数据。
                cand_alphabet: 候选字符集。

            Returns:
                OCR 识别结果。
            """
            img_fp = pickle.loads(img_fp)
            cnocr: AlOcr = self.__getattribute__(lang)
            return cnocr.atomic_ocr(img_fp, cand_alphabet)

        def atomic_ocr_for_single_line(self, lang, img_fp, cand_alphabet):
            """使用候选字符集执行单行文本原子 OCR 识别。

            Args:
                lang: 模型语言标识。
                img_fp: pickle 序列化的图像数据。
                cand_alphabet: 候选字符集。

            Returns:
                单行 OCR 识别结果。
            """
            img_fp = pickle.loads(img_fp)
            cnocr: AlOcr = self.__getattribute__(lang)
            return cnocr.atomic_ocr_for_single_line(img_fp, cand_alphabet)

        def atomic_ocr_for_single_lines(self, lang, img_list, cand_alphabet):
            """使用候选字符集批量执行单行文本原子 OCR 识别。

            Args:
                lang: 模型语言标识。
                img_list: pickle 序列化的图像数据列表。
                cand_alphabet: 候选字符集。

            Returns:
                各图像对应的 OCR 识别结果列表。
            """
            img_list = [pickle.loads(img_fp) for img_fp in img_list]
            cnocr: AlOcr = self.__getattribute__(lang)
            return cnocr.atomic_ocr_for_single_lines(img_list, cand_alphabet)

        def debug(self, lang, img_list):
            """调试模式 OCR 识别。

            Args:
                lang: 模型语言标识。
                img_list: pickle 序列化的图像数据列表。

            Returns:
                调试信息。
            """
            img_list = [pickle.loads(img_fp) for img_fp in img_list]
            cnocr: AlOcr = self.__getattribute__(lang)
            return cnocr.debug(img_list)

    if multiprocessing.parent_process() is not None:
        # Windows 控制台 Ctrl+C 会同时发给子进程；由父进程负责回收，避免 gevent 打印冗余堆栈。
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    server = zerorpc.Server(OCRServer())
    try:
        server.bind(f"tcp://*:{port}")
    except zmq.error.ZMQError:
        logger.error(f"[OCR-RPC] OCR 服务器无法绑定端口 {port}")
        return
    logger.info(f"[OCR-RPC] 服务器监听端口 {port}")
    try:
        server.run()
    except KeyboardInterrupt:
        server.stop()


def start_ocr_server_process(port=22268):
    """在独立子进程中启动 OCR 服务器。

    Args:
        port: 服务器监听端口，默认 22268。
    """
    global process
    if not alive():
        process = multiprocessing.Process(target=start_ocr_server, args=(port,))
        process.start()


def stop_ocr_server_process():
    """终止 OCR 服务器子进程。"""
    global process
    if alive():
        process.kill()
        process = None


def alive() -> bool:
    """检查 OCR 服务器子进程是否存活。

    Returns:
        子进程是否正在运行。
    """
    global process
    if process is not None:
        return process.is_alive()
    else:
        return False


if __name__ == "__main__":
    # 启动 OCR 服务器
    parser = argparse.ArgumentParser(description="Alas OCR service")
    parser.add_argument(
        "--port",
        type=int,
        help="Port to listen. Default to OcrServerPort in deploy setting",
    )
    args, _ = parser.parse_known_args()
    port = args.port or State.deploy_config.OcrServerPort
    start_ocr_server(port=port)

"""OCR RPC 服务模块。

基于 zerorpc 实现的 OCR 分布式推理框架，支持将 OCR 识别任务分发到独立的服务器进程。
客户端通过 ModelProxyFactory 获取对应语言的代理对象，自动处理连接失败的回退逻辑。
"""

import argparse
import multiprocessing
import pickle

from module.logger import logger
from module.webui.setting import State

process: multiprocessing.Process = None


class ModelProxy:
    """OCR 模型的 RPC 代理客户端。

    通过 zerorpc 连接远程 OCR 服务器，当服务器不可用时自动回退到本地模型。
    """
    client = None
    online = True

    @classmethod
    def init(cls, address="127.0.0.1:22268"):
        """初始化 RPC 客户端并连接 OCR 服务器。

        Args:
            address: OCR 服务器地址，格式为 'host:port'。
        """
        import zerorpc

        logger.info(f"Connecting to OCR server {address}")
        cls.client = zerorpc.Client(timeout=5)
        cls.client.connect(f"tcp://{address}")
        try:
            cls.client.hello()
            logger.info("Successfully connected to OCR server")
        except Exception:
            cls.online = False
            logger.warning("Ocr server not running")

    @classmethod
    def close(cls):
        """关闭 RPC 客户端连接。"""
        if cls.client is not None:
            logger.info('Disconnect to OCR server')
            cls.client.close()
            logger.info('Successfully disconnected to OCR server')
            cls.client = None

    def __init__(self, lang) -> None:
        """初始化模型代理。

        Args:
            lang: OCR 模型语言标识，如 'azur_lane'、'cnocr'、'jp'、'tw'。
        """
        self.lang = lang

    def ocr(self, img_fp):
        """对图像执行 OCR 文本识别。

        Args:
            img_fp: 输入图像，numpy 数组格式。

        Returns:
            OCR 识别结果。
        """
        if self.online:
            img_str = img_fp.dumps()
            try:
                return self.client("ocr", self.lang, img_str)
            except Exception:
                self.online = False
        from module.ocr.models import OCR_MODEL
        return OCR_MODEL.__getattribute__(self.lang).ocr(img_fp)

    def ocr_for_single_line(self, img_fp):
        """对单行文本图像执行 OCR 识别。

        Args:
            img_fp: 输入图像，numpy 数组格式。

        Returns:
            单行 OCR 识别结果。
        """
        if self.online:
            img_str = img_fp.dumps()
            try:
                return self.client("ocr_for_single_line", self.lang, img_str)
            except Exception:
                self.online = False
        from module.ocr.models import OCR_MODEL
        return OCR_MODEL.__getattribute__(self.lang).ocr_for_single_line(img_fp)

    def ocr_for_single_lines(self, img_list):
        """对多张单行文本图像批量执行 OCR 识别。

        Args:
            img_list: 输入图像列表，每项为 numpy 数组格式。

        Returns:
            各图像对应的 OCR 识别结果列表。
        """
        if self.online:
            img_str_list = [img_fp.dumps() for img_fp in img_list]
            try:
                return self.client("ocr_for_single_lines", self.lang, img_str_list)
            except Exception:
                self.online = False
        from module.ocr.models import OCR_MODEL
        return OCR_MODEL.__getattribute__(self.lang).ocr_for_single_lines(img_list)

    def set_cand_alphabet(self, cand_alphabet: str):
        """设置 OCR 识别的候选字符集。

        Args:
            cand_alphabet: 候选字符集字符串。

        Returns:
            设置结果。
        """
        if self.online:
            try:
                return self.client("set_cand_alphabet", self.lang, cand_alphabet)
            except Exception:
                self.online = False
        from module.ocr.models import OCR_MODEL
        return OCR_MODEL.__getattribute__(self.lang).set_cand_alphabet(cand_alphabet)

    def atomic_ocr(self, img_fp, cand_alphabet=None):
        """使用候选字符集对图像执行原子 OCR 识别。

        Args:
            img_fp: 输入图像，numpy 数组格式。
            cand_alphabet: 候选字符集，为 None 时使用默认字符集。

        Returns:
            OCR 识别结果。
        """
        if self.online:
            img_str = img_fp.dumps()
            try:
                return self.client("atomic_ocr", self.lang, img_str, cand_alphabet)
            except Exception:
                self.online = False
        from module.ocr.models import OCR_MODEL
        return OCR_MODEL.__getattribute__(self.lang).atomic_ocr(img_fp, cand_alphabet)

    def atomic_ocr_for_single_line(self, img_fp, cand_alphabet=None):
        """使用候选字符集对单行文本图像执行原子 OCR 识别。

        Args:
            img_fp: 输入图像，numpy 数组格式。
            cand_alphabet: 候选字符集，为 None 时使用默认字符集。

        Returns:
            单行 OCR 识别结果。
        """
        if self.online:
            img_str = img_fp.dumps()
            try:
                return self.client("atomic_ocr_for_single_line", self.lang, img_str, cand_alphabet)
            except Exception:
                self.online = False
        from module.ocr.models import OCR_MODEL
        return OCR_MODEL.__getattribute__(self.lang).atomic_ocr_for_single_line(img_fp, cand_alphabet)

    def atomic_ocr_for_single_lines(self, img_list, cand_alphabet=None):
        """使用候选字符集对多张单行文本图像批量执行原子 OCR 识别。

        Args:
            img_list: 输入图像列表，每项为 numpy 数组格式。
            cand_alphabet: 候选字符集，为 None 时使用默认字符集。

        Returns:
            各图像对应的 OCR 识别结果列表。
        """
        if self.online:
            img_str_list = [img_fp.dumps() for img_fp in img_list]
            try:
                return self.client("atomic_ocr_for_single_lines", self.lang, img_str_list, cand_alphabet)
            except Exception:
                self.online = False
        from module.ocr.models import OCR_MODEL
        return OCR_MODEL.__getattribute__(self.lang).atomic_ocr_for_single_lines(img_list, cand_alphabet)

    def debug(self, img_list):
        """对图像列表执行调试模式 OCR 识别。

        Args:
            img_list: 输入图像列表，每项为 numpy 数组格式。

        Returns:
            调试信息。
        """
        if self.online:
            img_str_list = [img_fp.dumps() for img_fp in img_list]
            try:
                return self.client("debug", self.lang, img_str_list)
            except Exception:
                self.online = False
        from module.ocr.models import OCR_MODEL
        return OCR_MODEL.__getattribute__(self.lang).debug(img_list)


class ModelProxyFactory:
    """OCR 模型代理工厂。

    通过 __getattribute__ 拦截语言模型属性访问，返回对应的 ModelProxy 实例。
    支持的语言模型：azur_lane、cnocr、jp、tw、azur_lane_jp。
    """

    def __getattribute__(self, __name: str) -> ModelProxy:
        """获取指定语言的 OCR 模型代理。

        Args:
            __name: 模型语言标识。

        Returns:
            对应语言的 ModelProxy 实例，或父类属性。
        """
        if __name in ["azur_lane", "cnocr", "jp", "tw", "azur_lane_jp"]:
            if ModelProxy.client is None:
                ModelProxy.init(address=State.deploy_config.OcrClientAddress)
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
            """心跳检测，用于客户端验证服务器是否存活。"""
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

    server = zerorpc.Server(OCRServer())
    try:
        server.bind(f"tcp://*:{port}")
    except zmq.error.ZMQError:
        logger.error(f"Ocr server cannot bind on port {port}")
        return
    logger.info(f"Ocr server listen on port {port}")
    server.run()


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

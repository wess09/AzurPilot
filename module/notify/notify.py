"""推送通知（Push Notification）模块。

通过 onepush 库将任务执行结果推送到外部渠道（QQ、微信、Telegram 等）。
支持 YAML 格式的通知配置和 WebUI 本地推送。

主要函数：
    - handle_notify(): 解析 YAML 配置并通过指定渠道发送推送通知。
    - notify_webui(): 向本地 WebUI 服务发送 HTTP POST 通知。
"""

import requests
import onepush.core
import yaml
from onepush import get_notifier
from onepush.core import Provider
from onepush.exceptions import OnePushException
from onepush.providers.custom import Custom
from requests import Response

from module.logger import logger

onepush.core.log = logger

# onepush 的内部请求不传 timeout，推送服务器无响应时会永久阻塞调度线程（issue #824）。
# 覆盖其 Provider.request，为所有推送请求注入默认超时，(连接超时, 读取超时)，单位秒。
PUSH_REQUEST_TIMEOUT = (10, 30)

# 仅在未 patch 过时包装：模块被重复加载时 Provider.request 已是包装函数，
# 二次包装会因模块 dict 原地更新导致原函数引用丢失、无限递归
if not getattr(Provider.request, '_timeout_patched', False):
    _original_provider_request = Provider.request

    def _provider_request_with_timeout(method, url, **kwargs):
        kwargs.setdefault('timeout', PUSH_REQUEST_TIMEOUT)
        return _original_provider_request(method, url, **kwargs)

    _provider_request_with_timeout._timeout_patched = True
    Provider.request = staticmethod(_provider_request_with_timeout)


def handle_notify(_config: str, **kwargs) -> bool:
    """处理推送通知请求。

    解析 YAML 格式的配置，选择通知渠道（如 QQ、微信等），
    并通过 onepush 库发送通知消息。

    Args:
        _config (str): YAML 格式的通知配置字符串，包含 provider 和渠道参数。
        **kwargs: 附加的通知参数，如 title、content 等。

    Returns:
        bool: 通知发送成功返回 True，失败返回 False。
    """
    try:
        config = {}
        for item in yaml.safe_load_all(_config):
            config.update(item)
    except Exception:
        logger.error("加载onepush配置失败，跳过发送")
        return False
    try:
        provider_name: str = config.pop("provider", None)
        if provider_name is None:
            logger.info("未指定推送提供者，跳过发送")
            return False
        notifier: Provider = get_notifier(provider_name)
        required: list[str] = notifier.params["required"]
        config.update(kwargs)

        # 参数预检查
        for key in required:
            if key not in config:
                logger.warning(
                    f"[通知] 推送渠道 {notifier.name} 缺少必需参数 '{key}'"
                )

        if isinstance(notifier, Custom):
            if "method" not in config or config["method"] == "post":
                config["datatype"] = "json"
            if not isinstance(config.get("data"), dict):
                config["data"] = {}
            if "title" in kwargs:
                config["data"]["title"] = kwargs["title"]
            if "content" in kwargs:
                config["data"]["content"] = kwargs["content"]
                if "data" in config and "message" in config["data"] and '${content}' in config["data"]["message"]:
                    config["data"]["message"] = config["data"]["message"].replace("${content}", config["data"]["content"])
                    
        if provider_name.lower() == "gocqhttp":
            access_token = config.get("access_token")
            if access_token:
                config["token"] = access_token

        resp = notifier.notify(**config)
        if resp is None:
            # onepush 内部请求异常被吞（连接失败/超时/SSL 重试失败）时返回 None，
            # 必须显式报失败，否则卡死或推送不可达时日志里无任何失败痕迹
            logger.warning("推送通知失败!")
            logger.warning("[通知] 未收到推送服务器的响应（连接失败或超时）")
            return False
        if isinstance(resp, Response):
            if not 200 <= resp.status_code < 300:
                logger.warning("推送通知失败!")
                logger.warning(f"[通知] HTTP状态码:{resp.status_code}")
                return False
            else:
                if provider_name.lower() == "gocqhttp":
                    return_data: dict = resp.json()
                    if return_data["status"] == "failed":
                        logger.warning("推送通知失败!")
                        logger.warning(
                            f"Return message:{return_data['wording']}")
                        return False
    except OnePushException:
        logger.error("推送通知失败")
        return False
    except Exception as e:
        # 不打印完整异常栈，避免暴露变量信息
        logger.error(e)
        return False

    logger.info("推送通知成功")
    return True


def notify_webui(instance: str, title: str, content: str, **kwargs) -> bool:
    """推送通知到 WebUI 本地端口，供启动器接收。

    向本地 WebUI 服务发送 HTTP POST 请求，传递实例名、标题和内容。
    默认端口为 25548，可通过配置自定义。

    Args:
        instance (str): 触发通知的实例名称。
        title (str): 通知标题。
        content (str): 通知正文内容。
        **kwargs: 其他附加字段，合并到请求体中。

    Returns:
        bool: 推送成功返回 True，失败返回 False。
    """
    try:
        from module.runtime.setting import State
        port = int(State.deploy_config.WebuiPort) or 25548
    except Exception:
        port = 25548
    try:
        payload = {"instance": instance, "title": title, "content": content}
        # IPC 的通知协议只接收这三个字段；第三方推送参数不进入本机通道。
        response = requests.post(
            f"http://127.0.0.1:{port}/api/v2/internal/notifications",
            json=payload,
            timeout=2,
        )
        return response.ok
    except Exception:
        return False

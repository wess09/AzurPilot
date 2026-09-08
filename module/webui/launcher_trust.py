"""启动器信任免密登录的进程内状态与令牌逻辑。

WebUI 若由 alas-launcher 以环境变量 ``ALAS_WEBUI_TRUST_SECRET`` 拉起，
则对携带匹配密钥的回环请求签发短时令牌，允许其在本机窗口预置
``localStorage["password"]`` 实现免密进入；其他浏览器不受影响。

信任密钥与用户 WebUI 密码（--key / deploy.yaml Password）解耦：之后修改
WebUI 密码或由 WebUI 自动生成密码，启动器依旧免密。手动 ``gui.py`` 启动时
该环境变量缺省，免密通道整体关闭，维持原有登录行为。

本模块只依赖标准库，便于独立单元测试。
"""

import secrets
import threading
import time

#: 启动器注入信任密钥的环境变量名（与 alas-launcher 保持一致）
TRUST_SECRET_ENV = "ALAS_WEBUI_TRUST_SECRET"
#: 免密令牌有效期（秒），短时一次性
TOKEN_TTL_SECONDS = 60

_lock = threading.Lock()
_secret: str | None = None       #: 启动器信任密钥，None 表示未启用
_webui_key: str | None = None    #: 当前 WebUI 有效密码
_tokens: dict[str, float] = {}   #: token -> 过期时间戳


def configure(secret, webui_key):
    """WebUI 工厂启动时调用一次，登记信任密钥与当前有效 WebUI 密码。

    Args:
        secret: 启动器信任密钥，None/空表示未由启动器拉起。
        webui_key: 当前生效的 WebUI 密码（可能为 None）。
    """
    global _secret, _webui_key
    with _lock:
        normalized = str(secret or "").strip() or None
        _secret = normalized
        _webui_key = str(webui_key) if webui_key is not None else None
        # 重新配置时清空残留令牌，避免跨配置重放。
        _tokens.clear()


def _enabled_locked() -> bool:
    """已持有 ``_lock`` 时的免密可用性判定，供各函数内部复用。

    单独抽出以便 ``enabled()`` 与 ``issue_token()`` 共享同一判定，避免
    在已持锁时再次获取非重入锁导致死锁。
    """
    if not _secret:
        return False
    return bool(_webui_key is not None and str(_webui_key).strip())


def enabled() -> bool:
    """免密通道是否可用：既由启动器拉起，又确实配置了 WebUI 密码。"""
    with _lock:
        return _enabled_locked()


def check_secret(candidate) -> bool:
    """常数时间比较候选密钥是否与信任密钥一致。"""
    if candidate is None:
        return False
    with _lock:
        secret = _secret
    if not secret:
        return False
    return secrets.compare_digest(str(candidate), secret)


def issue_token():
    """签发一次性免密令牌，未启用时返回 None。"""
    with _lock:
        if not _enabled_locked():
            return None
        token = secrets.token_urlsafe(24)
        _tokens[token] = time.time() + TOKEN_TTL_SECONDS
        return token


def validate_token(token) -> bool:
    """校验令牌是否存在且未过期，过期令牌会被清理。"""
    if not token:
        return False
    now = time.time()
    with _lock:
        expire = _tokens.get(token)
        if expire is None:
            return False
        if now > expire:
            _tokens.pop(token, None)
            return False
    return True


def webui_key():
    """返回当前有效 WebUI 密码，供种子页写入 localStorage。"""
    with _lock:
        return _webui_key


def _reset():
    """清空全部状态，仅用于单元测试。"""
    configure(None, None)

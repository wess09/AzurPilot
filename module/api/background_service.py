"""背景图服务：解析随机图 API 的真实直链，并把图片存进仓内的用户图库。

设计要点：

- **解析不落盘**：``resolve()`` 只把 API 抓一次、跟完重定向（JSON 型 API 再从响应里取图片地址），
  返回真实直链。字节只在 ``gallery_add()`` 里落盘 —— 直链是稳定的真图地址，
  所以“预览”和“存图库”看到的是同一张图，不存在二次随机。
- **服务端代抓**：浏览器跨域时拿不到最终地址与字节，因此解析与保存都由服务端完成。
- **SSRF 防护**：只允许 http/https，逐跳（含每一跳重定向、以及 DNS 解析出的每个地址）
  拒绝内网、回环、链路本地、保留与组播地址；限制跳数、超时与体积；只接受图片/视频内容类型。
"""
from module.base.runtime_params import DOWNLOAD_TIMEOUT
import ipaddress
import json
import tempfile
from functools import wraps

from deploy.atomic import atomic_write
from module.config.transaction import config_transaction
import os
import subprocess
import sys
import hashlib
import socket
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from module.base import http
from module.api.protocol import ApiError
from module.logger import logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIBRARY_DIR = PROJECT_ROOT / 'cache' / 'background' / 'library'
INDEX_FILE = LIBRARY_DIR / 'index.json'

MAX_REDIRECTS = 5
MAX_BYTES = 20 * 1024 * 1024
IMAGE_SUFFIX = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif')
VIDEO_SUFFIX = ('.mp4', '.webm', '.mov')
USER_AGENT = http.BROWSER_USER_AGENT


def _download_get(url, **kwargs):
    if http.is_service_url(url):
        return http.get(url, download=True, **kwargs)
    return requests.get(url, **kwargs)

# 明确列出"代抓绝不允许落到"的网段。用显式清单而不是 ipaddress 的 is_private / is_reserved：
# 后两者把 198.18.0.0/15（基准测试段，也是 Clash 这类 fake-IP 代理的占位地址）也算作私网，
# 一刀切会把正常网站一起打死（本机实测 api.yppp.net 就解析到 198.18.0.97）。
BLOCKED_NETWORKS = tuple(ipaddress.ip_network(item) for item in (
    '0.0.0.0/8',            # 本机/未指定
    '10.0.0.0/8',           # 私网 A
    '100.64.0.0/10',        # 运营商级 NAT
    '127.0.0.0/8',          # 回环
    '169.254.0.0/16',       # 链路本地（含云厂商元数据 169.254.169.254）
    '172.16.0.0/12',        # 私网 B
    '192.168.0.0/16',       # 私网 C
    '224.0.0.0/4',          # 组播
    '::/128', '::1/128',    # IPv6 未指定 / 回环
    'fc00::/7',             # IPv6 唯一本地
    'fe80::/10',            # IPv6 链路本地
))


class BackgroundError(ApiError):
    """背景相关的可预期错误：地址非法、抓取失败、内容不是图片等。可直接展示给用户。"""

    def __init__(self, message: str):
        super().__init__('background', message)


def ensure_public_url(url: str) -> str:
    """校验地址可安全代抓：协议受限，且解析出的每个地址都不能是内网/回环/保留地址。

    Args:
        url: 待校验地址。

    Returns:
        原样返回合法地址。

    Raises:
        BackgroundError: 协议不支持、缺少主机名，或解析到非公网地址。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise BackgroundError('只支持 http / https 地址。')
    host = parsed.hostname
    if not host:
        raise BackgroundError('地址缺少主机名。')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise BackgroundError(f'域名解析失败：{host}') from error
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise BackgroundError(f'无法识别的地址：{address}')
        if any(ip in network for network in BLOCKED_NETWORKS):
            raise BackgroundError(f'拒绝内网或本机地址：{address}')
    return url


def first_image_url(payload: Any) -> Optional[str]:
    """从 JSON 型 API 的响应里取第一个图片地址。

    Args:
        payload: JSON 解析后的数据对象（字符串、字典或列表）。

    Returns:
        匹配到的首个有效图片/视频 URL，未找到则返回 None。
    """
    if isinstance(payload, str):
        return payload if payload.lower().split('?')[0].endswith(IMAGE_SUFFIX + VIDEO_SUFFIX) else None
    if isinstance(payload, dict):
        for value in payload.values():
            found = first_image_url(value)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = first_image_url(value)
            if found:
                return found
    return None


def fetch_once(url: str, *, allow_json: bool) -> Dict[str, str]:
    """抓一次地址：跟完重定向，返回真实直链与内容类型。

    Args:
        url: 待抓地址（随机图 API 或图片直链）。
        allow_json: 允许响应是 JSON（从里面再取一次图片地址）。

    Returns:
        ``{'final_url': ..., 'content_type': ...}``

    Raises:
        BackgroundError: 跳数过多、状态码异常、体积超限或内容类型不是图片/视频。
    """
    current = ensure_public_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        try:
            response = _download_get(
                current, timeout=DOWNLOAD_TIMEOUT, stream=True, allow_redirects=False, headers={'User-Agent': USER_AGENT}
            )
        except (requests.RequestException, http.RequestException) as error:
            raise BackgroundError(f'抓取失败：{type(error).__name__}') from error
        with response:
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get('Location')
                if not location:
                    raise BackgroundError('重定向没有给出目标地址。')
                current = ensure_public_url(requests.compat.urljoin(current, location))
                continue
            if response.status_code >= 400:
                raise BackgroundError(f'目标返回 {response.status_code}。')
            content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
            if content_type.startswith('application/json') or content_type.startswith('text/json'):
                if not allow_json:
                    raise BackgroundError('目标返回的是 JSON，不是图片地址。')
                body = response.raw.read(200_000, decode_content=True)
                try:
                    payload = json.loads(body.decode('utf-8', 'ignore'))
                except ValueError as error:
                    raise BackgroundError('目标返回的 JSON 无法解析。') from error
                found = first_image_url(payload)
                if not found:
                    raise BackgroundError('JSON 里没有找到图片地址。')
                return fetch_once(found, allow_json=False)
            if not (content_type.startswith('image/') or content_type.startswith('video/')):
                raise BackgroundError(f'目标不是图片或视频（{content_type or "未知类型"}）。')
            length = response.headers.get('Content-Length')
            if length and int(length) > MAX_BYTES:
                raise BackgroundError('目标文件超过 20 MB。')
            return {'final_url': current, 'content_type': content_type}
    raise BackgroundError(f'重定向超过 {MAX_REDIRECTS} 跳。')


def resolve(url: str) -> Dict[str, str]:
    """把随机图 API 解析成真实直链。

    只抓取一次并追踪重定向，不将图片字节写入磁盘。

    Args:
        url: 随机图 API 或图片直链地址。

    Returns:
        包含 final_url 和 content_type 的字典。

    Raises:
        BackgroundError: 地址非法、重定向过多或抓取失败。
    """
    return fetch_once(url, allow_json=True)


def _read_index() -> List[Dict[str, Any]]:
    """读取图库索引文件。

    Returns:
        图库条目列表，索引不存在或损坏时返回空列表。
    """
    if not INDEX_FILE.exists():
        return []
    try:
        data = json.loads(INDEX_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        logger.warning(f'[背景图库] 索引损坏，按空处理：{INDEX_FILE}')
        return []


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(str(path), data)


def _gallery_mutation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with config_transaction(LIBRARY_DIR.parent / 'gallery-index.json', timeout=60):
            return function(*args, **kwargs)
    return wrapped


def _write_index(entries: List[Dict[str, Any]]) -> None:
    """将图库条目列表写入索引文件。

    Args:
        entries: 待写入的图库条目列表。
    """
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(INDEX_FILE, json.dumps(entries, ensure_ascii=False, indent=2).encode('utf-8'))


PROXY_DIR = PROJECT_ROOT / 'cache' / 'background' / 'proxy'


def proxy_fetch(url: str) -> tuple:
    """抓取一张图供前端同源显示。

    为什么不让浏览器直接加载直链：不少图库有防盗链或跨域限制，服务端能抓到、浏览器却加载不出来，
    于是界面显示的图与直链行会对不上。让壁纸走这条同源通道，两边必然是同一份字节。
    抓到的字节按地址哈希缓存在 cache/background/proxy（可重建，随时可删）。

    Args:
        url: 图片直链地址。

    Returns:
        包含图片二进制数据和内容类型的元组 (bytes, content_type)。

    Raises:
        BackgroundError: 抓取失败或文件体积超过上限。
    """
    meta = fetch_once(url, allow_json=False)
    digest = hashlib.sha1(meta['final_url'].encode('utf-8')).hexdigest()
    PROXY_DIR.mkdir(parents=True, exist_ok=True)
    cached = PROXY_DIR / digest
    if cached.exists():
        return cached.read_bytes(), meta['content_type']
    try:
        response = _download_get(meta['final_url'], timeout=DOWNLOAD_TIMEOUT, stream=True, headers={'User-Agent': USER_AGENT})
    except (requests.RequestException, http.RequestException) as error:
        raise BackgroundError(f'抓取失败：{type(error).__name__}') from error
    chunks = []
    total = 0
    with response:
        for chunk in response.iter_content(64 * 1024):
            total += len(chunk)
            if total > MAX_BYTES:
                raise BackgroundError('文件超过 20 MB。')
            chunks.append(chunk)
    data = b''.join(chunks)
    cached.write_bytes(data)
    return data, meta['content_type']


def gallery_list() -> List[Dict[str, Any]]:
    """列出图库条目。

    自动剔除磁盘文件已缺失的无效条目。

    Returns:
        包含条目信息的字典列表，每个条目包含 id、name、size、added、kind 等字段。
    """
    entries = [entry for entry in _read_index() if isinstance(entry, dict) and (LIBRARY_DIR / str(entry.get('id', ''))).exists()]
    return entries


def gallery_add(url: str, name: str = '') -> Dict[str, Any]:
    """把一张网图存进图库（服务端代抓，浏览器跨域也能存）。

    Args:
        url: 图片直链（通常是 ``resolve()`` 返回的 ``final_url``）。
        name: 展示用名称，留空则用地址末段。

    Returns:
        新条目字典。

    Raises:
        BackgroundError: 抓取失败、超限或内容不是图片/视频。
    """
    meta = fetch_once(url, allow_json=False)
    suffix = Path(urlparse(meta['final_url']).path).suffix.lower()
    if suffix not in IMAGE_SUFFIX + VIDEO_SUFFIX:
        suffix = '.jpg' if meta['content_type'].startswith('image/') else '.mp4'
    digest = hashlib.sha1(meta['final_url'].encode('utf-8')).hexdigest()[:10]
    identifier = f'{int(time.time() * 1000):x}-{digest}{suffix}'
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    target = LIBRARY_DIR / identifier
    try:
        response = _download_get(meta['final_url'], timeout=DOWNLOAD_TIMEOUT, stream=True, headers={'User-Agent': USER_AGENT})
    except (requests.RequestException, http.RequestException) as error:
        raise BackgroundError(f'抓取失败：{type(error).__name__}') from error
    written = 0
    temporary = None
    try:
        with response, tempfile.NamedTemporaryFile(dir=LIBRARY_DIR.parent, delete=False) as handle:
            temporary = Path(handle.name)
            for chunk in response.iter_content(64 * 1024):
                written += len(chunk)
                if written > MAX_BYTES:
                    raise BackgroundError('文件超过 20 MB，已放弃。')
                handle.write(chunk)
        entry = {
            'id': identifier,
            'name': name or Path(urlparse(meta['final_url']).path).name or identifier,
            'size': written,
            'added': int(time.time()),
            'kind': 'video' if meta['content_type'].startswith('video/') else 'image',
            'source': meta['final_url'],
        }
        with config_transaction(LIBRARY_DIR.parent / 'gallery-index.json', timeout=60):
            os.replace(temporary, target)
            entries = [item for item in _read_index() if item.get('id') != identifier]
            entries.append(entry)
            _write_index(entries)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    logger.info(f'[背景图库] 已存入 {identifier}（{written} 字节）')
    return entry


@_gallery_mutation
def gallery_add_bytes(data: bytes, filename: str, content_type: str = '', *, legacy: bool = False) -> Dict[str, Any]:
    """把浏览器上传的文件存进图库（本地图片走这条；服务端不再去网上抓）。

    Args:
        data: 文件字节。
        filename: 原始文件名，用于展示与推断后缀。
        content_type: 浏览器给出的内容类型，缺省时按后缀判断。

    Returns:
        新条目字典。

    Raises:
        BackgroundError: 空文件、超限或类型不是图片/视频。
    """
    if not data:
        raise BackgroundError('所选文件为空。')
    if len(data) > MAX_BYTES:
        raise BackgroundError('文件超过 20 MB。')
    suffix = Path(filename or '').suffix.lower()
    is_video = content_type.startswith('video/') or suffix in VIDEO_SUFFIX
    if not (content_type.startswith('image/') or is_video or suffix in IMAGE_SUFFIX):
        raise BackgroundError('只支持图片或视频文件。')
    if suffix not in IMAGE_SUFFIX + VIDEO_SUFFIX:
        suffix = '.mp4' if is_video else '.jpg'
    if legacy:
        canonical = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
                     'image/gif': '.gif', 'image/bmp': '.bmp', 'image/avif': '.avif',
                     'video/mp4': '.mp4', 'video/webm': '.webm', 'video/quicktime': '.mov'}
        suffix = canonical.get(content_type.split(';', 1)[0].strip().lower(), suffix)
    digest = hashlib.sha256(data).hexdigest()
    identifier = f'legacy-{digest}{suffix}' if legacy else f'{time.time_ns():x}-{digest[:10]}{suffix}'
    if legacy:
        existing = next((item for item in _read_index() if item.get('id') == identifier), None)
        if existing and (LIBRARY_DIR / identifier).is_file():
            return existing
    _atomic_write(LIBRARY_DIR / identifier, data)
    entry = {
        'id': identifier,
        'name': Path(filename or '').name or identifier,
        'size': len(data),
        'added': int(time.time()),
        'kind': 'video' if is_video else 'image',
        'source': 'upload',
    }
    entries = [item for item in _read_index() if item.get('id') != identifier]
    entries.append(entry)
    _write_index(entries)
    logger.info(f'[背景图库] 已上传 {identifier}（{len(data)} 字节）')
    return entry


@_gallery_mutation
def gallery_remove(identifier: str) -> bool:
    """从图库删除一个条目（包括文件与索引）。

    Args:
        identifier: 条目的唯一标识符（文件名）。

    Returns:
        若成功删除返回 True，若条目不存在则返回 False。
    """
    entries = _read_index()
    kept = [item for item in entries if item.get('id') != identifier]
    if len(kept) == len(entries):
        return False
    (LIBRARY_DIR / identifier).unlink(missing_ok=True)
    _write_index(kept)
    return True


def gallery_open() -> Dict[str, str]:
    """在系统文件管理器里打开图库目录。

    打开的路径是服务端固定的图库目录，不接受任何调用方输入，因此不存在越权打开任意目录的问题；
    服务本身只监听本机（gui.py 绑定 127.0.0.1），所以该操作等同于用户自己在资源管理器中打开该文件夹。

    Returns:
        包含已打开目录路径 'path' 的字典。

    Raises:
        BackgroundError: 调用系统命令打开目录失败。
    """
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == 'nt':
            os.startfile(str(LIBRARY_DIR))  # noqa: S606 - 固定路径，非用户输入
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(LIBRARY_DIR)])
        else:
            subprocess.Popen(['xdg-open', str(LIBRARY_DIR)])
    except OSError as error:
        raise BackgroundError(f'打开文件夹失败：{type(error).__name__}') from error
    return {'path': str(LIBRARY_DIR)}


def gallery_path(identifier: str) -> Optional[Path]:
    """获取图库中某个条目的本地文件路径。

    Args:
        identifier: 条目的唯一标识符（文件名）。

    Returns:
        条目文件的 Path 对象；若不存在、为空或包含非法路径字符则返回 None。
    """
    if not identifier or '/' in identifier or '\\' in identifier or identifier.startswith('.'):
        return None
    path = LIBRARY_DIR / identifier
    return path if path.is_file() else None

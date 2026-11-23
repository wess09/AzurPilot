"""提供完整前端构建目录，区分页面导航与静态资源请求。"""
import mimetypes
import re
from pathlib import Path, PurePosixPath

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles

# 浏览器对 ES module 与样式表做强制 MIME 检查，类型不对就直接拒绝执行，前端整片白屏。
# Windows 上 Python 的 mimetypes 会读注册表的文件关联（而且直接覆盖标准表），
# 系统里 .js 被关联成 text/plain 的机器就会白屏，所以这里写死正确的映射。
WEB_MIME_TYPES = {
    '.js': 'text/javascript',
    '.mjs': 'text/javascript',
    '.css': 'text/css',
}


def ensure_static_mime_types() -> None:
    """把静态资源的 MIME 类型注册到标准映射表，覆盖系统注册表中的错误关联。"""
    for ext, media_type in WEB_MIME_TYPES.items():
        mimetypes.add_type(media_type, ext)


ensure_static_mime_types()


class FrontendAssetFiles(StaticFiles):
    """为 Vite 的构建资源提供缓存，并压缩 JavaScript 和 CSS。"""

    _fingerprinted = re.compile(r'-[A-Za-z0-9_-]{8}\.[^.]+$')
    _compressible = {'.js', '.mjs', '.css'}
    _gzip_disabled = re.compile(r'(?:^|,)\s*gzip\s*;\s*q=0(?:\.0*)?\s*(?:,|$)', re.IGNORECASE)

    def __init__(self, directory: Path):
        super().__init__(directory=directory)
        self._gzip = GZipMiddleware(super().__call__, minimum_size=1024, compresslevel=4)

    async def __call__(self, scope, receive, send):
        # 保留二进制资产和 Range 请求的原始字节表示。
        if (scope['type'] == 'http' and scope['method'] == 'GET'
                and PurePosixPath(scope['path']).suffix in self._compressible):
            headers = Headers(scope=scope)
            if 'range' not in headers and not self._gzip_disabled.search(headers.get('accept-encoding', '')):
                await self._gzip(scope, receive, send)
                return
        await super().__call__(scope, receive, send)

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if self._fingerprinted.search(path):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        if PurePosixPath(path).suffix in self._compressible and 'etag' in response.headers:
            # 原始表示与 gzip 表示共用内容验证器，只能做弱比较。
            response.headers['etag'] = 'W/' + response.headers['etag']
            headers = Headers(scope=scope)
            if (response.status_code == 304 or scope['method'] == 'HEAD' or 'range' in headers
                    or self._gzip_disabled.search(headers.get('accept-encoding', ''))):
                response.headers.add_vary_header('Accept-Encoding')
        return response


class ItemTemplateFiles(StaticFiles):
    """按优先级提供物品图标，缺图时从其他领奖模板目录查找同名图片。"""

    def __init__(self, directories: list[Path]):
        super().__init__(directory=None)
        # 沿用 StaticFiles 的路径边界与缓存校验，不复制图片或公开模板库之外的目录。
        self.all_directories = [str(directory) for directory in directories if directory.is_dir()]


class FrontendFiles(StaticFiles):
    """前端静态文件服务。

    保留 SPA 单页应用路由回退，同时让缺失的静态资源返回真实的 404 状态码。
    """

    async def get_response(self, path: str, scope: dict):
        """处理静态资源或 SPA 页面请求响应。

        对点开头的隐藏内部文件返回 404；若无后缀的路由未命中静态资源，则回退到 index.html。

        Args:
            path: 请求的文件相对路径。
            scope: ASGI 连接作用域字典。

        Returns:
            Response: Starlette 响应对象。

        Raises:
            HTTPException: 隐藏文件访问拒绝 (404) 或带扩展名的文件未找到 (404)。
        """
        # 构建指纹等内部文件不属于公开资源；路径越界仍由 StaticFiles 拦截。
        if any(part.startswith('.') and part not in ('.', '..') for part in PurePosixPath(path).parts):
            raise HTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or PurePosixPath(path).suffix:
                raise
            response = await super().get_response('index.html', scope)
        # public 资源名称不带内容哈希，更新后必须向服务端重新验证缓存。
        response.headers['Cache-Control'] = 'no-cache'
        return response

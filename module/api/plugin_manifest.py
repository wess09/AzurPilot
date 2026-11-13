"""Validate the versioned contributions and assets of an APU package."""

import posixpath
import re
from pathlib import PurePosixPath
from typing import Literal

import tinycss2
from pydantic import Field, ValidationError

from module.api.protocol import Params

ID_PATTERN = r'^[a-z0-9][a-z0-9._-]{0,79}$'
Component = Literal['shell', 'navigation', 'overview', 'scheduler', 'global']
OverviewBlock = Literal['resources', 'scheduler', 'queue', 'logs', 'panels']
Permission = Literal['instance.read', 'storage', 'scheduler.control']
ICON_TYPES = {'.svg', '.png', '.webp', '.jpg', '.jpeg', '.gif', '.avif'}
ASSET_TYPES = {
    '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
    '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.avif': 'image/avif',
    '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf',
    '.json': 'application/json', '.wasm': 'application/wasm',
}


class View(Params):
    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(min_length=1, max_length=100)
    entry: str
    scope: Literal['global', 'instance'] = 'instance'
    icon: str | None = None


class Panel(Params):
    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(min_length=1, max_length=100)
    entry: str
    icon: str | None = None


class Theme(Params):
    navigation: Literal['top', 'left', 'right', 'bottom'] | None = None
    navigationView: str | None = None
    overview: list[OverviewBlock] | None = Field(default=None, min_length=1, max_length=5)
    overviewView: str | None = None
    scheduler: str | None = None
    styles: dict[Component, str] = Field(default_factory=dict)
    replaceSchedulerStyles: bool = False
    icons: dict[Literal['scheduler.start', 'scheduler.stop', 'scheduler.title'], str] = Field(default_factory=dict)


class Manifest(Params):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=80)
    apiVersion: Literal[1]
    theme: Theme | None = None
    permissions: list[Permission] = Field(default_factory=list, max_length=3)
    pages: list[View] = Field(default_factory=list, max_length=20)
    panels: list[Panel] = Field(default_factory=list, max_length=20)


def validate_manifest(manifest, archive):
    try:
        result = Manifest.model_validate(manifest)
    except ValidationError as error:
        path = '.'.join(map(str, error.errors()[0]['loc']))
        raise ValueError(f'插件清单字段无效：{path or "manifest.json"}。') from error
    theme = result.theme
    if not result.name.strip() or not result.version.strip():
        raise ValueError('插件名称和版本不能为空。')
    if theme and theme.overview and len(theme.overview) != len(set(theme.overview)):
        raise ValueError('总览布局不能重复引用同一部件。')
    if theme and theme.replaceSchedulerStyles and 'scheduler' not in theme.styles:
        raise ValueError('替换调度器样式需要提供 theme.styles.scheduler。')
    for views in (result.pages, result.panels):
        if len(views) != len({view.id for view in views}):
            raise ValueError('插件页面或面板 ID 重复。')
    entries = [view.entry for view in (*result.pages, *result.panels)]
    if theme:
        entries.extend(path for path in (theme.scheduler, theme.navigationView, theme.overviewView) if path is not None)
    for path in entries:
        _require_asset(archive, path, {'.html'})
    for view in (*result.pages, *result.panels):
        if view.icon is not None:
            _require_asset(archive, view.icon, ICON_TYPES)
    if theme:
        for slot, path in theme.styles.items():
            _require_asset(archive, path, {'.css'})
            theme_css(archive, path, slot, result.id)
        for path in theme.icons.values():
            _require_asset(archive, path, ICON_TYPES)
    return result.model_dump(exclude_unset=True)


def _require_asset(archive, path, extensions):
    if (path not in archive.namelist() or PurePosixPath(path).suffix.lower() not in extensions
            or archive.getinfo(path).is_dir()):
        raise ValueError(f'找不到有效的插件资源：{path}。')


def theme_css(archive, path, slot, identifier):
    """Scope component rules and allow references to passive files in the same archive."""
    css = archive.read(path).decode('utf-8')
    rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    globals_ = []
    scoped = []
    for rule in rules:
        validate_rule(rule, archive, path, identifier)
        target = globals_ if rule.type == 'at-rule' and rule.lower_at_keyword in ('font-face', 'keyframes') else scoped
        target.append(rule)
    if slot == 'global':
        # 全局槽位不包 @scope：主题需要触达 portal 到 body 的弹层组件，
        # 并在 :root 派生点接管宿主色板（rail-panel/theme 系变量都在那里合成）。
        return tinycss2.serialize(globals_) + tinycss2.serialize(scoped)
    return (tinycss2.serialize(globals_) +
            f'\n@scope ([data-apu-component="{slot}"]) {{\n{tinycss2.serialize(scoped)}\n}}')


def validate_rule(rule, archive, path, identifier):
    if rule.type == 'qualified-rule':
        validate_tokens(rule.prelude, archive, path)
        validate_tokens(rule.content, archive, path)
        return
    if rule.type != 'at-rule' or rule.content is None:
        raise ValueError(f'组件样式含有无效规则：{path}。')
    keyword = rule.lower_at_keyword
    if keyword in ('media', 'supports'):
        validate_tokens(rule.prelude, archive, path)
        for child in tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True):
            if child.type == 'at-rule' and child.lower_at_keyword not in ('media', 'supports'):
                raise ValueError(f'组件样式的条件规则不支持 @{child.lower_at_keyword}。')
            validate_rule(child, archive, path, identifier)
        return
    if keyword == 'keyframes':
        name = tinycss2.serialize(rule.prelude).strip()
    elif keyword == 'font-face':
        declarations = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
        name = next((tinycss2.serialize(item.value).strip().strip('"\'') for item in declarations
                     if item.type == 'declaration' and item.lower_name == 'font-family'), '')
    else:
        raise ValueError(f'组件样式不支持 @{keyword}。')
    if not re.fullmatch(re.escape(f'apu-{identifier}-') + r'[\w-]+', name, flags=re.ASCII):
        raise ValueError(f'组件样式的字体和动画名称须以 apu-{identifier}- 开头。')
    validate_tokens(rule.content, archive, path)


def validate_tokens(tokens, archive, path):
    for token in tokens:
        if token.type == 'error' or token.type == 'at-keyword':
            raise ValueError(f'组件样式含有无效语法或嵌套 @ 规则：{path}。')
        if token.type == 'url':
            validate_url(token.value, archive, path)
        elif token.type == 'function':
            if token.lower_name == 'url':
                arguments = [item for item in token.arguments if item.type not in ('whitespace', 'comment')]
                if len(arguments) != 1 or arguments[0].type != 'string':
                    raise ValueError(f'组件样式的资源路径无效：{path}。')
                validate_url(arguments[0].value, archive, path)
            elif token.lower_name in ('image-set', '-webkit-image-set', 'image', 'src'):
                raise ValueError(f'组件样式请使用 url() 引用包内资源：{path}。')
            else:
                validate_tokens(token.arguments, archive, path)
        elif hasattr(token, 'content'):
            validate_tokens(token.content, archive, path)


def validate_url(url, archive, path):
    if not url or url.startswith('/') or not re.fullmatch(r'[a-zA-Z0-9_./-]+', url):
        raise ValueError(f'组件样式的资源必须使用包内相对路径：{path}。')
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), url))
    _require_asset(archive, resolved, {ext for ext, mime in ASSET_TYPES.items() if mime.startswith(('image/', 'font/'))})

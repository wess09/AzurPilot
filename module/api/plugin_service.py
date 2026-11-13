"""Store imported APU packages and their enabled state in the service config directory."""

import io
import json
import re
import sqlite3
import stat
import zipfile
import zlib
from contextlib import closing
from hashlib import sha256
from pathlib import PurePosixPath

from module.api.plugin_manifest import ASSET_TYPES, ID_PATTERN, theme_css, validate_manifest

MAX_PACKAGE_SIZE = 20 * 1024 * 1024
MAX_UNPACKED_SIZE = 80 * 1024 * 1024
MAX_FILES = 512
PLUGIN_ID = re.compile(ID_PATTERN)


class PluginService:
    def __init__(self, directory):
        self.directory = directory / 'plugins'

    def _connect(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.directory / 'plugins.db', timeout=10)
        connection.execute('''CREATE TABLE IF NOT EXISTS plugins (
            id TEXT PRIMARY KEY, manifest TEXT NOT NULL, package BLOB NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0, revision TEXT NOT NULL
        )''')
        if 'revision' not in {column[1] for column in connection.execute('PRAGMA table_info(plugins)')}:
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                if 'revision' not in {column[1] for column in connection.execute('PRAGMA table_info(plugins)')}:
                    connection.execute("ALTER TABLE plugins ADD COLUMN revision TEXT NOT NULL DEFAULT ''")
                    connection.execute("UPDATE plugins SET revision=lower(hex(randomblob(32)))")
        connection.execute('''CREATE TABLE IF NOT EXISTS plugin_data (
            plugin_id TEXT NOT NULL, scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY (plugin_id, scope, key)
        )''')
        return connection

    @staticmethod
    def validate_package(data):
        if len(data) > MAX_PACKAGE_SIZE:
            raise ValueError('插件包超过大小限制。')
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_FILES or sum(entry.file_size for entry in entries) > MAX_UNPACKED_SIZE:
                    raise ValueError('插件包解压后超过大小限制。')
                names = set()
                for entry in entries:
                    name = entry.filename
                    path = PurePosixPath(name)
                    if (not name or not re.fullmatch(r'[a-zA-Z0-9_./-]+', name) or path.is_absolute() or
                            any(part in ('', '.', '..') for part in name.rstrip('/').split('/')) or
                            entry.orig_filename != name or
                            stat.S_ISLNK(entry.external_attr >> 16) or name in names):
                        raise ValueError('插件包含无效或重复的路径。')
                    names.add(name)
                manifest_info = archive.getinfo('manifest.json')
                if manifest_info.file_size > 65536:
                    raise ValueError('插件清单过大。')
                manifest = json.loads(archive.read(manifest_info))
                if not isinstance(manifest, dict):
                    raise ValueError('插件清单格式无效。')
                if type(manifest.get('apiVersion')) is not int or manifest['apiVersion'] != 1:
                    raise ValueError('插件 API 版本不受支持。')
                if archive.testzip() is not None:
                    raise ValueError('插件包内容损坏。')
                return validate_manifest(manifest, archive)
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError,
                RuntimeError, NotImplementedError, OSError, zlib.error, RecursionError) as error:
            raise ValueError('插件包或清单格式无效。') from error

    def install(self, data):
        manifest = self.validate_package(data)
        with closing(self._connect()) as connection, connection:
            connection.execute('''INSERT INTO plugins (id, manifest, package, revision) VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET manifest=excluded.manifest, package=excluded.package,
                    revision=excluded.revision''',
                (manifest['id'], json.dumps(manifest, ensure_ascii=False, allow_nan=False), data, sha256(data).hexdigest()))
        return manifest

    def list(self):
        with closing(self._connect()) as connection:
            rows = connection.execute('SELECT manifest, enabled, revision FROM plugins ORDER BY id').fetchall()
        return [{'manifest': json.loads(manifest), 'enabled': bool(enabled), 'revision': revision}
                for manifest, enabled, revision in rows]

    def set_enabled(self, identifier, enabled):
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute('UPDATE plugins SET enabled=? WHERE id=?', (enabled, identifier))
            return cursor.rowcount > 0

    def remove(self, identifier):
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute('DELETE FROM plugins WHERE id=?', (identifier,))
            connection.execute('DELETE FROM plugin_data WHERE plugin_id=?', (identifier,))
            return cursor.rowcount > 0

    def asset(self, identifier, revision, path, component=None):
        if not PLUGIN_ID.fullmatch(identifier) or not re.fullmatch(r'[a-f0-9]{64}', revision):
            return None
        media_type = ASSET_TYPES.get(PurePosixPath(path).suffix.lower())
        if media_type is None:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                'SELECT manifest, package FROM plugins WHERE id=? AND revision=? AND enabled=1',
                (identifier, revision)).fetchone()
        if row is None:
            return None
        manifest, package = row
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            if path not in archive.namelist() or archive.getinfo(path).is_dir():
                return None
            if component:
                styles = (json.loads(manifest).get('theme') or {}).get('styles', {})
                if styles.get(component) != path:
                    return None
                return theme_css(archive, path, component, identifier), media_type
            return archive.read(path), media_type

    def storage(self, identifier, scope, key, action, value):
        from module.api.protocol import ApiError

        with closing(self._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT manifest FROM plugins WHERE id=? AND enabled=1', (identifier,)).fetchone()
            if row is None or 'storage' not in json.loads(row[0]).get('permissions', []):
                raise ApiError('PLUGIN_DISABLED', '插件未启用或未声明存储权限')
            params = (identifier, scope, key)
            if action == 'get':
                row = connection.execute(
                    'SELECT value FROM plugin_data WHERE plugin_id=? AND scope=? AND key=?', params).fetchone()
                return {'value': json.loads(row[0]) if row else None}
            if action == 'delete':
                connection.execute('DELETE FROM plugin_data WHERE plugin_id=? AND scope=? AND key=?', params)
                return {'value': None}
            try:
                encoded = json.dumps(value, ensure_ascii=True, allow_nan=False)
            except (ValueError, RecursionError) as error:
                raise ApiError('INVALID_PARAMS', '插件数据必须是有效的 JSON') from error
            if len(encoded) > 65536:
                raise ApiError('INVALID_PARAMS', '单项插件数据不能超过 64 KiB')
            used = connection.execute('''SELECT COALESCE(SUM(length(value)), 0) FROM plugin_data
                WHERE plugin_id=? AND (scope<>? OR key<>?)''', params).fetchone()[0]
            if used + len(encoded) > 1024 * 1024:
                raise ApiError('PLUGIN_STORAGE_FULL', '插件存储已满')
            connection.execute('''INSERT INTO plugin_data (plugin_id, scope, key, value) VALUES (?, ?, ?, ?)
                ON CONFLICT(plugin_id, scope, key) DO UPDATE SET value=excluded.value''', (*params, encoded))
            return {'value': value}

"""在游戏启动前关闭渠道服 SDK 的游戏内悬浮球。

目前支持腾讯应用宝渠道服（YSDK）。YSDK 的 ``IconModule.init()`` 只在进程启动时读取一次
``YSDK_ICON_SWITCH``，为 ``false`` 时不注册登录回调，悬浮球不会被创建。读取顺序为：
云配置 SharedPreferences（``YSDK_CONFIG*.xml``）→ APK 内 ``ysdkconf.ini``。每次登录后
SDK 会清空云配置并写回服务器下发的 ``true``，因此写入 ``false`` 后需要用 ``chattr +i``
锁定文件，使服务器的值只停留在当前进程内存中、无法落盘。

不修改 APK、不注入进程，客户端签名保持不变。关闭配置项不会自动解锁，恢复方法见模块文档。
"""

import secrets
import xml.etree.ElementTree as etree

from module.game_setting.player_prefs import (
    PACKAGE_PATTERN,
    PlayerPrefsError,
    PlayerPrefsManager,
    PlayerPrefsUnsupported,
    PlayerPrefsWriteError,
    _device_lock,
    _serialize_xml,
)
from module.logger import logger

# 使用腾讯 YSDK 的渠道服包名
YSDK_PACKAGES = frozenset({
    'com.tencent.tmgp.bilibili.blhx',
})
YSDK_CONFIG_FILE = 'YSDK_CONFIG.xml'
YSDK_ICON_SWITCH = 'YSDK_ICON_SWITCH'


def _find_switch(root: etree.Element) -> etree.Element | None:
    """查找 YSDK_ICON_SWITCH 节点，类型不符时拒绝修改。

    Args:
        root (etree.Element): XML 根节点。

    Returns:
        etree.Element | None: 开关节点，不存在时返回 None。

    Raises:
        PlayerPrefsUnsupported: 根节点或开关节点类型不符合预期。
    """
    if root.tag != 'map':
        raise PlayerPrefsUnsupported(f'不支持的 YSDK 配置根节点: {root.tag!r}')
    for element in root:
        if element.get('name') == YSDK_ICON_SWITCH:
            if element.tag != 'string':
                raise PlayerPrefsUnsupported('YSDK 悬浮球开关的 XML 类型不是 string')
            return element
    return None


def _parse(content: bytes) -> etree.Element:
    """解析 YSDK 配置 XML。

    Args:
        content (bytes): 原始 XML 字节串。

    Returns:
        etree.Element: XML 根节点。

    Raises:
        PlayerPrefsUnsupported: XML 无法解析。
    """
    try:
        return etree.fromstring(content)
    except etree.ParseError:
        raise PlayerPrefsUnsupported('YSDK 配置文件不是有效的 XML') from None


def ysdk_icon_disabled(content: bytes) -> bool:
    """判断 YSDK 配置中悬浮球是否已关闭。

    Args:
        content (bytes): YSDK_CONFIG.xml 内容。

    Returns:
        bool: 开关值为 false 时返回 True。
    """
    element = _find_switch(_parse(content))
    return element is not None and (element.text or '').strip().lower() == 'false'


def update_ysdk_config_xml(content: bytes) -> tuple[bytes, bool]:
    """将 YSDK_ICON_SWITCH 设为 false，保留其他键。

    Args:
        content (bytes): YSDK_CONFIG.xml 内容。

    Returns:
        tuple[bytes, bool]: 新 XML 内容，以及是否发生修改。
    """
    if ysdk_icon_disabled(content):
        return content, False
    root = _parse(content)
    element = _find_switch(root)
    if element is None:
        element = etree.Element('string', {'name': YSDK_ICON_SWITCH})
        root.append(element)
    element.text = 'false'
    return _serialize_xml(root), True


class ChannelFloatManager(PlayerPrefsManager):
    """复用 PlayerPrefs 的 root 事务，写入并锁定 YSDK 悬浮球开关。"""

    def _config_path(self) -> str:
        """返回 YSDK 云配置文件路径。

        Returns:
            str: 远程 YSDK_CONFIG.xml 路径。

        Raises:
            PlayerPrefsUnsupported: 包名格式不安全。
        """
        if not PACKAGE_PATTERN.fullmatch(self.package):
            raise PlayerPrefsUnsupported('游戏包名格式不安全')
        return f'/data/user/0/{self.package}/shared_prefs/{YSDK_CONFIG_FILE}'

    def _is_immutable(self, remote: str) -> bool:
        """读取文件是否带有 immutable 属性。

        Args:
            remote (str): 远程文件路径。

        Returns:
            bool: 带有 ``i`` 属性返回 True。

        Raises:
            PlayerPrefsUnsupported: 设备不支持 lsattr 或无法读取属性。
        """
        result = self._shell(['lsattr', remote], check=False)
        flags = result.stdout.split(maxsplit=1)
        if result.returncode != 0 or not flags:
            raise PlayerPrefsUnsupported('无法读取 YSDK 配置文件属性')
        return 'i' in flags[0]

    def _set_immutable(self, remote: str, enabled: bool) -> None:
        """设置或清除文件的 immutable 属性。

        Args:
            remote (str): 远程文件路径。
            enabled (bool): True 为加锁，False 为解锁。
        """
        self._shell(['chattr', '+i' if enabled else '-i', remote], error_type=PlayerPrefsWriteError)

    def _apply_locked(self) -> bool:
        """在持有跨进程文件锁的情况下关闭并锁定 YSDK 悬浮球开关。

        Returns:
            bool: 已关闭并锁定返回 True，尚无配置文件或写入未完成返回 False。

        Raises:
            PlayerPrefsUnsupported: 游戏正在运行、未获得 root 或安全检查未通过。
        """
        if not self._wait_until_game_stopped():
            raise PlayerPrefsUnsupported('游戏进程仍在运行，已跳过本次写入')
        if not self._ensure_root():
            raise PlayerPrefsUnsupported('ADB 未获得 root 权限')
        if not self._wait_until_game_stopped():
            raise PlayerPrefsUnsupported('游戏进程在提权期间启动，已取消本次写入')

        config = self._config_path()
        if self._shell(['test', '-f', config], check=False).returncode != 0:
            # 首次安装尚未登录过时 SDK 还没生成云配置，登录一次后下次启动生效
            logger.info('[ChannelFloat] 尚未生成 YSDK 配置文件，将在下次启动游戏时处理')
            return False
        self._cleanup_stale_transaction_files(config)
        self._ensure_no_atomic_backup(config)

        original = self._read_remote_bytes(config, PlayerPrefsUnsupported)
        locked = self._is_immutable(config)
        if locked and ysdk_icon_disabled(original):
            logger.info('[ChannelFloat] YSDK 悬浮球已关闭并锁定，无需写入')
            return True

        modified, changed = update_ysdk_config_xml(original)
        metadata = self._metadata(config)
        temporary = f'{config}.alas-tmp-{secrets.token_hex(8)}.tmp'
        try:
            if locked:
                self._set_immutable(config, False)
            if changed:
                self._write_remote_bytes(temporary, modified, PlayerPrefsWriteError)
                self._restore_metadata(temporary, metadata)
                if self._read_remote_bytes(temporary, PlayerPrefsWriteError) != modified:
                    raise PlayerPrefsWriteError('YSDK 配置临时写入内容校验失败')
                if not self._wait_until_game_stopped():
                    raise PlayerPrefsUnsupported('游戏进程在替换前启动，已取消本次写入')
                self._shell(['mv', temporary, config], error_type=PlayerPrefsWriteError)
            self._set_immutable(config, True)
            if not ysdk_icon_disabled(self._read_remote_bytes(config, PlayerPrefsWriteError)):
                raise PlayerPrefsWriteError('写入后的 YSDK 悬浮球开关不正确')
            if not self._is_immutable(config):
                raise PlayerPrefsWriteError('YSDK 配置文件未能加锁')
        except PlayerPrefsWriteError:
            # 写入失败时原文件未被锁定也无妨：SDK 会照常显示悬浮球，下次启动再尝试
            logger.warning('[ChannelFloat] 关闭 YSDK 悬浮球未完成，本次启动保持原状')
            return False
        finally:
            try:
                self._shell(['rm', '-f', temporary], check=False)
            except PlayerPrefsError:
                logger.warning('[ChannelFloat] 无法清理本次临时写入数据')

        logger.info('[ChannelFloat] 已关闭并锁定 YSDK 悬浮球开关')
        return True

    def apply(self) -> bool:
        """安全关闭渠道服悬浮球；不适用或无法安全执行时不影响常规启动。

        Returns:
            bool: 已关闭并锁定返回 True，其余情况返回 False。
        """
        if self.package not in YSDK_PACKAGES:
            logger.info('[ChannelFloat] 当前包名不是腾讯应用宝渠道服，跳过悬浮球关闭')
            return False
        if getattr(self.device, 'is_over_http', False):
            logger.warning('[ChannelFloat] HTTP 设备不支持关闭渠道服悬浮球，已跳过')
            return False
        try:
            with _device_lock(str(self.device.serial), self.package):
                return self._apply_locked()
        except PlayerPrefsUnsupported:
            logger.warning('[ChannelFloat] 已跳过关闭渠道服悬浮球（安全检查未通过）')
            return False
        finally:
            self._restore_root_state()


def disable_channel_float(device, wait_for_stop: bool = False) -> bool:
    """为当前设备关闭渠道服 SDK 悬浮球的唯一运行时入口。

    Args:
        device: 设备连接实例。
        wait_for_stop (bool): 重启流程中是否轮询等待应用完全退出。

    Returns:
        bool: 已关闭并锁定返回 True，其余情况返回 False。
    """
    return ChannelFloatManager(device, wait_for_stop=wait_for_stop).apply()

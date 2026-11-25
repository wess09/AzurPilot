"""Web 界面部署设置定义。

定义部署设置的数据结构、主题选项、远程访问模式等配置字段。
提供设置的序列化、反序列化及启动运行项管理功能。
"""
import json
from dataclasses import dataclass
from typing import Any

from module.config.utils import LANGUAGES, alas_instance
from module.runtime.setting import State

THEME_OPTIONS = [
    "default",
    "dark",
    "light",
    "advanced_material",
    "dark_advanced_material",
]
REMOTE_ACCESS_MODE_OPTIONS = ["auto", "webrtc", "ssh", "cloudflare"]
TURN_CREDENTIAL_MODE_OPTIONS = ["static", "ephemeral"]
INVALID_INSTANCE_CHARS = set(".\\/:*?\"'<>|")


@dataclass(frozen=True)
class DeployField:
    """部署配置项字段元数据。

    Attributes:
        key: 配置项键名。
        kind: 字段类型（string, bool, int, select, nullable_string, cdn 等）。
        options: 可选值元组。
    """
    key: str
    kind: str = "string"
    options: tuple[str, ...] = ()

    @property
    def label_key(self) -> str:
        """获取界面显示的国际化标签键名。"""
        return f"Gui.DeploySetting.{self.key}"

    @property
    def help_key(self) -> str:
        """获取界面帮助说明的国际化键名。"""
        return f"Gui.DeploySetting.{self.key}Help"


DEPLOY_GROUPS: tuple[tuple[str, tuple[DeployField, ...]], ...] = (
    (
        "Git",
        (
            DeployField("Repository"),
            DeployField("Branch"),
            DeployField("GitExecutable"),
            DeployField("GitProxy", "nullable_string"),
            DeployField("SSLVerify", "bool"),
            DeployField("UseMirrorChyan", "bool"),
            DeployField("MirrorChyanCdk", "nullable_string"),
        ),
    ),
    (
        "Python",
        (
            DeployField("PythonExecutable"),
            DeployField("PypiMirror", "nullable_string"),
            DeployField("InstallDependencies", "bool"),
        ),
    ),
    (
        "Adb",
        (
            DeployField("AdbExecutable"),
            DeployField("ReplaceAdb", "bool"),
            DeployField("AutoConnect", "bool"),
            DeployField("InstallUiautomator2", "bool"),
        ),
    ),
    (
        "Ocr",
        (
            DeployField("UseOcrServer", "bool"),
            DeployField("StartOcrServer", "bool"),
            DeployField("OcrServerPort", "int"),
            DeployField("OcrClientAddress"),
        ),
    ),
    (
        "Update",
        (
            DeployField("EnableReload", "bool"),
            DeployField("CheckUpdateInterval", "int"),
            DeployField("AutoRestartTime", "nullable_string"),
        ),
    ),
    ("Misc", (DeployField("DiscordRichPresence", "bool"),)),
    (
        "RemoteAccess",
        (
            DeployField("EnableRemoteAccess", "bool"),
            DeployField("RemoteAccessMode", "select", tuple(REMOTE_ACCESS_MODE_OPTIONS)),
            DeployField("CloudflareRegistry"),
            DeployField("RemoteAccessPort", "int"),
            DeployField("RemoteAccessPublicPort", "int"),
            DeployField("SSHUser", "nullable_string"),
            DeployField("SSHServer", "nullable_string"),
            DeployField("SSHExecutable", "nullable_string"),
            DeployField("AllowedRedirectHosts", "nullable_string"),
            DeployField("MaxRedirects", "int"),
            DeployField("SignalingServer", "nullable_string"),
            DeployField("StunServers", "nullable_string"),
            DeployField("TurnServers", "nullable_string"),
            DeployField("TurnCredentialMode", "select", tuple(TURN_CREDENTIAL_MODE_OPTIONS)),
        ),
    ),
    (
        "Webui",
        (
            DeployField("WebuiHost"),
            DeployField("WebuiPort", "int"),
            DeployField("Password", "nullable_string"),
            DeployField("WebuiSSLKey", "nullable_string"),
            DeployField("WebuiSSLCert", "nullable_string"),
        ),
    ),
)

# 旧前端兼容字段定义，仅用于兼容历史 deploy.yaml，不呈现在前端配置界面中
LEGACY_DEPLOY_FIELDS = {
    "Language": DeployField("Language", "select", tuple(LANGUAGES)),
    "Theme": DeployField("Theme", "select", tuple(THEME_OPTIONS)),
    "DpiScaling": DeployField("DpiScaling", "bool"),
    "CDN": DeployField("CDN", "cdn"),
}
DEPLOY_FIELDS = {
    **{field.key: field for _, fields in DEPLOY_GROUPS for field in fields},
    **LEGACY_DEPLOY_FIELDS,
}


def deploy_settings_schema(translate) -> dict[str, Any]:
    """返回部署设置表单结构和当前配置值。

    Args:
        translate: 国际化翻译函数。

    Returns:
        dict[str, Any]: 包含表单分组、字段定义、提示及演示模式标识的字典。
    """
    with State.deploy_config.transaction() as values:
        values = values.copy()
    groups = []
    for group, fields in DEPLOY_GROUPS:
        groups.append(
            {
                "key": group,
                "label": translate(f"Gui.DeploySetting.Group{group}"),
                "fields": [
                    {
                        "key": field.key,
                        "type": field.kind,
                        "label": translate(field.label_key),
                        "help": translate(field.help_key),
                        "value": _value_for_api(values.get(field.key)),
                        "options": list(field.options),
                    }
                    for field in fields
                ],
            }
        )

    return {
        "groups": groups,
        "notice": translate("Gui.DeploySetting.RestartNotice"),
        "demo": is_demo_mode(),
    }


def save_deploy_settings(data: dict[str, Any]) -> dict[str, Any]:
    """校验并保存部署设置。

    Args:
        data: 包含配置键值对字典的请求数据。

    Returns:
        dict[str, Any]: 包含已更新字段键名的结果字典。

    Raises:
        PermissionError: 演示模式下禁止修改。
        ValueError: 包含未知项或字段值校验失败。
    """
    if is_demo_mode():
        raise PermissionError("演示模式下不能修改部署设置")

    values = data.get("values", data)
    if not isinstance(values, dict):
        raise ValueError("values 必须是对象")

    updates = {}
    for key, value in values.items():
        if key == "Run":
            continue
        field = DEPLOY_FIELDS.get(key)
        if field is None:
            raise ValueError(f"未知部署配置项: {key}")
        updates[key] = _parse_value(field, value)

    State.deploy_config.update_config(updates)
    return {"updated": sorted(updates)}


def get_startup_run(instance: str) -> dict[str, Any]:
    """获取指定实例在部署配置中的开机自启状态。

    Args:
        instance: 实例名称。

    Returns:
        dict[str, Any]: 包含实例名、是否自启以及自启列表数据的字典。
    """
    instance = _validate_instance_name(instance, require_exists=False)
    with State.deploy_config.transaction() as values:
        raw = values.get("Run")
    runs = parse_run_config(raw)
    return {
        "instance": instance,
        "enabled": instance in runs,
        "run": runs,
        "raw": raw,
    }


def set_startup_run(instance: str, enabled: bool) -> dict[str, Any]:
    """设置指定实例是否随服务启动自动运行。

    Args:
        instance: 实例名称。
        enabled: 是否开启开机自启。

    Returns:
        dict[str, Any]: 更新后的自启状态字典。

    Raises:
        PermissionError: 演示模式下禁止修改。
        ValueError: 参数类型错误或实例不存在。
    """
    if is_demo_mode():
        raise PermissionError("演示模式下不能修改启动时自动运行")
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是布尔值")

    instance = _validate_instance_name(instance, require_exists=True)
    with State.deploy_config.transaction() as values:
        runs = parse_run_config(values.get("Run"))
        if enabled:
            if instance not in runs:
                runs.append(instance)
        else:
            runs = [item for item in runs if item != instance]
        raw = format_run_config(runs)
        values["Run"] = raw
    return {"instance": instance, "enabled": instance in runs, "run": runs, "raw": raw}


def parse_run_config(value: Any) -> list[str]:
    """兼容解析 deploy.yaml 中的 Webui.Run 自启配置。

    Args:
        value: 原始自启配置值（列表、JSON 字符串或逗号分隔串）。

    Returns:
        list[str]: 解析出的实例名称列表。
    """
    if value is None or value is False:
        return []
    if isinstance(value, list):
        items = value
    else:
        text = str(value).strip()
        if not text or text.lower() == "null":
            return []
        items = None
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    items = parsed
            except json.JSONDecodeError:
                items = None
        if items is None:
            items = text.strip("[]").split(",")

    result = []
    seen = set()
    for item in items:
        name = str(item).strip(" \t\r\n'\"")
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def format_run_config(runs: list[str]) -> str | None:
    """将自启实例列表格式化为 JSON 字符串。

    Args:
        runs: 实例名称列表。

    Returns:
        str | None: JSON 字符串；若列表为空返回 None。
    """
    if not runs:
        return None
    return json.dumps(runs, ensure_ascii=False, separators=(",", ":"))


def is_demo_mode() -> bool:
    """检查当前是否处于演示只读模式。

    Returns:
        bool: 环境变量 DEMO 为 '1' 时返回 True，否则返回 False。
    """
    import os

    return os.environ.get("DEMO") == "1"


def _value_for_api(value: Any) -> Any:
    """将配置值转换为前端 API 友好的输出格式。

    Args:
        value: 原始配置值。

    Returns:
        Any: 转换后的值（None 转为空字符串）。
    """
    if value is None:
        return ""
    return value


def _parse_value(field: DeployField, value: Any) -> Any:
    """根据部署字段类型校验并解析前端传入的值。

    Args:
        field: 部署字段元数据。
        value: 待校验的输入值。

    Returns:
        Any: 校验转换后的配置值。

    Raises:
        ValueError: 输入值与字段类型要求不符。
    """
    if field.kind == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError(f"{field.key} 必须是布尔值")

    if field.kind == "int":
        if isinstance(value, bool):
            raise ValueError(f"{field.key} 必须是整数")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"{field.key} 必须是整数") from e
        if parsed < 0:
            raise ValueError(f"{field.key} 不能小于 0")
        if field.key in ('RemoteAccessPort', 'RemoteAccessPublicPort') and parsed > 65535:
            raise ValueError(f"{field.key} 不能大于 65535")
        return parsed

    if field.kind == "select":
        value = str(value or "").strip()
        if value not in field.options:
            raise ValueError(f"{field.key} 的值无效")
        return value

    if field.kind == "nullable_string":
        value = "" if value is None else str(value).strip()
        return value or None

    if field.kind == "cdn":
        if isinstance(value, bool):
            return value
        value = "" if value is None else str(value).strip()
        if not value:
            return False
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None
        return value

    if value is None:
        return ""
    return str(value).strip()


def _validate_instance_name(instance: str, require_exists: bool) -> str:
    """校验实例名称合法性。

    Args:
        instance: 待校验的实例名称。
        require_exists: 是否要求实例在本地配置中必须存在。

    Returns:
        str: 校验并去除两端空格的实例名称。

    Raises:
        ValueError: 名称缺失、含非法字符、以 template 开头或实例不存在。
    """
    instance = str(instance or "").strip()
    if not instance:
        raise ValueError("缺少实例名")
    if set(instance) & INVALID_INSTANCE_CHARS:
        raise ValueError("实例名包含非法字符")
    if instance.lower().startswith("template"):
        raise ValueError("实例名不能以 template 开头")
    if require_exists and instance not in alas_instance():
        raise ValueError(f"实例不存在: {instance}")
    return instance

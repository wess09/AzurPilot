"""
Web界面部署设置定义。

定义部署设置的数据结构、主题选项、远程访问模式等配置字段。
提供设置的序列化、反序列化及启动运行项管理功能。
"""

import json
from dataclasses import dataclass
from typing import Any

from module.config.utils import LANGUAGES, alas_instance
from module.webui.setting import State


THEME_OPTIONS = [
    "default",
    "dark",
    "light",
    "advanced_material",
    "dark_advanced_material",
]
REMOTE_ACCESS_MODE_OPTIONS = ["auto", "webrtc", "ssh"]
TURN_CREDENTIAL_MODE_OPTIONS = ["static", "ephemeral"]
INVALID_INSTANCE_CHARS = set(".\\/:*?\"'<>|")


@dataclass(frozen=True)
class DeployField:
    key: str
    kind: str = "string"
    options: tuple[str, ...] = ()

    @property
    def label_key(self) -> str:
        return f"Gui.DeploySetting.{self.key}"

    @property
    def help_key(self) -> str:
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
        "Runtime",
        (
            DeployField("SingleProcessInstances", "bool"),
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
            DeployField("Language", "select", tuple(LANGUAGES)),
            DeployField("Theme", "select", tuple(THEME_OPTIONS)),
            DeployField("DpiScaling", "bool"),
            DeployField("Password", "nullable_string"),
            DeployField("CDN", "cdn"),
            DeployField("WebuiSSLKey", "nullable_string"),
            DeployField("WebuiSSLCert", "nullable_string"),
        ),
    ),
)

DEPLOY_FIELDS = {
    field.key: field for _, fields in DEPLOY_GROUPS for field in fields
}


def deploy_settings_schema(translate) -> dict[str, Any]:
    """返回部署设置表单结构和值。"""
    State.deploy_config.read()
    values = State.deploy_config.config
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
    """校验并保存部署设置。"""
    if is_demo_mode():
        raise PermissionError("演示模式下不能修改部署设置")

    values = data.get("values", data)
    if not isinstance(values, dict):
        raise ValueError("values 必须是对象")

    State.deploy_config.read()
    updates = {}
    for key, value in values.items():
        if key == "Run":
            continue
        field = DEPLOY_FIELDS.get(key)
        if field is None:
            raise ValueError(f"未知部署配置项: {key}")
        updates[key] = _parse_value(field, value)

    for key, value in updates.items():
        State.deploy_config.config[key] = value

    State.deploy_config.write()
    State.deploy_config.read()
    return {"updated": sorted(updates)}


def get_startup_run(instance: str) -> dict[str, Any]:
    instance = _validate_instance_name(instance, require_exists=False)
    State.deploy_config.read()
    runs = parse_run_config(State.deploy_config.config.get("Run"))
    return {
        "instance": instance,
        "enabled": instance in runs,
        "run": runs,
        "raw": State.deploy_config.config.get("Run"),
    }


def set_startup_run(instance: str, enabled: bool) -> dict[str, Any]:
    if is_demo_mode():
        raise PermissionError("演示模式下不能修改启动时自动运行")
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是布尔值")

    instance = _validate_instance_name(instance, require_exists=True)
    State.deploy_config.read()
    runs = parse_run_config(State.deploy_config.config.get("Run"))

    if enabled:
        if instance not in runs:
            runs.append(instance)
    else:
        runs = [item for item in runs if item != instance]

    State.deploy_config.config["Run"] = format_run_config(runs)
    State.deploy_config.write()
    State.deploy_config.read()

    return get_startup_run(instance)


def parse_run_config(value: Any) -> list[str]:
    """兼容解析 deploy.yaml 中的 Webui.Run。"""
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
    if not runs:
        return None
    return json.dumps(runs, ensure_ascii=False, separators=(",", ":"))


def is_demo_mode() -> bool:
    import os

    return os.environ.get("DEMO") == "1"


def _value_for_api(value: Any) -> Any:
    if value is None:
        return ""
    return value


def _parse_value(field: DeployField, value: Any) -> Any:
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

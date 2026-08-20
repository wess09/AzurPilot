"""WebUI 视图的共享依赖和一次性运行时初始化。"""

import os
import re
import argparse
import json
import queue
import requests
import secrets
import string
import threading
import time
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
from functools import partial
from typing import Any, Callable, Dict, List, Optional, cast

# 在导入 pywebio 之前导入伪造模块，避免加载不必要的 PIL 模块
from module.webui.fake_pil_module import import_fake_pil_module
from module.config.time_source import now as current_time, status as time_source_status

import_fake_pil_module()

import pywebio.output as pywebio_output
import pywebio.pin as pywebio_pin
from pywebio import config as _webconfig
from pywebio.input import actions, file_upload as _file_upload, input_group
from pywebio.output import (
    Output,
    clear,
    close_popup,
    popup,
    put_button as _put_button,
    put_buttons,
    put_collapse,
    put_column,
    put_error,
    put_html,
    put_link,
    put_loading,
    put_markdown,
    put_row,
    put_table,
    put_text,
    put_warning,
    toast,
    use_scope,
)
from pywebio.pin import pin
from pywebio.session import (
    download,
    go_app,
    info,
    local,
    register_thread,
    run_js,
    set_env as _set_env,
    eval_js as _eval_js,
)

import module.webui.lang as lang
from module.config.config import AzurLaneConfig, Function
from module.config.deep import deep_get, deep_iter, deep_set
from module.config.env import IS_ON_PHONE_CLOUD
from module.config.server import to_server
from module.config.task_priority import parse_task_priority, task_priority_from_config
from module.config.utils import (
    DEFAULT_CONFIG_NAME,
    alas_instance,
    alas_template,
    dict_to_kv,
    filepath_args,
    filepath_config,
    is_oobe_needed,
    read_file,
    readable_time,
)
from module.config.utils import time_delta
from module.log_res.log_res import LogRes
from module.logger import logger
from module.ocr.rpc import (
    start_ocr_server_process,
    stop_ocr_server_process,
    wait_for_ocr_server,
)
from module.submodule.submodule import load_config
from module.submodule.utils import get_config_mod
from module.webui.base import Frame
from module.webui.discord_presence import close_discord_rpc, init_discord_rpc
from module.webui.fastapi import asgi_app
from module.webui.lang import _t, t
from module.webui.patch import (
    fix_py37_subprocess_communicate,
    patch_executor,
    patch_mimetype,
)
from module.webui.pin import put_checkbox, put_input, put_select
from module.webui.process_manager import ProcessManager
from module.webui.remote_access import RemoteAccess
from module.webui.setting import State
from module.webui.updater import updater
from module.webui.utils import (
    Icon,
    Switch,
    TaskHandler,
    get_alas_config_listen_path,
    get_localstorage,
    get_localstorage_values,
    load_webui_styles,
    set_localstorage,
    get_window_visibility_state,
    login,
    parse_pin_value,
    raise_exception,
    re_fullmatch,
    to_pin_value,
)
from module.webui.widgets import (
    BinarySwitchButton,
    RichLog,
    T_Output_Kwargs,
    put_icon_buttons,
    put_loading_text,
    put_none,
    put_output,
)
from module.webui.dashboard_utils import get_dashboard_scope_id, get_group_scope_id
from module.webui.event_calculator import (
    build_error_html,
    build_event_calculator_html,
    build_event_calculator_js,
    load_event_calculator,
)
from module.base.device_id import get_device_id

# PyWebIO 1.7.1 未发布 PEP 561 类型信息，运行时装饰器还会扩展下列 API。
# 在共享边界归一化为动态可调用对象，页面模块无需重复写类型忽略标记。
put_scope: Callable[..., Any] = cast(
    Callable[..., Any], getattr(pywebio_output, "put_scope")
)
pin_on_change: Callable[..., Any] = cast(
    Callable[..., Any], getattr(pywebio_pin, "pin_on_change")
)
eval_js: Callable[..., Any] = cast(Callable[..., Any], _eval_js)
file_upload: Callable[..., Any] = cast(Callable[..., Any], _file_upload)
put_button: Callable[..., Any] = cast(Callable[..., Any], _put_button)
set_env: Callable[..., Any] = cast(Callable[..., Any], _set_env)
webconfig: Callable[..., Any] = cast(Callable[..., Any], _webconfig)

patch_executor()
patch_mimetype()
fix_py37_subprocess_communicate()

task_handler = TaskHandler()
RESTRICTED_DEVICE_IDS = {"1", "2"}
RESTRICTED_DEVICE_MESSAGE = (
    "你的公网IP已泄露 请加群https://join.nanoda.work/#/join联系我们解除安全限制"
)
PUBLIC_WEBUI_PASSWORD_GENERATE_FAILED_MESSAGE = "当前配置允许所有设备访问，但自动生成密码失败，请手动在 config/deploy.yaml 设置 Password 后重启。"

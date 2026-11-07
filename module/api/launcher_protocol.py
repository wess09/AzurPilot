"""启动器 v2 严格消息模型；分别声明可接收的方法与响应。"""
from typing import Any, Literal
from pydantic import Field, StrictBool, StrictFloat, StrictStr, model_validator
from module.api.protocol import Params


class AutostartState(Params):
    supported: StrictBool
    enabled: StrictBool | None = None


class HelloParams(Params):
    protocolVersion: Literal[2]
    launcherVersion: StrictStr = Field(min_length=1, max_length=32)
    platform: Literal['win32', 'darwin', 'linux']
    capabilities: list[Literal['autostart', 'notifications', 'login']] = Field(max_length=3)
    autostart: AutostartState


class StateParams(Params):
    autostart: AutostartState


class AckParams(Params):
    ids: list[StrictStr] = Field(min_length=1, max_length=100)


class LauncherRequest(Params):
    type: Literal['request']
    id: StrictStr = Field(min_length=1, max_length=100)
    method: StrictStr = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)


class LauncherCommand(LauncherRequest):
    method: Literal['autostart.get', 'autostart.set']
    deadline: StrictFloat = Field(gt=0)


class NotificationParams(Params):
    instance: StrictStr = Field(default='', max_length=64)
    title: StrictStr = Field(default='', max_length=512)
    content: StrictStr = Field(default='', max_length=8192)


class LauncherEvent(Params):
    type: Literal['event']
    id: StrictStr = Field(min_length=1, max_length=100)
    topic: Literal['notification']
    data: NotificationParams


class LauncherError(Params):
    code: StrictStr = Field(min_length=1, max_length=64)
    message: StrictStr = Field(max_length=256)


class LauncherResponse(Params):
    type: Literal['response']
    id: StrictStr = Field(min_length=1, max_length=100)
    ok: StrictBool
    result: dict[str, Any] | None = None
    error: LauncherError | None = None

    @model_validator(mode='after')
    def check_outcome(self):
        if self.ok and (self.result is None or self.error is not None):
            raise ValueError('成功响应须包含 result')
        if not self.ok and (self.error is None or self.result is not None):
            raise ValueError('失败响应须包含 error')
        return self


#: 托盘「暂停 / 继续任务」：查询、停止所有运行中的实例、恢复被暂停的实例。
SCHEDULER_METHODS = {'scheduler.state': 'state', 'scheduler.pause': 'pause', 'scheduler.resume': 'resume'}

INCOMING_METHODS = {'session.hello': HelloParams, 'state.report': StateParams,
                    'notifications.ack': AckParams, 'login.issue': Params, 'system.ping': Params,
                    **{method: Params for method in SCHEDULER_METHODS}}

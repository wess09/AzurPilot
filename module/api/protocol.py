"""协议信封、错误码及参数类型模块。

定义前后端 WebSocket 通信协议信封、各接口请求参数模型及标准响应封装。
禁止隐式调用任意 Python 方法。
"""

from typing import Any, Literal

from module.scheduler.models import Mode, ProgramDocument

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

VERSION = 1


class ApiError(Exception):
    """可以安全展示给用户的业务异常类。

    Attributes:
        code (str): 错误代码标识。
        message (str): 面向用户的错误描述。
        details (Any, optional): 附加错误细节或诊断数据。
    """

    def __init__(self, code: str, message: str, details: Any = None):
        """初始化业务异常。

        Args:
            code (str): 错误代码。
            message (str): 错误信息。
            details (Any, optional): 细节数据。默认为 None。
        """
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


class Params(BaseModel):
    """API 入参基础模型，禁止额外字段并启用严格类型校验。"""
    model_config = ConfigDict(extra='forbid', strict=True)


class MindShip(Params):
    """可编辑的舰船字段，核对状态与排除状态独立保存。"""
    name: StrictStr = Field(min_length=1, max_length=100)
    level: StrictInt = Field(ge=0, le=125)
    rarity: Literal['', 'N', 'R', 'SR', 'SSR', 'UR'] = ''
    base_rarity: Literal['', 'N', 'R', 'SR', 'SSR', 'UR'] = ''
    excluded: StrictBool = False
    review: StrictBool = False
    source: StrictStr = Field(default='', max_length=200)


class Request(Params):
    """API 顶层请求信封模型。"""
    v: Literal[1]
    type: Literal['request']
    id: StrictStr = Field(min_length=1, max_length=100)
    method: StrictStr = Field(min_length=1, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)


class AuthParams(Params):
    """鉴权请求参数模型。"""
    password: StrictStr = Field(default='', max_length=256)


class AnnouncementParams(Params):
    """公告查询参数模型。"""
    force: StrictBool = False


class SchemaParams(Params):
    """配置界面架构查询参数模型。"""
    language: Literal['zh-CN', 'zh-MIAO', 'en-US', 'ja-JP', 'zh-TW'] = 'zh-CN'


class SearchContentParams(Params):
    """侧栏内容检索请求参数模型。"""
    query: StrictStr = Field(min_length=1, max_length=64)


class BackgroundUrlParams(Params):
    url: StrictStr = Field(min_length=8, max_length=2048)


class BackgroundGalleryAddParams(BackgroundUrlParams):
    name: StrictStr = Field(default='', max_length=120)


class BackgroundGalleryRemoveParams(Params):
    id: StrictStr = Field(min_length=1, max_length=128)


class InstanceParams(Params):
    """单实例操作通用入参模型。"""
    instance: StrictStr = Field(min_length=1, max_length=64)


class MindCalculateParams(InstanceParams):
    ships: list[MindShip] = Field(max_length=5000)


class MindSaveParams(MindCalculateParams):
    revision: StrictStr = Field(min_length=64, max_length=64)


class MindFileParams(InstanceParams):
    filename: StrictStr = Field(min_length=1, max_length=200)
    content: StrictStr = Field(min_length=1, max_length=8_000_000)


class MindExportParams(InstanceParams):
    format: Literal['json', 'csv', 'xlsx'] = 'xlsx'


class StockRequestParams(InstanceParams):
    """实例专属交易请求；实例身份和远端凭据由后端补充。"""
    path: StrictStr = Field(min_length=1, max_length=100)
    method: Literal['GET', 'POST', 'DELETE'] = 'GET'
    body: dict[str, Any] | None = None
    etag: StrictStr = Field(default='', max_length=128)


class StockRebuildParams(InstanceParams):
    """先返回实际重建范围，用户确认后才重建本地交易账户。"""
    confirm: StrictBool = False
    scope: Literal['instance', 'all'] = 'instance'


class CreateParams(Params):
    """新建实例请求参数模型。"""
    name: StrictStr = Field(min_length=1, max_length=64)
    source: StrictStr | None = None
    import_file: StrictStr | None = None


class ImportParams(Params):
    """上传一份配置文件到导入目录，供创建实例时选用。"""

    name: StrictStr = Field(min_length=1, max_length=64)
    content: StrictStr = Field(min_length=2, max_length=2_000_000)


class TaskParams(InstanceParams):
    """单任务控制请求参数模型。"""
    task: StrictStr = Field(min_length=1, max_length=80)


class ProgramValidateParams(InstanceParams):
    """调度程序草稿的校验请求。"""

    document: ProgramDocument
    mode: Mode = 'takeover'


class ProgramSaveParams(InstanceParams):
    """按修订号保存调度程序草稿。"""

    document: ProgramDocument
    revision: StrictStr


class ProgramApplyParams(InstanceParams):
    """把草稿应用到运行中的调度器。"""

    revision: StrictStr
    mode: Mode


class ProgramSimulateParams(ProgramValidateParams):
    """带模拟上下文与步数上限的试运行请求。"""

    context: dict[str, Any] = Field(default_factory=dict)
    outcomes: list[Literal['completed', 'yielded', 'recoverable', 'failed']] = Field(default_factory=list, max_length=1000)
    steps: StrictInt = Field(default=100, ge=1, le=1000)


class ConfigChange(Params):
    """单个配置项修改条目模型。"""
    path: StrictStr = Field(min_length=1, max_length=180)
    value: Any


class PatchParams(InstanceParams):
    """批量配置修改请求参数模型。"""
    revision: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    changes: list[ConfigChange] = Field(min_length=1, max_length=200)


class RevisionParams(InstanceParams):
    """带版本校验的请求参数模型。"""
    revision: StrictStr


class SubscribeParams(Params):
    """WebSocket 主题订阅请求参数模型。"""
    instance: StrictStr | None = None
    topics: list[Literal['instances', 'overview', 'logs', 'preview', 'stock']] = Field(max_length=5)


class LogsParams(InstanceParams):
    """日志获取请求参数模型。"""
    after: StrictInt = Field(default=0, ge=0)


class StatisticsParams(InstanceParams):
    """单资源图表统计请求参数模型。"""
    days: StrictInt = Field(default=7, ge=1, le=90)
    resource: Literal['Oil', 'Coin', 'Gem', 'Cube', 'Pt', 'ActionPoint', 'Core', 'Medal', 'Merit', 'GuildCoin', 'YellowCoin', 'PurpleCoin'] = 'Oil'


class StatisticsReportParams(InstanceParams):
    """综合统计报表请求参数模型。"""
    category: Literal['resources', 'action', 'opsi', 'commission', 'ships', 'loot', 'research', 'storage'] = 'resources'
    month: StrictStr | None = Field(default=None, pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    days: StrictInt = Field(default=7, ge=1, le=365)
    period: Literal['day', 'week', 'month'] = 'month'
    # 科研统计专用：只看某一期（1~9），0 表示最新有记录的一期（界面不再提供该项）
    series: StrictInt = Field(default=0, ge=0, le=20)
    # 科研统计专用：视图口径。series = 按期；consumable = 心智/物资（不分期）。
    # 不分期的口径忽略 series——只有彩装备与舰船图纸绑定期数，心智与物资各期混着出。
    scope: Literal['series', 'consumable'] = 'series'
    # 大世界掉落专用：只看某个大世界任务（任务名转下划线，如 opsi_abyssal）；空表示全部
    task: StrictStr | None = Field(default=None, pattern=r'^[a-z][a-z0-9_]{0,40}$')
    # 图表与原始记录都被隐藏时前端传 false，后端跳过序列的查询与构造
    include_series: StrictBool = True


class ResourceFlowsParams(InstanceParams):
    """资源管理只读区间与明细分页，不触发设备操作。"""
    days: StrictInt = Field(default=7, ge=1, le=365)
    start: StrictStr | None = Field(default=None, max_length=32)
    end: StrictStr | None = Field(default=None, max_length=32)
    resource: StrictStr | None = Field(default=None, pattern=r'^[A-Za-z][A-Za-z0-9_]{0,100}$')
    task: StrictStr | None = Field(default=None, pattern=r'^[A-Za-z][A-Za-z0-9_]{0,100}$')
    offset: StrictInt = Field(default=0, ge=0)
    limit: StrictInt = Field(default=100, ge=1, le=1000)
    through_id: StrictInt | None = Field(default=None, ge=0)


class MeowfficerScoreReportParams(InstanceParams):
    """指挥喵评分报告的只读查询。"""

    limit: StrictInt = Field(default=100, ge=1, le=500)


class MeowfficerClearReportParams(InstanceParams):
    """清空指挥喵评分报告（删掉 json / md / html 三份产物）。"""


class DeployParams(Params):
    """部署配置修改请求参数模型。"""
    values: dict[str, Any]


class CommitsParams(Params):
    """Git 提交记录查询参数模型。"""
    offset: StrictInt = Field(default=0, ge=0)
    limit: StrictInt = Field(default=50, ge=1, le=100)


class StartupParams(InstanceParams):
    """开机启动设置请求参数模型。"""
    enabled: StrictBool | None = None
    remember: StrictBool | None = None


class AccountParams(InstanceParams):
    """独立实例密码只用于当前请求，禁止进入普通配置系统。"""
    action: Literal['create', 'unlock', 'lock', 'list', 'capture', 'select', 'enable', 'password', 'delete', 'bind_tpm', 'unbind_tpm', 'bind_local', 'unbind_local']
    password: StrictStr = Field(default='', max_length=256, repr=False)
    new_password: StrictStr = Field(default='', max_length=256, repr=False)
    label: StrictStr = Field(default='', max_length=64)
    profile: StrictStr = Field(default='', max_length=32)
    enabled: StrictBool = False


def response(request_id, result):
    """组装成功的标准响应协议字典。

    Args:
        request_id (str): 对应的请求 ID。
        result (Any): 返回的业务结果。

    Returns:
        dict: 封装后的响应报文。
    """
    return {'v': VERSION, 'type': 'response', 'id': request_id, 'ok': True, 'result': result}


def failure(request_id, error: ApiError):
    """组装失败的标准错误响应协议字典。

    Args:
        request_id (str): 对应的请求 ID。
        error (ApiError): 业务异常对象。

    Returns:
        dict: 封装后的错误响应报文。
    """
    return {'v': VERSION, 'type': 'response', 'id': request_id, 'ok': False,
            'error': {'code': error.code, 'message': error.message, 'details': error.details}}

import re

from module.base.filter import Filter
from module.campaign.run import CampaignRun

STAGE_FILTER = Filter(regex=re.compile('^(.*?)$'), attr=('stage',))


class EventStage:
    """活动关卡文件的封装，从文件名提取关卡名称。"""

    def __init__(self, filename):
        self.filename = filename
        # 从文件名中去掉 .py 后缀作为关卡名
        self.stage = 'unknown'
        if filename[-3:] == '.py':
            self.stage = filename[:-3]

    def __str__(self):
        return self.stage

    def __eq__(self, other):
        return str(self) == str(other)


class EventBase(CampaignRun):
    """活动战役基类，继承自 CampaignRun。

    提供活动关卡加载、关卡名称转换和关卡过滤等基础功能。
    """

    def load_campaign(self, *args, **kwargs):
        """加载战役地图，并强制关闭一次性关卡标记。"""
        super().load_campaign(*args, **kwargs)
        self.campaign.config.temporary(
            MAP_IS_ONE_TIME_STAGE=False
        )

    def convert_stages(self, stages):
        """将各种格式的输入转换为正确的关卡名称。

        支持字符串、EventStage 列表和 Filter 对象三种输入格式，
        统一调用 handle_stage_name 进行名称规范化。

        Args:
            stages: 待转换的关卡输入，可以是 str、list[EventStage | str] 或 Filter。

        Returns:
            转换后的关卡数据，类型与输入一致。
        """

        def convert(n):
            return self.handle_stage_name(n, folder=self.config.Campaign_Event)[0]

        if isinstance(stages, str):
            return convert(stages)
        if isinstance(stages, list):
            out = []
            for name in stages:
                if isinstance(name, EventStage):
                    name.stage = convert(name.stage)
                    out.append(name)
                elif isinstance(name, str):
                    out.append(convert(name))
                else:
                    out.append(name)
            return out
        if isinstance(stages, Filter):
            stages.filter = [[convert(selection[0])] for selection in stages.filter]
            return stages
        return stages

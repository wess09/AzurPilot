from ..campaign_war_archives.campaign_base import CampaignBase as WarArchivesCampaignBase
from ..event_20230817_cn.campaign_base import CampaignBase as EventCampaignBase


class CampaignBase(EventCampaignBase, WarArchivesCampaignBase):
    """复用原活动的剧情解锁逻辑，并通过作战档案进入关卡。"""

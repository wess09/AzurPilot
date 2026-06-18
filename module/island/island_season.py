"""
岛屿计划 - 季节配置模块

管理全局季节设置，定义每个季节的限定物品及其对应的图标映射。
各个模块通过全局配置 `IslandPlan.Season` 来启用/禁用季节性物品。
"""

from module.logger import logger


# ==================== 季节常量 ====================

SEASONS = {
    'spring': '春季',
    'summer': '夏季',
    'autumn': '秋季',
    'winter': '冬季',
}

# ==================== 每季度的季节限定物品映射 ====================
# structure: { season: { module_key: [item_names] } }
# module_key 对应各个店铺模块的类型标识

SEASONAL_ITEMS = {
    'spring': {
        # 鱼餐馆：春季限定菜品
        'restaurant': ['double_bamboo_shoots', 'asparagus_shrimp'],
        # 白熊饮品：春季限定饮品
        'teahouse': ['spring_flower_tea', 'pineapple_juice'],
        # 青芽苗圃：春季限定作物（凤梨、芦笋）
        'nursery': ['asparagus', 'pineapple'],
        # 工厂手工：春季限定产品
        'handmade': ['shepherd_purse', 'spring_bouquet'],
    },
    'summer': {
        # 鱼餐馆：夏季限定菜品
        'restaurant': ['amaranth_rice_ball', 'tomato_egg'],
        # 白熊饮品：夏季限定饮品
        'teahouse': ['cucumber_juice', 'watermelon_juice'],
        # 青芽苗圃：夏季限定作物
        'nursery': ['tomato', 'cucumber'],
        # 工厂手工：夏季限定产品
        'handmade': ['jasmine_oil', 'summer_bouquet'],
    },
    'autumn': {
        'restaurant': [],
        'teahouse': [],
        'nursery': [],
        'handmade': [],
    },
    'winter': {
        'restaurant': [],
        'teahouse': [],
        'nursery': [],
        'handmade': [],
    },
}

# ==================== 季节图标映射 ====================
# 每个季节对应的图标模板名称（在 assets 中定义）
SEASON_ICONS = {
    'spring': 'TEMPLATE_SEASON_SPRING',
    'summer': 'TEMPLATE_SEASON_SUMMER',
    'autumn': 'TEMPLATE_SEASON_AUTUMN',
    'winter': 'TEMPLATE_SEASON_WINTER',
}

# ==================== 季节主题色 ====================
SEASON_COLORS = {
    'spring': (144, 238, 144),    # 浅绿色
    'summer': (255, 215, 0),      # 金色
    'autumn': (255, 140, 0),      # 橙色
    'winter': (135, 206, 250),    # 天蓝色
}


class SeasonConfig:
    """
    季节配置管理器
    通过全局配置读取当前季节，并提供查询接口
    """

    def __init__(self, config=None):
        """
        Args:
            config: 配置对象，需要包含 IslandPlan.Season 属性
        """
        self._config = config
        self._season = 'none'
        self._update_season()

    def _update_season(self):
        """从配置对象中读取当前季节"""
        if self._config is not None:
            raw = self._config.cross_get('IslandPlan.IslandPlan.Season')
            if raw and raw in SEASONS:
                self._season = raw
                return
        self._season = 'spring'

    @property
    def season(self):
        """当前季节标识"""
        return self._season

    @property
    def season_name(self):
        """当前季节的中文名称"""
        return SEASONS.get(self._season, '无季节限定')

    @property
    def is_seasonal_enabled(self):
        """是否启用了季节限定"""
        return self._season != 'none'

    def get_seasonal_items(self, module_key):
        """
        获取指定模块在当前季节的限定物品列表

        Args:
            module_key: 模块标识（restaurant, teahouse, nursery, handmade 等）

        Returns:
            list: 当前季节启用的物品名称列表
        """
        if not self.is_seasonal_enabled:
            return []
        season_data = SEASONAL_ITEMS.get(self._season, {})
        return season_data.get(module_key, [])

    def is_item_seasonal(self, item_name, module_key=None):
        """
        判断物品是否是当前季节的季节限定物品

        Args:
            item_name: 物品名称
            module_key: 模块标识（可选）

        Returns:
            bool
        """
        if not self.is_seasonal_enabled:
            return False
        if module_key:
            return item_name in self.get_seasonal_items(module_key)
        # 在所有模块中查找
        for module_items in SEASONAL_ITEMS.get(self._season, {}).values():
            if item_name in module_items:
                return True
        return False

    def get_season_icon_name(self):
        """获取当前季节的图标模板名称"""
        return SEASON_ICONS.get(self._season)

    def get_season_color(self):
        """获取当前季节的主题色"""
        return SEASON_COLORS.get(self._season)

    def refresh(self):
        """刷新季节配置（从最新配置重新读取）"""
        self._update_season()
        logger.info(f"季节配置已刷新，当前季节: {self.season_name}")

    def __str__(self):
        return f"SeasonConfig(season={self._season}, name={self.season_name})"


# ==================== 全局实例 ====================

_global_season_config = None


def get_global_season_config(config=None):
    """
    获取全局季节配置实例（单例）

    Args:
        config: 配置对象（首次调用时需要传入）

    Returns:
        SeasonConfig
    """
    global _global_season_config
    if _global_season_config is None and config is not None:
        _global_season_config = SeasonConfig(config)
    elif config is not None:
        _global_season_config._config = config
        _global_season_config.refresh()
    return _global_season_config

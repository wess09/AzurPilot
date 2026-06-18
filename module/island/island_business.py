import os
from module.island.island import Island
from module.island.assets import *
from module.island_business.assets import *
from module.ui.page import *
from module.island_select_character.assets import *
from module.logger import logger
from module.base.button import Button
from module.base.template import Template
from module.base.utils import crop, get_color, color_similar
from module.island.island_season import SEASONAL_ITEMS
from datetime import datetime, timedelta
from module.ocr.ocr import Duration


# ==================== 经营剩余时间 OCR 区域（深蓝按钮上方） ====================
BUSINESS_REMAIN_TIME_AREA = Button(
    area=(1061, 100, 1118, 120), color=(),
    button=(1061, 100, 1118, 120),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)


# ==================== 美食评审安全区域（仅坐标，无需截图） ====================
BUSINESS_REVIEW_SAFE_AREA = Button(
    area=(), color=(),
    button=(75, 450, 110, 550),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)

# ==================== 领取奖励安全区域（仅坐标，无需截图） ====================
BUSINESS_REWARD_SAFE_AREA = Button(
    area=(), color=(),
    button=(1100, 600, 1200, 700),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)

# ==================== 加成商品检测区域 ====================
# 商店详情页左侧，加成标记数量区域。1/2/3 个标记分别表示 30%/20%/10% 加成。
BUSINESS_BOOST_ICON_AREA = Button(
    area=(108, 333, 295, 352), color=(),
    button=(108, 333, 295, 352),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)

# 商店详情页左侧，加成餐品展示区域。这里可能显示 1-3 个餐品，使用 *_CROPPED 模板逐个匹配。
BUSINESS_BOOSTED_PRODUCT_AREA = Button(
    area=(50, 332, 300, 388), color=(),
    button=(50, 332, 300, 388),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)

# ==================== 商店索引到名称的映射 ====================
SHOP_INDEX_MAP = {
    1: '有鱼餐馆',
    2: '白熊饮品',
    3: '啾啾简餐',
    4: '乌鱼烤肉',
    5: '啾咖啡',
}

# ==================== 季节限定餐品配置（有鱼餐馆专用） ====================
SEASONAL_FOOD_MAP = {
    'spring': {
        'product_name': 'double_bamboo_shoots',
        'display': '双笋',
    },
    'summer': {
        'product_name': 'amaranth_rice_ball',
        'display': '苋菜饭团',
    },
}


class IslandBusiness(Island):
    BUSINESS_REVIEW_OFFSET_X = 150

    def __init__(self, config, device=None, task=None):
        super().__init__(config, device=device, task=task)

        # 商店定义及配置键前缀
        self.shops = [
            {'name': '有鱼餐馆', 'button': BUSINESS_SHOP_FISH_RESTAURANT, 'config_key': '1'},
            {'name': '白熊饮品', 'button': BUSINESS_SHOP_TEAHOUSE, 'config_key': '2'},
            {'name': '啾啾简餐', 'button': BUSINESS_SHOP_JUU_EATERY, 'config_key': '3'},
            {'name': '乌鱼烤肉', 'button': BUSINESS_SHOP_GRILL, 'config_key': '4'},
            {'name': '啾咖啡', 'button': BUSINESS_SHOP_JUU_COFFEE, 'config_key': '5'},
        ]

        self.shop_products = {
            '有鱼餐馆': [
                {'name': 'double_bamboo_shoots', 'button': TEMPLATE_BUSINESS_PRODUCT_RESTAURANT_DOUBLE_BAMBOO_SHOOTS},
                {'name': 'tofu_meat', 'button': TEMPLATE_BUSINESS_PRODUCT_RESTAURANT_TOFU_MEAT},
                {'name': 'tofu_combo', 'button': TEMPLATE_BUSINESS_PRODUCT_RESTAURANT_TOFU_COMBO},
                {'name': 'hearty_meal', 'button': TEMPLATE_BUSINESS_PRODUCT_RESTAURANT_HEARTY_MEAL},
                {'name': 'fo_tiao', 'button': TEMPLATE_BUSINESS_PRODUCT_RESTAURANT_FO_TIAO},
                {'name': 'amaranth_rice_ball', 'button': TEMPLATE_BUSINESS_PRODUCT_RESTAURANT_AMARANTH_RICE_BALL},
            ],
            '白熊饮品': [
                {'name': 'spring_flower_tea', 'button': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_SPRING_FLOWER_TEA},
                {'name': 'strawberry_lemon', 'button': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_STRAWBERRY_LEMON},
                {'name': 'strawberry_honey', 'button': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_STRAWBERRY_HONEY},
                {'name': 'floral_fruity', 'button': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_FLORAL_FRUITY},
                {'name': 'fruit_paradise', 'button': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_FRUIT_PARADISE},
                {'name': 'lavender_tea', 'button': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_LAVENDER_TEA},
                {'name': 'sunny_honey', 'button': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_SUNNY_HONEY},
                {'name': 'watermelon_juice', 'button': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_WATERMELON_JUICE},
            ],
            '乌鱼烤肉': [
                {'name': 'roasted_skewer', 'button': TEMPLATE_BUSINESS_PRODUCT_GRILL_ROASTED_SKEWER},
                {'name': 'stir_fried_chicken', 'button': TEMPLATE_BUSINESS_PRODUCT_GRILL_STIR_FRIED_CHICKEN},
                {'name': 'steak_bowl', 'button': TEMPLATE_BUSINESS_PRODUCT_GRILL_STEAK_BOWL},
                {'name': 'carnival', 'button': TEMPLATE_BUSINESS_PRODUCT_GRILL_CARNIVAL},
                {'name': 'double_energy', 'button': TEMPLATE_BUSINESS_PRODUCT_GRILL_DOUBLE_ENERGY},
            ],
            '啾啾简餐': [
                {'name': 'orchard_duo', 'button': TEMPLATE_BUSINESS_PRODUCT_EATERY_ORCHARD_DUO},
                {'name': 'succulently_sweet', 'button': TEMPLATE_BUSINESS_PRODUCT_EATERY_SUCCULENTLY_SWEET},
                {'name': 'berry_orange', 'button': TEMPLATE_BUSINESS_PRODUCT_EATERY_BERRY_ORANGE},
                {'name': 'strawberry_charlotte', 'button': TEMPLATE_BUSINESS_PRODUCT_EATERY_STRAWBERRY_CHARLOTTE},
                {'name': 'seafood_rice', 'button': TEMPLATE_BUSINESS_PRODUCT_EATERY_SEAFOOD_RICE},
            ],
            '啾咖啡': [
                {'name': 'strawberry_milkshake', 'button': TEMPLATE_BUSINESS_PRODUCT_COFFEE_STRAWBERRY_MILKSHAKE},
                {'name': 'morning_light', 'button': TEMPLATE_BUSINESS_PRODUCT_COFFEE_MORNING_LIGHT},
                {'name': 'wake_up_call', 'button': TEMPLATE_BUSINESS_PRODUCT_COFFEE_WAKE_UP_CALL},
                {'name': 'fruity_fruitier', 'button': TEMPLATE_BUSINESS_PRODUCT_COFFEE_FRUITY_FRUITIER},
                {'name': 'cheese', 'button': TEMPLATE_BUSINESS_PRODUCT_COFFEE_CHEESE},
            ],
        }

        self.boost_product_templates = {
            '有鱼餐馆': [
                {'name': 'double_bamboo_shoots', 'template': TEMPLATE_BUSINESS_PRODUCT_RESTAURANT_DOUBLE_BAMBOO_SHOOTS_CROPPED},
                {'name': 'tofu_meat', 'template': TEMPLATE_BUSINESS_PRODUCT_RESTAURANT_TOFU_MEAT_CROPPED},
                {'name': 'tofu_combo', 'template': TEMPLATE_BUSINESS_PRODUCT_RESTAURANT_TOFU_COMBO_CROPPED},
                {'name': 'hearty_meal', 'template': TEMPLATE_BUSINESS_PRODUCT_RESTAURANT_HEARTY_MEAL_CROPPED},
                {'name': 'fo_tiao', 'template': TEMPLATE_BUSINESS_PRODUCT_RESTAURANT_FO_TIAO_CROPPED},
                {'name': 'amaranth_rice_ball', 'template': TEMPLATE_BUSINESS_PRODUCT_RESTAURANT_AMARANTH_RICE_BALL_CROPPED},
            ],
            '白熊饮品': [
                {'name': 'spring_flower_tea', 'template': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_SPRING_FLOWER_TEA_CROPPED},
                {'name': 'strawberry_lemon', 'template': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_STRAWBERRY_LEMON_CROPPED},
                {'name': 'strawberry_honey', 'template': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_STRAWBERRY_HONEY_CROPPED},
                {'name': 'floral_fruity', 'template': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_FLORAL_FRUITY_CROPPED},
                {'name': 'fruit_paradise', 'template': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_FRUIT_PARADISE_CROPPED},
                {'name': 'lavender_tea', 'template': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_LAVENDER_TEA_CROPPED},
                {'name': 'sunny_honey', 'template': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_SUNNY_HONEY_CROPPED},
                {'name': 'watermelon_juice', 'template': TEMPLATE_BUSINESS_PRODUCT_TEAHOUSE_WATERMELON_JUICE_CROPPED},
            ],
            '乌鱼烤肉': [
                {'name': 'roasted_skewer', 'template': TEMPLATE_BUSINESS_PRODUCT_GRILL_ROASTED_SKEWER_CROPPED},
                {'name': 'stir_fried_chicken', 'template': TEMPLATE_BUSINESS_PRODUCT_GRILL_STIR_FRIED_CHICKEN_CROPPED},
                {'name': 'steak_bowl', 'template': TEMPLATE_BUSINESS_PRODUCT_GRILL_STEAK_BOWL_CROPPED},
                {'name': 'carnival', 'template': TEMPLATE_BUSINESS_PRODUCT_GRILL_CARNIVAL_CROPPED},
                {'name': 'double_energy', 'template': TEMPLATE_BUSINESS_PRODUCT_GRILL_DOUBLE_ENERGY_CROPPED},
            ],
            '啾啾简餐': [
                {'name': 'orchard_duo', 'template': TEMPLATE_BUSINESS_PRODUCT_EATERY_ORCHARD_DUO_CROPPED},
                {'name': 'succulently_sweet', 'template': TEMPLATE_BUSINESS_PRODUCT_EATERY_SUCCULENTLY_SWEET_CROPPED},
                {'name': 'berry_orange', 'template': TEMPLATE_BUSINESS_PRODUCT_EATERY_BERRY_ORANGE_CROPPED},
                {'name': 'strawberry_charlotte', 'template': TEMPLATE_BUSINESS_PRODUCT_EATERY_STRAWBERRY_CHARLOTTE_CROPPED},
                {'name': 'seafood_rice', 'template': TEMPLATE_BUSINESS_PRODUCT_EATERY_SEAFOOD_RICE_CROPPED},
            ],
            '啾咖啡': [
                {'name': 'strawberry_milkshake', 'template': TEMPLATE_BUSINESS_PRODUCT_COFFEE_STRAWBERRY_MILKSHAKE_CROPPED},
                {'name': 'morning_light', 'template': TEMPLATE_BUSINESS_PRODUCT_COFFEE_MORNING_LIGHT_CROPPED},
                {'name': 'wake_up_call', 'template': TEMPLATE_BUSINESS_PRODUCT_COFFEE_WAKE_UP_CALL_CROPPED},
                {'name': 'fruity_fruitier', 'template': TEMPLATE_BUSINESS_PRODUCT_COFFEE_FRUITY_FRUITIER_CROPPED},
                {'name': 'cheese', 'template': TEMPLATE_BUSINESS_PRODUCT_COFFEE_CHEESE_CROPPED},
            ],
        }

        self._init_season_config()
        self.season = self.season_config.season
        logger.info(f"当前季节: {self.season_config.season_name}")

        # 读取每个商店配置的角色和餐品
        self._load_shop_configs()

        # ========== 分批配置 ==========
        self.batch_enabled = getattr(self.config, 'IslandBusiness_BatchEnabled', True)
        self.batch1_shops_indices = getattr(self.config, 'IslandBusiness_Batch1Shops', [3, 1, 5])
        self.batch2_shops_indices = getattr(self.config, 'IslandBusiness_Batch2Shops', [2, 4])

        # 去重：如果某商店同时出现在两批中，从第二批移除
        self.batch2_shops_indices = [i for i in self.batch2_shops_indices
                                     if i not in self.batch1_shops_indices]

        # ========== 季节替换配置 ==========
        self.seasonal_replace_enabled = getattr(self.config, 'IslandBusiness_SeasonalReplaceEnabled', True)
        self.seasonal_threshold = getattr(self.config, 'IslandBusiness_SeasonalThreshold', 7)

        # ========== 加成绩替换配置 ==========
        self.boost_filters = {}
        self._load_boost_filters()

        logger.info(f"分批经营: {'启用' if self.batch_enabled else '禁用'}, "
                     f"第一批: {self.batch1_shops_indices}, 第二批: {self.batch2_shops_indices}")
        logger.info("经营模块初始化完成")

    # ===================================================================
    # 分批经营：工具方法
    # ===================================================================

    def _indices_to_shop_names(self, indices):
        """将商店索引列表转换为商店名称列表"""
        return [SHOP_INDEX_MAP[i] for i in indices if i in SHOP_INDEX_MAP]

    def _get_batch1_shops(self):
        """获取第一批商店配置列表（按 config_key 过滤）"""
        names = self._indices_to_shop_names(self.batch1_shops_indices)
        return [s for s in self.shops if s['name'] in names]

    def _get_batch2_shops(self):
        """获取第二批商店配置列表（按 config_key 过滤）"""
        names = self._indices_to_shop_names(self.batch2_shops_indices)
        return [s for s in self.shops if s['name'] in names]

    def _is_shop_in_batch(self, shop_name, batch_shops):
        """检查指定商店是否属于当前批次"""
        return any(s['name'] == shop_name for s in batch_shops)

    # ===================================================================
    # 季节限定餐品检测替换
    # ===================================================================

    def _check_seasonal_dish_quantity_and_replace(self):
        """
        检查有鱼餐馆的季节限定餐品库存，如果 < 阈值则替换为备用餐品。

        只处理有鱼餐馆。仅在 Product1~5 中选择了当前季节餐品时检查仓库库存。

        Returns:
            bool: True 表示进行了替换
        """
        if not self.seasonal_replace_enabled:
            return False

        seasonal_info = SEASONAL_FOOD_MAP.get(self.season)
        if not seasonal_info:
            return False

        seasonal_product_name = seasonal_info['product_name']
        shop_name = '有鱼餐馆'

        # 检查有鱼餐馆的配置中是否包含了当前季节餐品
        selected_products = self.active_products.get(shop_name, [])
        selected_names = [p['name'] for p in selected_products]
        if seasonal_product_name not in selected_names:
            logger.info(f"有鱼餐馆未配置季节餐品 {seasonal_info['display']}，跳过季节检查")
            return False

        logger.info(f"检测有鱼餐馆季节餐品 '{seasonal_info['display']}' 库存")
        # 前往仓库检查库存
        self.goto_warehouse_within_postmanage()
        self.device.screenshot()

        # 使用 WarehouseOCR 检查季节餐品库存
        from module.island.warehouse import WarehouseOCR
        warehouse = WarehouseOCR()
        count = warehouse.ocr_item_quantity(self.device.image, self._get_seasonal_warehouse_template(seasonal_product_name))

        logger.info(f"季节餐品 '{seasonal_info['display']}' 当前库存: {count}")
        if count >= self.seasonal_threshold:
            logger.info(f"季节餐品库存充足 ({count} >= {self.seasonal_threshold})，无需替换")
            return False

        # 库存不足，获取备用餐品
        fallback_name = getattr(self.config, 'IslandBusinessShop1_SeasonalFallback', 'hearty_meal')
        fallback_product = self._find_product_by_name(shop_name, fallback_name)
        if not fallback_product:
            logger.warning(f"备用餐品 '{fallback_name}' 未找到，无法替换")
            return False

        logger.info(f"季节餐品 '{seasonal_info['display']}' 库存不足 ({count} < {self.seasonal_threshold})，"
                     f"替换为 '{fallback_name}'")

        # 在 active_products 中替换
        new_products = []
        replaced = False
        for p in selected_products:
            if p['name'] == seasonal_product_name and not replaced:
                new_products.append(fallback_product)
                replaced = True
            else:
                new_products.append(p)

        if replaced:
            self.active_products[shop_name] = new_products
            logger.info(f"有鱼餐馆餐品已替换: {seasonal_product_name} → {fallback_name}")
            return True

        return False

    def _get_seasonal_warehouse_template(self, product_name):
        """
        获取季节餐品在仓库中的识别模板。
        直接复用已有餐品模板（在有鱼餐馆/餐厅模块中已定义）。
        """
        # 仓库专用模板映射，直接使用已有模板文件路径
        # 使用 Template 直接引用文件，避免循环导入
        warehouse_files = {
            'double_bamboo_shoots': Template(file={
                'cn': './assets/cn/island_restaurant/TEMPLATE_DOUBLE_BAMBOO_SHOOTS.png',
                'en': './assets/cn/island_restaurant/TEMPLATE_DOUBLE_BAMBOO_SHOOTS.png',
                'jp': './assets/cn/island_restaurant/TEMPLATE_DOUBLE_BAMBOO_SHOOTS.png',
                'tw': './assets/cn/island_restaurant/TEMPLATE_DOUBLE_BAMBOO_SHOOTS.png',
            }),
            'amaranth_rice_ball': Template(file={
                'cn': './assets/cn/island_restaurant/TEMPLATE_AMARANTH_RICE_BALL.png',
                'en': './assets/cn/island_restaurant/TEMPLATE_AMARANTH_RICE_BALL.png',
                'jp': './assets/cn/island_restaurant/TEMPLATE_AMARANTH_RICE_BALL.png',
                'tw': './assets/cn/island_restaurant/TEMPLATE_AMARANTH_RICE_BALL.png',
            }),
        }
        return warehouse_files.get(product_name)

    def _find_product_by_name(self, shop_name, product_name):
        """在指定商店的餐品列表中按名称查找产品"""
        for p in self.shop_products.get(shop_name, []):
            if p['name'] == product_name:
                return p
        return None

    def goto_warehouse_within_postmanage(self):
        """
        从经营页签导航到仓库页面，并筛选有鱼餐馆的餐品。
        使用已有的 warehouse_filter 能力进入仓库并设置分类筛选。
        """
        self.ui_goto(page_island_postmanage, get_ship=False)
        self.device.sleep(1)
        self.device.screenshot()

        # 使用 warehouse_filter 进入仓库并筛选有鱼餐馆产品
        # product = 餐品分类, restaurant = 有鱼餐馆来源
        self.warehouse_filter('product', 'restaurant')
        self.device.sleep(1)

    def goto_warehouse(self):
        """
        从当前页面导航到仓库页面。
        复用 Island 的 warehouse_filter 前置逻辑。
        """
        self.ui_goto(page_island_warehouse_filter, get_ship=False)
        self.device.sleep(1)

    # ===================================================================
    # 加成商品检测替换
    # ===================================================================

    def _load_boost_filters(self):
        """
        加载每个商店的加成绩替换过滤配置。

        过滤串格式（级联规则）: 30 > 20 > 餐品A > 餐品B > 10

        含义：数字（30/20/10）代表加成档位从高到低排列，
        所有餐品最终归入最后/最低的数字档位。
        """
        self.boost_filters = {}
        for shop in self.shops:
            ck = shop['config_key']
            raw = getattr(self.config, f'IslandBusinessShop{ck}_BoostReplaceFilter', '')
            if raw:
                parsed = self._parse_boost_filter(raw)
                if parsed:
                    self.boost_filters[shop['name']] = parsed
                    logger.info(f"{shop['name']}: 加成替换配置已加载: {parsed}")

    def _parse_boost_filter(self, filter_str):
        """
        解析加成绩替换过滤串。

        支持两种模式，根据字符串首元素自动判断：

        **级联模式**（首元素是数字 30/20/10）：
        数字代表加成档位从高到低排列。餐品归入当前数字的**下一档位**：
        30→20, 20→10, 10→10。遇到更低数字时，较高档位的餐品
        **快照复制**到该档位（向下级联）。
        例如：
        "30 > fruit_paradise"                            → {20: ['fruit_paradise']}
        "30 > strawberry_honey > 20 > fruit_paradise > 10" → {20: ['strawberry_honey'], 10: ['strawberry_honey', 'fruit_paradise']}

        **标准模式**（首元素是餐品名）：
        餐品在数字前，归属于该数字档位。支持正向和反向格式。
        例如： "fo_tiao > hearty_meal > 30 > tofu_combo > tofu_meat > 20 > double_bamboo_shoots > 10"
        返回： {30: ['fo_tiao', 'hearty_meal'], 20: ['tofu_combo', 'tofu_meat'], 10: ['double_bamboo_shoots']}

        Args:
            filter_str: 过滤串

        Returns:
            dict: 加成档位到餐品列表的映射
        """
        parts = [p.strip() for p in filter_str.replace('\n', ' ').split('>') if p.strip()]

        if not parts:
            return {}

        # 首元素是数字 → 级联模式；首元素是餐品 → 标准模式
        is_cascade = parts[0] in ('30', '20', '10')

        if is_cascade:
            # ========== 级联模式 ==========
            # 餐品归入当前数字的下一档位（30→20, 20→10, 10→10）
            # 遇到更低数字时，较高档位的餐品快照复制到该档位

            def _next_lower(tier):
                if tier == 30:
                    return 20
                elif tier == 20:
                    return 10
                return 10

            result = {}
            current_tier = None

            for part in parts:
                if part in ('30', '20', '10'):
                    boost = int(part)
                    # 遇到更低数字：较高档位的餐品快照复制到当前档位
                    if current_tier is not None and boost < current_tier:
                        for tier in sorted(result.keys(), reverse=True):
                            if tier > boost:
                                result.setdefault(boost, []).extend(result[tier])
                    current_tier = boost
                else:
                    # 餐品归入当前档位的下一档
                    target_tier = _next_lower(current_tier)
                    result.setdefault(target_tier, []).append(part)

            # 清除空档位
            return {k: v for k, v in result.items() if v}
        else:
            # ========== 标准模式 ==========
            # 餐品在数字前，归属于该数字档位，分配后清空
            result = {}
            current_items = []
            pending_boost = None  # 跟踪 "数字 > 餐品" 反向格式

            for part in parts:
                if part in ('30', '20', '10'):
                    boost = int(part)
                    if current_items:
                        # 标准格式：餐品 > 数字（如 "fo_tiao > hearty_meal > 30"）
                        result[boost] = current_items
                        current_items = []
                    else:
                        # 反向格式：数字 > 餐品（如 "20 > double_bamboo_shoots"）
                        pending_boost = boost
                else:
                    if pending_boost is not None:
                        # 数字先出现，此餐品归属于前面的数字档位
                        result.setdefault(pending_boost, []).append(part)
                        pending_boost = None
                    else:
                        current_items.append(part)

            # 兜底处理：残留餐品默认归到最低档 10%
            if current_items:
                result.setdefault(10, []).extend(current_items)

            return result

    def _detect_boosted_products(self, shop_name, skip_names=None):
        """
        检测当前商店中哪些餐品有加成标签。

        进入商店后（选择角色之前），先检测左侧加成标记数量确定加成档位，
        再在左侧加成餐品展示区域用 CROPPED 模板逐个匹配具体加成餐品，
        该区域可能同时显示 1-3 个餐品。

        加成标签特征：
        - 1 个图标：30% 加成
        - 2 个图标：20% 加成
        - 3 个图标：10% 加成

        Args:
            shop_name: 商店名称
            skip_names: 可选，需要跳过检测的餐品名集合（已在槽位中则跳过检测）

        Returns:
            list: [('product_name', boost_percent), ...] 按玩家配置顺序排列
        """
        self.device.screenshot()
        boost_percent = self._detect_boost_percent()
        if not boost_percent:
            return []

        boost_filter = self.boost_filters.get(shop_name, {})
        candidates = boost_filter.get(boost_percent, [])
        if not candidates:
            logger.info(f"{shop_name}: 当前 {boost_percent}% 档位没有配置加成替换餐品，跳过匹配")
            return []

        # 过滤掉已在当前配置槽位中的餐品，避免重复检测
        if skip_names:
            filtered = [c for c in candidates if c not in skip_names]
            skipped = [c for c in candidates if c in skip_names]
            if skipped:
                logger.info(f"{shop_name}: 以下餐品已在配置中，跳过检测: {skipped}")
            candidates = filtered
            if not candidates:
                logger.info(f"{shop_name}: 当前 {boost_percent}% 档位的所有候选餐品已在配置中，跳过匹配")
                return []

        boosted = []
        area_img = crop(self.device.image, BUSINESS_BOOSTED_PRODUCT_AREA.area)
        products = {p['name']: p for p in self.boost_product_templates.get(shop_name, [])}
        for product_name in candidates:
            p = products.get(product_name)
            if p is None:
                logger.warning(f"{shop_name}: 加成替换配置中的餐品 {product_name} 没有对应识别模板")
                continue
            template = p.get('template')
            if template is None:
                continue
            sim, _ = template.match_result(area_img)
            if sim >= 0.7:
                logger.info(f"{shop_name}: 检测到配置内加成餐品 {product_name} ({boost_percent}%, sim={sim:.2f})")
                boosted.append((product_name, boost_percent))

        return boosted

    def _detect_boost_percent(self):
        """
        通过加成图标数量判断加成档位。

        Returns:
            int: 30/20/10，无加成为 0
        """
        area_img = crop(self.device.image, BUSINESS_BOOST_ICON_AREA.area)
        matches = TEMPLATE_BUSINESS_BOOST_ICON.match_multi(
            area_img,
            similarity=0.8,
            threshold=5,
            name='TEMPLATE_BUSINESS_BOOST_ICON'
        )
        count = len(matches)
        logger.info(f"检测到加成图标数量: {count}")
        if count == 1:
            return 30
        if count == 2:
            return 20
        if count == 3:
            return 10
        return 0

    def _select_boost_replacement(self, shop_name, boosted_products):
        """
        根据过滤配置和当天实际加成绩，选择合适的替换餐品。

        规则：
        1. 从配置中获取对应档位的候选餐品列表
        2. 选择的餐品必须属于当前加成档位，且当天确实有加成

        Args:
            shop_name: 商店名称
            boosted_products: [('product_name', boost_percent), ...]

        Returns:
            str: 要替换成的餐品名称，或 None
        """
        boost_filter = self.boost_filters.get(shop_name, {})
        if not boost_filter:
            return None

        # 取最高加成百分比
        if not boosted_products:
            return None

        max_boost = boosted_products[0][1]

        # 获取该档位的候选餐品
        candidates = boost_filter.get(max_boost, [])

        # 从候选列表中找第一个当天确实有加成的餐品
        boosted_names = {name for name, _ in boosted_products}
        for candidate in candidates:
            if candidate in boosted_names:
                logger.info(f"选择加成替换餐品: {candidate} (档位: {max_boost}%)")
                return candidate

        logger.warning(f"{shop_name}: 未找到合适的加成替换餐品")
        return None

    def _find_first_filled_product_slot_bottom_up(self, shop_name):
        """
        从 Product5 → Product4 → ... → Product1 查找第一个有值的餐品槽位。

        Args:
            shop_name: 商店名称

        Returns:
            int: 槽位编号（1-5），或 None
        """
        products = self.active_products.get(shop_name, [])
        if not products:
            return None

        # 从 Product5 → Product1 查找
        for i in range(len(products) - 1, -1, -1):
            product = products[i]
            if not product:
                continue
            if isinstance(product, dict):
                name = product.get('name')
                if name and name != 'None':
                    return i
                continue
            return i

        return None

    def _replace_product_slot(self, shop_name, slot_index, replacement_name):
        """
        替换指定商店指定槽位的餐品。

        Args:
            shop_name: 商店名称
            slot_index: 槽位索引
            replacement_name: 替换成的餐品名称
        """
        replacement = self._find_product_by_name(shop_name, replacement_name)
        if not replacement:
            logger.warning(f"替换餐品 '{replacement_name}' 未找到，无法替换")
            return False

        products = self.active_products.get(shop_name, [])
        if not products or slot_index is None or slot_index < 0 or slot_index >= len(products):
            slot_display = slot_index + 1 if isinstance(slot_index, int) else slot_index
            logger.warning(f"槽位 {slot_display} 无效")
            return False

        old_name = products[slot_index]['name']
        products[slot_index] = replacement
        self.active_products[shop_name] = products
        logger.info(f"加成餐品替换: {old_name} → {replacement_name} (槽位 {slot_index + 1})")
        return True

    def _check_and_replace_boosted_product(self, shop_name):
        """
        进入商店后（选择角色前），检测当天加成餐品并执行替换。

        跳过条件：
        1. 加成过滤中所有候选餐品已在当前配置中，跳过检测和替换
        2. 选中的替换餐品已在当前配置中，跳过替换

        替换槽位从 Product5 → Product1 倒查，取最后一个有值的槽位。

        Args:
            shop_name: 商店名称

        Returns:
            bool: True 表示进行了替换
        """
        # 获取商店配置key
        ck = None
        for shop in self.shops:
            if shop['name'] == shop_name:
                ck = shop['config_key']
                break
        if ck is None:
            return False

        # 获取当前已选的餐品名称列表
        products = self.active_products.get(shop_name, [])
        active_names = {p['name'] for p in products}

        # 检查加成过滤配置中的所有候选餐品是否都已存在
        boost_filter = self.boost_filters.get(shop_name, {})
        all_candidates = set()
        for candidates in boost_filter.values():
            all_candidates.update(candidates)

        if all_candidates and all_candidates.issubset(active_names):
            logger.info(f"{shop_name}: 加成过滤中所有候选餐品均已存在，跳过检测和替换")
            return False

        # 检测当天加成（跳过已在配置中的餐品）
        boosted = self._detect_boosted_products(shop_name, skip_names=active_names)
        if not boosted:
            logger.info(f"{shop_name}: 未检测到加成餐品")
            return False

        logger.info(f"{shop_name}: 检测到加成 {boosted}")

        # 选择替换餐品
        replacement = self._select_boost_replacement(shop_name, boosted)
        if not replacement:
            logger.info(f"{shop_name}: 未找到合适的替换餐品")
            return False

        # 检查替换餐品是否已存在于当前配置中
        if replacement in active_names:
            logger.info(f"{shop_name}: 替换餐品 {replacement} 已在当前配置中，跳过替换")
            return False

        # 从 Product5 → Product1 倒查最后一个有值的配置槽位
        target_slot = self._find_first_filled_product_slot_bottom_up(shop_name)
        if target_slot is None:
            logger.info(f"{shop_name}: 没有可替换的餐品槽位")
            return False

        # 执行替换
        return self._replace_product_slot(shop_name, target_slot, replacement)

    # ===================================================================
    # 季节配置初始化（保留原逻辑）
    # ===================================================================

    def _init_season_config(self):
        """初始化季节配置（同 IslandShopBase）"""
        from module.island.island_season import get_global_season_config
        self.season_config = get_global_season_config(self.config)
        self.current_season = self.season_config.season
        self.season_name = self.season_config.season_name

    # 商店名到 season_config 模块key的映射
    SHOP_SEASON_MAP = {
        '有鱼餐馆': 'restaurant',
        '白熊饮品': 'teahouse',
        '啾啾简餐': 'juu_eatery',
        '乌鱼烤肉': 'grill',
        '啾咖啡': 'juu_coffee',
    }

    def _get_seasonal_items_for_shop(self, shop_name):
        """获取指定商店当前季节的限定物品列表"""
        module_key = self.SHOP_SEASON_MAP.get(shop_name)
        if module_key and hasattr(self, 'season_config') and self.season_config:
            return self.season_config.get_seasonal_items(module_key)
        return []

    def _load_shop_configs(self):
        """从配置中读取每个商店选择的餐品（已按季节过滤）"""
        self.active_products = {}

        for shop in self.shops:
            shop_name = shop['name']
            ck = shop['config_key']
            module_key = self.SHOP_SEASON_MAP.get(shop_name, '')

            # 读取餐品配置（最多5个）
            products = []
            for i in range(1, 6):
                val = getattr(self.config, f'IslandBusinessShop{ck}_Product{i}', 'None')
                if val and val != 'None' and val in self._all_product_names(shop_name):
                    # 季节过滤：检查该物品是否为其他季节的限定品
                    other_season_item = False
                    for season_key, season_data in SEASONAL_ITEMS.items():
                        if season_key != self.season_config.season:
                            if module_key and val in season_data.get(module_key, []):
                                other_season_item = True
                                break
                    if other_season_item:
                        logger.info(f"{shop_name}: 跳过 {val}（非当前季节限定）")
                        continue

                    for p in self.shop_products.get(shop_name, []):
                        if p['name'] == val:
                            products.append(p)
                            break
            if products:
                self.active_products[shop_name] = products
                logger.info(f"{shop_name}: 配置 {len(products)} 餐品")

    def _load_shop_characters(self, shop):
        """为指定商店加载角色优先级列表"""
        ck = shop['config_key']
        chars = []
        for i in range(1, 3):
            val = getattr(self.config, f'IslandBusinessShop{ck}_Char{i}', 'None')
            if val and val != 'None':
                chars.append(val)
        self.character_priority = chars if chars else ['WorkerJuu']
        logger.info(f"{shop['name']}: 角色优先级 {self.character_priority}")

    def _all_product_names(self, shop_name):
        """获取商店所有可能的餐品名（含季节限定，全部显示）"""
        names = [p['name'] for p in self.shop_products.get(shop_name, [])]
        return names

    def _get_review_button(self, button):
        """创建偏移150px的按钮用于检测（游戏截图向左偏移150px = 按钮向右偏移150px）"""
        if not button or not button.area:
            return None
        # 偏移 area（检测区域）向右150px，button（点击坐标）同步偏移
        ax1, ay1, ax2, ay2 = button.area
        new_area = (ax1 + self.BUSINESS_REVIEW_OFFSET_X, ay1,
                    ax2 + self.BUSINESS_REVIEW_OFFSET_X, ay2)
        if button.button:
            bx1, by1, bx2, by2 = button.button
            new_button = (bx1 + self.BUSINESS_REVIEW_OFFSET_X, by1,
                          bx2 + self.BUSINESS_REVIEW_OFFSET_X, by2)
        else:
            new_button = new_area
        return Button(area=new_area, color=button.color,
                      button=new_button, file=button.file)

    def _appear_at_positions(self, button, offset=30):
        """
        在正常位置和偏移位置（美食评审模式）检测按钮。

        保留模板匹配能力（offset=30）以应对界面背景变化或微小位置偏差。
        在检测前后调用 button.clear_offset() 清理 match() 设置的 _button_offset，
        避免污染全局按钮常量导致后续点击坐标偏移。

        review_btn 虽然是新建的局部 Button 实例，但 appear() 内部调用 match()
        会就地修改 review_btn._button_offset，因此返回前必须清理。

        Args:
            button: 待检测的按钮。
            offset: 模板匹配搜索范围，默认 30。

        Returns:
            Button: 检测到的按钮实例，或 None。
        """
        self.device.screenshot()
        # 清理残留偏移，确保以干净状态进入检测
        button.clear_offset()
        if self.appear(button, offset=offset):
            # match() 已修改 _button_offset，清理后返回确保点击坐标正确
            button.clear_offset()
            return button
        # 清理 match() 可能设置的偏移，确保 _get_review_button 读到原始坐标
        button.clear_offset()
        review_btn = self._get_review_button(button)
        if review_btn and self.appear(review_btn, offset=offset):
            # match() 修改了 review_btn._button_offset，必须清理后再返回
            review_btn.clear_offset()
            return review_btn
        return None

    def _appear_business_settlement(self):
        """检测经营结算按钮，并用按钮颜色过滤灰色休息中按钮条的误匹配。"""
        settlement = self._appear_at_positions(BUSINESS_SETTLEMENT)
        if not settlement:
            return None

        area_color = get_color(self.device.image, settlement.area)
        if color_similar(area_color, BUSINESS_SETTLEMENT.color, threshold=50):
            return settlement

        logger.info(f"经营结算按钮颜色不匹配，跳过: {area_color}")
        return None

    def _parse_character_config(self, config_str):
        if isinstance(config_str, str):
            return [char.strip() for char in config_str.split('>')]
        return ['WorkerJuu']

    def _switch_to_business_tab(self):
        """
        切换到经营页签，并处理切换后可能出现的美食评审弹窗遮挡问题。

        点击经营页签按钮后，游戏可能弹出美食评审界面遮挡所有页签按钮，
        导致 post_manage_mode() 陷入死循环。此方法在每次点击后检测弹窗
        并及时关闭，确保成功切换到经营页签。
        """
        for attempt in range(10):
            self.device.screenshot()

            # 已成功切换到经营页签
            if self.appear(POST_MANAGE_BUSINESS, offset=30):
                logger.info("已在经营页签")
                return

            # 检查是否有弹窗遮挡（生产和经营页签的蓝色指示器都不可见）
            if not self.appear(POST_MANAGE_PRODUCTION, offset=30) \
                    and not self.appear(POST_MANAGE_BUSINESS, offset=30):
                # 不使用 appear 判断但使用固定坐标检测弹窗位置
                logger.info("页签按钮被弹窗遮挡，点击安全区域关闭")
                self.device.click(BUSINESS_REVIEW_SAFE_AREA)
                self.device.sleep(1)
                continue

            # 在采集页签
            if self.appear(ISLAND_GATHER_COLLECT_CHECK, offset=30):
                self.device.click(POST_MANAGE_PRODUCTION)
                self.device.sleep(0.5)
                continue

            # 在其他页签（如生产），点击经营页签按钮切换
            self.device.click(POST_MANAGE_PRODUCTION)
            self.device.sleep(0.5)

        logger.warning("切换到经营页签失败（超过最大尝试次数）")

    # ===================================================================
    # 主入口 run() - 支持分批和传统模式
    # ===================================================================

    def run(self):
        logger.info("=== 开始经营模块 ===")
        self.goto_postmanage()
        self.device.sleep(1)

        # 处理每日首次进入可能出现的美食评审界面
        self._handle_food_review()

        logger.info("切换到经营页签")
        self._switch_to_business_tab()
        self.device.sleep(1)

        # 切换页签后再次处理可能出现的弹窗
        self._handle_food_review()

        if self.batch_enabled:
            self._run_batch_mode()
        else:
            self._run_legacy_mode()

        logger.info("=== 经营模块完成 ===")

    # ===================================================================
    # 传统模式（不分批，原逻辑）
    # ===================================================================

    def _run_legacy_mode(self):
        """传统不分批模式（保持原有行为）"""
        # 标记本轮是否曾处理过蓝色开始经营按钮
        self._has_seen_blue = False

        while True:
            logger.info("--- 处理商店 ---")
            status = self._check_start_button_status()

            if status == 'blue':
                self._has_seen_blue = True
                logger.info("检测到蓝色按钮，点击进入商店")
                self.device.click(BUSINESS_START_BUTTON_BLUE)
                self.device.sleep(1)

                current_shop = self._detect_current_shop()
                if current_shop:
                    shop_name = current_shop['name']
                    logger.info(f"当前商店: {shop_name}")
                    self._load_shop_characters(current_shop)
                    self._select_business_characters()
                    self._select_business_product(shop_name)
                else:
                    logger.warning("无法识别当前商店，返回后跳过")
                    self.device.click(ISLAND_BACK)
                    self.device.sleep(1)
                    continue
                self._confirm_business_start()
                self.post_manage_mode(POST_MANAGE_BUSINESS)
                self.device.sleep(0.5)
            elif status == 'yellow':
                logger.info("检测到黄色领取奖励按钮")
                self._claim_business_reward()
                self.post_manage_mode(POST_MANAGE_BUSINESS)
                self.device.sleep(0.5)
            elif status == 'darkblue':
                if self._has_seen_blue:
                    logger.info("经营已启动，正常退出")
                    self._trigger_shop_refill()
                    self._set_task_delay()
                    return
                logger.info("经营中，检测剩余时间")
                self._ocr_and_delay_business_remain()
                return
            elif status == 'gray':
                logger.info("不可经营，延后至明天0点")
                tomorrow = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                self.config.task_delay(target=tomorrow)
                return
            else:
                logger.info("按钮状态未知，跳过")
                continue

    # ===================================================================
    # 分批模式
    # ===================================================================

    def _run_batch_mode(self):
        """
        分批经营模式。

        流程：
        1. 执行第一批商店的经营
        2. 如果第一批商店仍在经营中，延迟第二批
        3. 第一批经营结束后，执行第二批
        4. 第二批结束后，设置延时
        """
        batch1_shops = self._get_batch1_shops()
        batch2_shops = self._get_batch2_shops()

        if not batch1_shops:
            logger.info("第一批未配置商店，跳过")
        else:
            logger.info(f"=== 第一批经营: {[s['name'] for s in batch1_shops]} ===")
            # 季节限定餐品检测替换（仅在第一批中有鱼餐馆存在时执行）
            if any(s['name'] == '有鱼餐馆' for s in batch1_shops):
                self._check_seasonal_dish_quantity_and_replace()
                # 重新导航回经营页面
                self.goto_postmanage()
                self._switch_to_business_tab()
                self._handle_food_review()

            self._run_batch(batch1_shops)

        # 检查第二批是否需要执行
        if not batch2_shops:
            logger.info("第二批未配置商店，跳过")
            return

        # 检查第一批商店是否仍在经营中
        if self._batch_is_still_running(batch1_shops):
            logger.info("第一批商店仍在经营中，延迟第二批")
            return

        logger.info(f"=== 第二批经营: {[s['name'] for s in batch2_shops]} ===")
        self._run_batch(batch2_shops)

    # ===================================================================
    # 分批模式：逐商店扫描 → 检测按钮状态 → 按状态处理
    # ===================================================================

    # 商店列表中的行常量
    # 列表页店名标签模板位于左侧，右侧经营按钮的 X 位置固定。
    # Y 位置跟随店名标签所在行偏移，用于检测/点击蓝色、黄色、深蓝按钮。
    _SHOP_BUTTON_X_RANGE = (1020, 1154)
    _SHOP_LABEL_TO_BUTTON_OFFSET_Y = 88
    _SHOP_BUTTON_HEIGHT = 27
    # 经营商店列表的可视区域
    _BUSINESS_LIST_SEARCH_AREA = (50, 80, 1200, 640)
    # 商店行高（经验值，适用于各行）
    _BUSINESS_ROW_HEIGHT = 160

    def _find_shop_on_screen(self, shop_name):
        """
        在经营页签列表中查找指定商店，返回其标签位置和按钮区域。

        在 _BUSINESS_LIST_SEARCH_AREA 区域内使用模板匹配搜索商店标签。
        如果商店标签在此区域内不可见，返回 None。

        Args:
            shop_name: 商店名称

        Returns:
            dict: {'label_rect': (x1,y1,x2,y2), 'button_rect': (x1,y1,x2,y2), 'similarity': float}
                  或 None（未找到）
        """
        template = self.SHOP_LIST_TEMPLATE_MAP.get(shop_name)
        if not template:
            return None

        s = self.device.image
        sx1, sy1, sx2, sy2 = self._BUSINESS_LIST_SEARCH_AREA
        area_img = crop(s, (sx1, sy1, sx2, sy2))

        sim, btn = template.match_result(area_img)
        if sim >= 0.7:
            # 从裁剪坐标偏移回全屏坐标
            lx1 = btn.area[0] + sx1
            ly1 = btn.area[1] + sy1
            lx2 = btn.area[2] + sx1
            ly2 = btn.area[3] + sy1
            label_rect = (lx1, ly1, lx2, ly2)

            # 计算右侧经营按钮区域。按钮宽度不能沿用店名标签宽度偏移，
            # 否则会落到中间餐品图标上，导致黄色结算按钮被误判为 gray。
            bx1, bx2 = self._SHOP_BUTTON_X_RANGE
            by1 = ly1 + self._SHOP_LABEL_TO_BUTTON_OFFSET_Y
            by2 = by1 + self._SHOP_BUTTON_HEIGHT
            button_rect = (bx1, by1, bx2, by2)

            return {
                'label_rect': label_rect,
                'button_rect': button_rect,
                'similarity': sim,
            }

        return None

    def _detect_button_at(self, button_rect):
        """
        在指定矩形区域内检测按钮的颜色状态。

        使用 get_color() 提取区域平均颜色，与已知的按钮颜色阈值比较。

        Args:
            button_rect: (x1, y1, x2, y2) 按钮区域

        Returns:
            str: 'blue' | 'yellow' | 'darkblue' | 'gray'
        """
        x1, y1, x2, y2 = button_rect
        area_color = get_color(self.device.image, (x1, y1, x2, y2))

        # 蓝色 (82, 197, 255) - 可经营（蓝色开始按钮）
        if color_similar(area_color, (82, 197, 255), threshold=80):
            return 'blue'
        # 黄色 (230, 192, 71) - 可领取奖励
        if color_similar(area_color, (230, 192, 71), threshold=80):
            return 'yellow'
        # 深蓝 (60, 67, 84) - 经营中
        if color_similar(area_color, (60, 67, 84), threshold=80):
            return 'darkblue'

        # 以上都不是 → 灰色不可经营
        return 'gray'

    def _scan_visible_batch_shops(self, batch_shops):
        """
        扫描当前视野中所有属于指定批次的商店。

        对每个商店：
        1. 在搜索区域内模板匹配其标签
        2. 若找到，计算按钮区域并检测按钮状态
        3. 按标签的 Y 坐标从上到下排序

        Args:
            batch_shops: 当前批次的商店列表

        Returns:
            list of dict:
            [{'shop': shop_dict, 'status': str, 'button_rect': tuple, 'label_rect': tuple, 'similarity': float}, ...]
        """
        self.device.screenshot()
        results = []

        for shop in batch_shops:
            found = self._find_shop_on_screen(shop['name'])
            if found:
                status = self._detect_button_at(found['button_rect'])
                results.append({
                    'shop': shop,
                    'status': status,
                    'button_rect': found['button_rect'],
                    'label_rect': found['label_rect'],
                    'similarity': found['similarity'],
                })

        # 按标签的 Y 坐标从上到下排序
        results.sort(key=lambda r: r['label_rect'][1])
        return results

    def _scroll_business_down(self):
        """在经营商店列表中向下滑动一页"""
        logger.info("向下滑动商店列表")
        self.device.swipe_vector(
            vector=(0, -450),
            box=(688, 120, 725, 656),
            name="BusinessListSwipe"
        )
        self.device.sleep(1.0)

    def _scroll_business_to_top(self):
        """将经营商店列表滑动回顶部"""
        logger.info("向上滑动回顶部")
        self.device.swipe_vector(
            vector=(0, 900),
            box=(688, 120, 725, 656),
            name="BusinessListSwipeTop"
        )
        self.device.sleep(1.0)

    def _process_shop_entry(self, shop):
        """进入商店后处理：加成替换 → 选角色 → 选餐品 → 确认经营"""
        shop_name = shop['name']
        self._load_shop_characters(shop)

        # 加成商品检测替换（在选择角色前）
        self._check_and_replace_boosted_product(shop_name)

        # 选择角色和餐品
        self._select_business_characters()
        self._select_business_product(shop_name)

        # 确认经营并返回
        self._confirm_business_start()
        self.post_manage_mode(POST_MANAGE_BUSINESS)
        self.device.sleep(0.5)

    def _check_batch_completion(self, batch_results):
        """
        根据各商店的检测结果判断批次是否全部完成。

        Returns:
            dict: {'done': bool, 'all_gray': bool, 'has_running': bool, 'has_blue': bool}
        """
        all_gray = all(r['status'] == 'gray' for r in batch_results)
        has_running = any(r['status'] == 'darkblue' for r in batch_results)
        has_blue = any(r['status'] == 'blue' for r in batch_results)

        return {
            'all_gray': all_gray,
            'has_running': has_running,
            'has_blue': has_blue,
        }

    def _run_batch(self, batch_shops):
        """
        执行指定批次的商店经营（逐商店扫描模式）。

        流程：
        1. 先向上滑动回到列表顶部
        2. 截图 → 扫描当前视野中属于本批次的商店
        3. 对每个可见商店检测按钮状态：
           - blue → 点击进入 → 处理 → 回到顶部 → 重新扫描
           - yellow → 领取奖励 → 回到顶部 → 重新扫描
           - darkblue → 记录为经营中，继续看下一个
           - gray → 跳过，继续看下一个
        4. 如果所有可见商店都处理完后还需要滚动：
           - 向下滑动 → 等待惯性结束 → 重新扫描可见商店
        5. 如果向下滑动也找不到更多 → 退出判断
        6. 退出前向上滑动回顶部

        Args:
            batch_shops: 当前批次的商店列表
        """
        self._has_seen_blue = False
        total_darkblue_count = 0  # 本批次内深蓝商店计数
        processed_shop_names = set()  # 已处理过的商店（进入或领取过）
        seen_shop_names = set()  # 跨滚动位置累积看到过的商店（用于判断是否已遍历全部）
        max_scrolls = 8  # 最大滑动次数

        # 先回到列表顶部
        self._scroll_business_to_top()

        scroll_attempt = 0
        while scroll_attempt < max_scrolls:
            visible_shops = self._scan_visible_batch_shops(batch_shops)

            if not visible_shops:
                logger.info("当前视野中无本批次商店，尝试向下滑动")
                if scroll_attempt < max_scrolls - 1:
                    self._scroll_business_down()
                    self.device.sleep(0.5)
                    scroll_attempt += 1
                    continue
                else:
                    break

            # 累积当前可见商店到 seen_shop_names
            for r in visible_shops:
                seen_shop_names.add(r['shop']['name'])

            logger.info(f"视野中可见的批次商店: {[r['shop']['name'] + '(' + r['status'] + ')' for r in visible_shops]}")

            # 遍历可见商店
            for shop_info in visible_shops:
                shop = shop_info['shop']
                shop_name = shop['name']
                status = shop_info['status']
                button_rect = shop_info['button_rect']

                if shop_name in processed_shop_names:
                    continue  # 这个商店已经处理过了

                if status == 'blue':
                    self._has_seen_blue = True
                    logger.info(f"{shop_name}: 蓝色可经营，点击进入")

                    # 点击该商店的按钮（使用动态坐标）
                    btn = Button(
                        area=button_rect, color=(),
                        button=button_rect,
                        file={'cn': ''}
                    )
                    self.device.click(btn)
                    self.device.sleep(1)

                    # 进入商店后处理
                    current_shop = self._detect_current_shop()
                    if current_shop and current_shop['name'] == shop_name:
                        self._process_shop_entry(current_shop)
                        processed_shop_names.add(shop_name)
                    else:
                        logger.warning(f"进入商店后识别到的不是 {shop_name}，返回后跳过")
                        self.device.click(ISLAND_BACK)
                        self.device.sleep(1)
                        self.post_manage_mode(POST_MANAGE_BUSINESS)
                        self.device.sleep(0.5)

                    # 返回后重新扫描（列表可能有变化）
                    self._scroll_business_to_top()
                    scroll_attempt = 0
                    break  # 重新扫描

                elif status == 'yellow':
                    logger.info(f"{shop_name}: 黄色可领取奖励")

                    # 点击该商店的黄色按钮
                    btn = Button(
                        area=button_rect, color=(),
                        button=button_rect,
                        file={'cn': ''}
                    )
                    self.device.click(btn)
                    self.device.sleep(1)

                    self._claim_business_reward(button_already_clicked=True)
                    self.post_manage_mode(POST_MANAGE_BUSINESS)
                    self.device.sleep(0.5)

                    processed_shop_names.add(shop_name)

                    # 返回后重新扫描
                    self._scroll_business_to_top()
                    scroll_attempt = 0
                    break  # 重新扫描

                elif status == 'darkblue':
                    logger.info(f"{shop_name}: 经营中，跳过")
                    total_darkblue_count += 1

                elif status == 'gray':
                    logger.info(f"{shop_name}: 不可经营，跳过")

            else:
                # 没有 break（所有可见商店都遍历完了，没有需要处理的）
                if len(seen_shop_names) < len(batch_shops):
                    # 累积看到的商店数少于批次总数，说明还有商店未找到，继续滚动
                    logger.info(f"累积看到 {len(seen_shop_names)}/{len(batch_shops)} 家商店，还有未找到的商店，尝试向下滑动")
                    if scroll_attempt < max_scrolls - 1:
                        self._scroll_business_down()
                        self.device.sleep(0.5)
                        scroll_attempt += 1
                        continue
                    else:
                        break
                else:
                    # 所有批次商店都已被看到过
                    logger.info(f"已遍历全部 {len(batch_shops)} 家商店，无待处理商店")
                    break

        # ========== 退出判断 ==========
        # 先回到顶部
        self._scroll_business_to_top()

        if total_darkblue_count > 0 and not self._has_seen_blue:
            # 所有商店都在经营中（从未处理过蓝色按钮）
            logger.info(f"批次所有商店均在经营中，检测剩余时间")
            self.device.screenshot()
            self._ocr_and_delay_business_remain()
            return

        if self._has_seen_blue:
            # 处理过蓝色按钮（部分或全部商店已启动）
            logger.info(f"批次经营已启动，正常退出")
            if batch_shops == self._get_batch2_shops() or not self._get_batch2_shops():
                self._trigger_shop_refill()
                self._set_task_delay()
            return

        # 所有商店都是灰色不可经营
        # 只有当前是第二批，或没有第二批时，才设置延后到明天0点
        # 第一批全 gray 时让 _run_batch_mode 继续处理第二批
        if batch_shops == self._get_batch2_shops() or not self._get_batch2_shops():
            logger.info("批次内所有商店不可经营，延后至明天0点")
            tomorrow = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            self.config.task_delay(target=tomorrow)

    def _batch_is_still_running(self, batch_shops):
        """
        检查指定批次是否仍有商店在经营中。

        使用逐商店扫描方式检测，如果任一商店为 darkblue 状态，
        则认为该批次仍在经营中，并 OCR 剩余时间设置延时。

        Args:
            batch_shops: 要检查的商店列表

        Returns:
            bool: True 表示仍在经营中
        """
        self._scroll_business_to_top()
        visible = self._scan_visible_batch_shops(batch_shops)

        running_shops = [r for r in visible if r['status'] == 'darkblue']
        if not running_shops:
            return False

        logger.info(f"检测到经营中的商店: {[r['shop']['name'] for r in running_shops]}")

        # OCR 剩余经营时间
        self.device.screenshot()
        ocr_remain = Duration(BUSINESS_REMAIN_TIME_AREA, lang='azur_lane',
                              letter=(255, 255, 255), threshold=128,
                              name='OCR_BUSINESS_REMAIN_BATCH')
        remain = ocr_remain.ocr(self.device.image)
        if remain and remain.total_seconds() > 0:
            delay_seconds = remain.total_seconds() + 300
            logger.info(f"剩余经营时间 {remain}，延时 {delay_seconds / 60:.1f} 分钟")
            self.config.task_delay(minute=delay_seconds / 60)
        else:
            logger.warning("剩余时间OCR失败，使用默认2小时延时")
            self.config.task_delay(minute=120)

        return True

    # ===================================================================
    # 公用方法（传统和分批模式共享）
    # ===================================================================

    def _ocr_and_delay_business_remain(self):
        """OCR 经营剩余时间并设置延时"""
        ocr_remain = Duration(BUSINESS_REMAIN_TIME_AREA, lang='azur_lane',
                              letter=(255, 255, 255), threshold=128,
                              name='OCR_BUSINESS_REMAIN')
        remain = ocr_remain.ocr(self.device.image)
        if remain and remain.total_seconds() > 0:
            delay_seconds = remain.total_seconds() + 300
            logger.info(f"经营剩余 {remain}，延时 {delay_seconds / 60:.1f} 分钟后检测")
            self.config.task_delay(minute=delay_seconds / 60)
        else:
            logger.warning("剩余时间OCR失败，使用默认2小时延时")
            next_time = self._calculate_darkblue_delay()
            self.config.task_delay(target=next_time)

    # 商店标签到对应 Template 的映射
    # TEMPLATE_BUSINESS_SHOP_* 是进入商店后显示的商店名称标签（店内用，120x35）
    # TEMPLATE_BUSINESS_LIST_SHOP_* 是经营列表页的商店标签（列表页用，107x26）
    SHOP_TEMPLATE_MAP = {
        '有鱼餐馆': TEMPLATE_BUSINESS_SHOP_FISH_RESTAURANT,
        '白熊饮品': TEMPLATE_BUSINESS_SHOP_TEAHOUSE,
        '啾啾简餐': TEMPLATE_BUSINESS_SHOP_JUU_EATERY,
        '乌鱼烤肉': TEMPLATE_BUSINESS_SHOP_GRILL,
        '啾咖啡': TEMPLATE_BUSINESS_SHOP_JUU_COFFEE,
    }

    # 经营列表页商店标签模板映射（用于 _find_shop_on_screen 列表页匹配）
    SHOP_LIST_TEMPLATE_MAP = {
        '有鱼餐馆': TEMPLATE_BUSINESS_LIST_SHOP_FISH_RESTAURANT,
        '白熊饮品': TEMPLATE_BUSINESS_LIST_SHOP_TEAHOUSE,
        '啾啾简餐': TEMPLATE_BUSINESS_LIST_SHOP_JUU_EATERY,
        '乌鱼烤肉': TEMPLATE_BUSINESS_LIST_SHOP_GRILL,
        '啾咖啡': TEMPLATE_BUSINESS_LIST_SHOP_JUU_COFFEE,
    }

    def _detect_current_shop(self):
        """进入商店后，用模板匹配检测商店标签确定当前是哪个商店（同时检查正常和偏移150px位置）"""
        self.device.screenshot()
        areas = [
            (548, 90, 668, 125),           # 正常位置
            (698, 90, 818, 125),            # 偏移150px（美食评审模式）
        ]

        best = (None, None, 0.0)  # (shop, button, similarity)
        for area in areas:
            area_img = crop(self.device.image, area)
            for shop in self.shops:
                t = self.SHOP_TEMPLATE_MAP.get(shop['name'])
                if not t:
                    continue
                sim, _ = t.match_result(area_img)
                if sim > best[2]:
                    best = (shop, None, sim)

        if best[0] is not None and best[2] >= 0.7:
            logger.info(f"检测到商店: {best[0]['name']} (相似度: {best[2]:.2f})")
            return best[0]
        return None

    def _handle_food_review(self):
        """
        处理每日首次进入经营页签时可能出现的美食评审界面
        流程：检测弹窗 → 点击安全区域关闭 → 检测详情弹窗 → 再点安全区域
        """
        logger.info("检测美食评审界面")
        self.device.screenshot()

        # 如果经营页签按钮被遮挡，说明有弹窗
        if not self.appear(POST_MANAGE_BUSINESS, offset=30) and not self.appear(POST_MANAGE_PRODUCTION, offset=30):
            logger.info("检测到美食评审界面，点击安全区域关闭")
            self.device.click(BUSINESS_REVIEW_SAFE_AREA)
            self.device.sleep(1)

            # 检测详情界面
            self.device.screenshot()
            if not self.appear(POST_MANAGE_BUSINESS, offset=30) and not self.appear(POST_MANAGE_PRODUCTION, offset=30):
                logger.info("检测到美食评审详情界面，再次点击安全区域")
                self.device.click(BUSINESS_REVIEW_SAFE_AREA)
                self.device.sleep(1)

            # 确保回到经营页签
            self.device.screenshot()
            if not self.appear(POST_MANAGE_BUSINESS, offset=30) and not self.appear(POST_MANAGE_PRODUCTION, offset=30):
                logger.warning("关闭美食评审后未回到经营页签，重新进入")
                self.goto_postmanage()
                self.post_manage_mode(POST_MANAGE_BUSINESS)
                self.device.sleep(1)

        logger.info("美食评审处理完成")

    def _calculate_darkblue_delay(self):
        """计算深蓝（经营中）状态的延后检测时间"""
        now = datetime.now()

        # 延后2小时
        delayed = now + timedelta(hours=2)

        # 当天23:55
        today_2355 = now.replace(hour=23, minute=55, second=0, microsecond=0)

        if now >= today_2355:
            # 如果当前时间已超过23:55，重置为第二天0点
            next_time = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            logger.info(f"当前时间已超过23:55，重置为明天0点")
        elif delayed > today_2355:
            # 如果延后时间超过23:55，则设为23:55
            next_time = today_2355
            logger.info(f"延后时间超过23:55，设为今天23:55")
        else:
            next_time = delayed
            logger.info(f"设定延后2小时检测")

        return next_time

    def _check_start_button_status(self):
        self.device.screenshot()
        if self.appear(BUSINESS_START_BUTTON_BLUE, offset=30):
            return 'blue'
        if self.appear(BUSINESS_START_BUTTON_YELLOW, offset=30):
            return 'yellow'
        if self.appear(BUSINESS_START_BUTTON_DARKBLUE, offset=30):
            return 'darkblue'
        # 三个可经营按钮都未识别到 → 视为灰色不可经营状态
        return 'gray'

    def _claim_business_reward(self, button_already_clicked=False):
        """
        领取经营奖励。

        处理从点击黄色按钮到回到经营界面的完整流程。
        如果在调用前已经点击了黄色按钮（分批模式），设置 button_already_clicked=True。

        Args:
            button_already_clicked: 是否已在外部点击了黄色按钮
        """
        logger.info("领取经营奖励")

        if not button_already_clicked:
            # 传统模式：先点击黄色按钮进入结算界面
            self.device.click(BUSINESS_START_BUTTON_YELLOW)
            self.device.sleep(1)
            # 如果黄色奖励按钮还在，继续点击直到消失
            self.device.screenshot()
            for _ in range(5):
                if self.appear(BUSINESS_START_BUTTON_YELLOW, offset=30):
                    logger.info("黄色奖励按钮仍在，再次点击")
                    self.device.click(BUSINESS_START_BUTTON_YELLOW)
                    self.device.sleep(1)
                    self.device.screenshot()
                else:
                    break

        # 统一截图-检测循环，处理从结算到回到经营界面的整个流程
        # 每次循环检测当前界面状态，执行对应操作，直到回到经营页签
        self.device.sleep(1)
        timeout = 0
        while True:
            if timeout > 40:
                logger.warning("领取奖励流程超时，跳过")
                return

            self.device.screenshot()

            # 已回到经营页签 → 退出
            if self.appear(POST_MANAGE_BUSINESS, offset=30) or self.appear(POST_MANAGE_PRODUCTION, offset=30):
                logger.info("已回到经营界面，退出领取")
                return

            # 检测到"经营结算"按钮 → 优先处理结算（必须在 ISLAND_BACK 之前检测，
            # 防止结算界面出现时返回按钮也被检测到而导致提前退出）
            # 同时检测偏移150px位置（美食评审模式）
            settlement = self._appear_business_settlement()
            if settlement:
                logger.info("检测到经营结算按钮")
                self.device.click(settlement)
                self.device.sleep(1)

            # 检测到"获得物品" → 点击安全区域
            elif self.appear(BUSINESS_OBTAINED_ITEMS, offset=30):
                logger.info("检测到获得物品")
                self.device.click(BUSINESS_REWARD_SAFE_AREA)
                self.device.sleep(1)

            # 检测到"销售情况" → 点击安全区域
            elif self.appear(BUSINESS_SALES_STATUS, offset=30):
                logger.info("检测到销售情况")
                self.device.click(BUSINESS_REWARD_SAFE_AREA)
                self.device.sleep(1)

            # 检测到返回按钮 → 点击返回
            elif self.appear(ISLAND_BACK, offset=30):
                logger.info("检测到返回按钮，点击返回")
                self.device.click(ISLAND_BACK)
                self.device.sleep(1)

            # 无识别的界面元素，点击安全区域等待
            else:
                self.device.click(BUSINESS_REWARD_SAFE_AREA)
                self.device.sleep(1)

            # 统一在循环末尾递增 timeout，确保每次循环仅递增一次
            timeout += 1

    def _select_business_characters(self):
        for slot_idx in range(2):
            btn = BUSINESS_PLUS_A if slot_idx == 0 else BUSINESS_PLUS_B
            plus_button = self._appear_at_positions(btn)
            if not plus_button:
                # 第一次未检测到，在正常位置重试3次
                for retry in range(3):
                    logger.info(f"第{slot_idx + 1}个'+'按钮未找到(正常位置)，等待1s重试({retry + 1}/3)")
                    self.device.sleep(1.0)
                    plus_button = self._appear_at_positions(btn)
                    if plus_button:
                        break
            if not plus_button:
                # 正常位置未找到，向右偏移150px再试3次（美食评审偏移）
                review_btn = self._get_review_button(btn)
                if review_btn:
                    for retry in range(3):
                        logger.info(f"第{slot_idx + 1}个'+'按钮未找到(偏移位置)，等待1s重试({retry + 1}/3)")
                        self.device.sleep(1.0)
                        self.device.screenshot()
                        if self.appear(review_btn, offset=30):
                            plus_button = review_btn
                            break
            if not plus_button:
                logger.info(f"第{slot_idx + 1}个'+'按钮未找到(共尝试6次)，跳过")
                continue
            self.device.click(plus_button)
            self.device.sleep(0.5)
            if not self._wait_for_character_selection():
                continue
            result = self._find_and_select_character()
            if result:
                selected_name = result
                logger.info(f"第{slot_idx + 1}个角色选择成功: {selected_name}")
                # 已选角色从优先级中移除，防止下个槽位重复选择
                if selected_name in self.character_priority:
                    self.character_priority.remove(selected_name)
                self.device.click(SELECT_UI_CONFIRM)
                self.device.sleep(0.5)
                # 确认后等待界面刷新，再检测第二个"+"按钮
                self.device.screenshot()
                self.device.sleep(1)
            else:
                logger.info(f"第{slot_idx + 1}个角色未找到，跳过")
                self.device.click(SELECT_UI_BACK)
                self.device.sleep(0.5)

    def _wait_for_character_selection(self):
        from module.base.timer import Timer
        timer = Timer(5).start()
        while not timer.reached():
            self.device.screenshot()
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                return True
            self.device.sleep(0.3)
        return False

    # 角色选择列表全区域坐标
    BUSINESS_CHARACTER_AREA = (55, 139, 878, 463)

    def _stop_swipe_inertia(self):
        """滑动后点击安全区域消除惯性"""
        self.device.click(BUSINESS_REVIEW_SAFE_AREA)
        self.device.sleep(0.3)

    # 角色选择页面滑动惯性消除安全区域
    BUSINESS_INERTIA_STOP_AREA = (462, 477, 473, 577)

    def _swipe_down_short(self):
        """短距离向下滑动，滑动后立即点击安全区域消除惯性"""
        self.device.swipe_vector(vector=(0, -200), box=(58, 150, 838, 480),
                                 duration=(0.3, 0.5), name="BusinessCharSwipe")
        self.device.click(Button(area=(), color=(), button=self.BUSINESS_INERTIA_STOP_AREA, file={'cn': ''}))
        self.device.sleep(1.0)

    def _swipe_up_reset(self):
        """向上滑动回到顶部，滑动后立即点击安全区域消除惯性"""
        self.device.swipe_vector(vector=(0, 500), box=(58, 150, 838, 480),
                                 duration=(0.3, 0.5), name="BusinessCharSwipeReset")
        self.device.sleep(0.5)
        self.device.click(Button(area=(), color=(), button=self.BUSINESS_INERTIA_STOP_AREA, file={'cn': ''}))
        self.device.sleep(1.0)

    def _find_and_select_character(self):
        """在角色选择界面中查找并选择角色（全区域模板匹配）"""
        # 进入角色选择界面后，先向上滑动500px回到顶部
        self._swipe_up_reset()

        max_swipes = 5
        for attempt in range(max_swipes):
            self.device.screenshot()
            result = self._find_best_character()
            if result:
                char_name, button = result
                logger.info(f"选择角色: {char_name}")
                self.device.click(button)
                self.device.sleep(0.5)
                return char_name
            # 短距离向下滑动继续搜索
            self._swipe_down_short()

        # 滑动多次未找到，切换排序后从头搜索
        self.select_character_filter()
        self.device.sleep(0.5)
        self._swipe_up_reset()

        for attempt in range(max_swipes):
            self.device.screenshot()
            result = self._find_best_character()
            if result:
                char_name, button = result
                logger.info(f"切换排序后选择角色: {char_name}")
                self.device.click(button)
                self.device.sleep(0.5)
                return char_name
            self._swipe_down_short()

        return False

    def _find_best_character(self):
        """
        在全区域 (55, 139, 878, 563) 内进行模板匹配查找角色。
        只匹配 character_priority 中指定的角色，不做全量扫描。
        返回 (角色名, Button) 或 None。
        """
        s = self.device.image
        area_img = crop(s, self.BUSINESS_CHARACTER_AREA)
        best = (None, None, 0.0)  # (name, button, similarity)

        # 只遍历优先级列表中的角色模板，跳过不在优先级中的角色
        for name in self.character_priority:
            template = self.character_templates.get(name)
            if template is None:
                continue
            sim, btn = template.match_result(area_img)
            if sim >= 0.8 and sim > best[2]:
                # 创建新 Button，坐标从裁剪区域偏移回全屏坐标
                old_area = btn.area
                new_area = (old_area[0] + self.BUSINESS_CHARACTER_AREA[0],
                            old_area[1] + self.BUSINESS_CHARACTER_AREA[1],
                            old_area[2] + self.BUSINESS_CHARACTER_AREA[0],
                            old_area[3] + self.BUSINESS_CHARACTER_AREA[1])
                offset_btn = Button(area=new_area, color=btn.color, button=new_area, file=btn.file)
                best = (name, offset_btn, sim)

        if best[0] is not None:
            return (best[0], best[1])
        return None

    # 餐品图标检测区域（选完角色后餐品列表在此范围内）
    BUSINESS_PRODUCT_AREA = (580, 200, 1177, 400)

    def _get_product_template_path(self, button):
        """从Button的file路径构造TEMPLATE小图路径"""
        fp = button.file
        # ./assets/cn/island_business/BUSINESS_PRODUCT_XXX.png
        # -> ./assets/cn/island_business/TEMPLATE_BUSINESS_PRODUCT_XXX.png
        dir_name = os.path.dirname(fp)
        base_name = os.path.basename(fp)
        return os.path.join(dir_name, f'TEMPLATE_{base_name}')

    def _select_business_product(self, shop_name=None):
        # 优先使用配置的产品列表，否则使用全部
        products = self.active_products.get(shop_name, self.shop_products.get(shop_name, []))
        if not products:
            return
        # 等待界面稳定
        self.device.sleep(1.0)

        # 逐个选择配置的餐品
        for p in products:
            b = p.get('button')
            if not b or not b.file:
                continue
            self.device.screenshot()
            area_img = crop(self.device.image, self.BUSINESS_PRODUCT_AREA)
            sim, btn = b.match_result(area_img)
            if sim >= 0.7:
                # 偏移回全屏坐标
                old_area = btn.area
                new_area = (old_area[0] + self.BUSINESS_PRODUCT_AREA[0],
                            old_area[1] + self.BUSINESS_PRODUCT_AREA[1],
                            old_area[2] + self.BUSINESS_PRODUCT_AREA[0],
                            old_area[3] + self.BUSINESS_PRODUCT_AREA[1])
                offset_btn = Button(area=new_area, color=(), button=new_area, file=b.file)
                logger.info(f"选择餐品: {p['name']} (相似度: {sim:.2f})")
                self.device.click(offset_btn)
                self.device.sleep(0.5)

    def _confirm_business_start(self):
        start_button = self._appear_at_positions(BUSINESS_START_IN_SHOP)
        if start_button:
            logger.info("确认经营")
            self.device.click(start_button)
            self.device.sleep(1)
            # 确认经营后检测并跳过可能的周常/PT奖励弹窗
            self.device.screenshot()
            for _ in range(3):
                if self.handle_popup_single('BUSINESS'):
                    self.device.sleep(0.5)
                    self.device.screenshot()
                else:
                    break
            self.device.click(ISLAND_BACK)
            self.device.sleep(1)
            self.device.screenshot()
            if not self.appear(POST_MANAGE_BUSINESS, offset=30) and not self.appear(POST_MANAGE_PRODUCTION, offset=30):
                self.goto_postmanage()
                self.post_manage_mode(POST_MANAGE_BUSINESS)
                self.device.sleep(1)

    def _trigger_shop_refill(self):
        for t in ['IslandRestaurant', 'IslandTeahouse', 'IslandGrill', 'IslandJuuEatery', 'IslandJuuCoffee']:
            self.config.task_delay(minute=0, task=t)

    def _set_task_delay(self):
        self.config.task_delay(minute=60 * 8)


if __name__ == "__main__":
    IslandBusiness('alas', task='Alas').run()

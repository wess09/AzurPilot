"""
岛屿农场（Island Farm）自动化管理模块。

负责岛屿系统中农场、果园、苗圃三大生产区域的自动化管理，包括：
- 仓库库存检查与低库存作物识别
- 空闲岗位检测与自动播种
- 作物选择策略：优先补种低于阈值的作物，其次种植默认作物
- 工人派遣与角色筛选（含小天城橡胶树优先机制）
- 季节限定作物的智能过滤
- 种子不足时自动从商店购买

管理的生产区域：
- 农场（farm）：小麦、玉米、水稻、白菜、土豆、大豆、牧草、咖啡豆
- 果园（orchard）：苹果、柑橘、香蕉、芒果、柠檬、牛油果、橡胶
  （秋季限定：秋月梨、柿子，4x1 种植——每次派遣只消耗 4 颗种子）
- 苗圃（nursery）：胡萝卜、洋葱、亚麻、草莓、棉花、茶叶、薰衣草、菠萝、芦笋
"""
from module.island_farm.assets import *
from module.island.island import *
from datetime import timedelta
from module.config.time_source import now as current_time
from module.handler.login import LoginHandler
from module.island.warehouse import *
from module.logger import logger


class IslandFarm(Island, WarehouseOCR, LoginHandler):
    """
    岛屿农场自动化管理器。

    继承 Island（岛屿基础操作）、WarehouseOCR（仓库 OCR 识别）和
    LoginHandler（登录处理），实现农场、果园、苗圃的全自动管理。

    执行流程：
    1. 进入岛屿并检查仓库库存，识别低库存作物
    2. 进入岗位管理页面，遍历所有岗位检测状态
    3. 对空闲岗位执行播种（优先补种低库存作物，其次默认作物）
    4. 计算下次运行时间（取所有岗位完成时间和 6 小时后的最小值）

    Attributes:
        season_config: 季节配置对象，用于季节限定作物过滤。
        farm_positions (int): 农场岗位数量。
        orchard_positions (int): 果园岗位数量。
        nursery_positions (int): 苗圃岗位数量。
        farm_threshold (int): 农场作物库存最低阈值。
        orchard_threshold (int): 果园作物库存最低阈值。
        nursery_threshold (int): 苗圃作物库存最低阈值。
        worker_filters (dict): 各区域的工人派遣角色筛选器。
        ignore_avocado (bool): 是否忽略牛油果。
        ignore_pineapple (bool): 是否忽略菠萝。
        plant_config (dict): 各区域的默认作物种植配置。
        INVENTORY_CONFIG (dict): 各区域的仓库物品配置（模板、选择按钮、种子数量等）。
        posts (dict): 岗位信息字典，包含按钮和当前种植作物。
        to_plant_lists (dict): 各区域需要补种的作物列表。
        name_to_config (dict): 作物名称到配置项的映射。
        inventory_counts (dict): 各区域的仓库库存统计。
    """
    def __init__(self, *args, **kwargs):
        Island.__init__(self, *args, **kwargs)
        WarehouseOCR.__init__(self)
        
        # === 初始化全局季节配置 ===
        from module.island.island_season import get_global_season_config
        self.season_config = get_global_season_config(self.config)
        if self.season_config.is_seasonal_enabled:
            logger.info(f"[岛屿-农田] 当前季节: {self.season_config.season_name}，季节限定作物将根据配置启用")

        self.farm_positions = self.config.IslandFarm_Positions
        self.orchard_positions = self.config.IslandOrchard_Positions
        self.nursery_positions = self.config.IslandNursery_Positions
        self.farm_threshold = self.config.IslandFarm_MinFarm
        self.orchard_threshold = self.config.IslandOrchard_MinOrchard
        self.nursery_threshold = self.config.IslandNursery_MinNursery
        self.worker_filters = {
            'farm': self.config.IslandFarm_WorkerFilter,
            'orchard': self.config.IslandOrchard_WorkerFilter,
            'nursery': self.config.IslandNursery_WorkerFilter,
        }

        self.ignore_avocado = self.config.IslandOrchard_IgnoreAvocado
        self.ignore_pineapple = self.config.IslandNursery_IgnorePineapple

        # 修改默认作物配置：数值类型，表示要种植默认作物的岗位数量
        self.plant_config = {
            'farm': {
                'plant_default': self.config.IslandFarm_PlantPotatoes,  # 0-4
                'default_crop': 'wheat'
            },
            'orchard': {
                'plant_default': self.config.IslandOrchard_PlantRubber,  # 0-4
                'default_crop': 'rubber'
            },
            'nursery': {
                'plant_default': self.config.IslandNursery_PlantLavender,  # 0-2
                'default_crop': 'lavender'
            }
        }

        self.INVENTORY_CONFIG = {
            'farm': {
                'filter': 'farm',
                'threshold': self.farm_threshold,
                'items': [
                    {'name': 'wheat', 'template': TEMPLATE_WHEAT, 'var_name': 'wheat',
                     'selection': SELECT_WHEAT, 'selection_check': SELECT_WHEAT_CHECK,
                     'post_action': POST_WHEAT, 'category': 'farm', 'seed_number': 99,
                     'shop': SHOP_SEED_WHEAT},
                    {'name': 'corn', 'template': TEMPLATE_CORN, 'var_name': 'corn',
                     'selection': SELECT_CORN, 'selection_check': SELECT_CORN_CHECK,
                     'post_action': POST_CORN, 'category': 'farm', 'seed_number': 99,
                     'shop': SHOP_SEED_CORN},
                    {'name': 'rice', 'template': TEMPLATE_RICE, 'var_name': 'rice',
                     'selection': SELECT_RICE, 'selection_check': SELECT_RICE_CHECK,
                     'post_action': POST_RICE, 'category': 'farm', 'seed_number': 45,
                     'shop': SHOP_SEED_RICE},
                    {'name': 'chinese_cabbage', 'template': TEMPLATE_CHINESE_CABBAGE, 'var_name': 'chinese_cabbage',
                     'selection': SELECT_CHINESE_CABBAGE, 'selection_check': SELECT_CHINESE_CABBAGE_CHECK,
                     'post_action': POST_CHINESE_CABBAGE, 'category': 'farm', 'seed_number': 99,
                     'shop': SHOP_SEED_CHINESE_CABBAGE},
                    {'name': 'potato', 'template': TEMPLATE_POTATO, 'var_name': 'potato',
                     'selection': SELECT_POTATO, 'selection_check': SELECT_POTATO_CHECK,
                     'post_action': POST_POTATO, 'category': 'farm', 'seed_number': 36,
                     'shop': SHOP_SEED_POTATO},
                    {'name': 'soybean', 'template': TEMPLATE_SOYBEAN, 'var_name': 'soybean',
                     'selection': SELECT_SOYBEAN, 'selection_check': SELECT_SOYBEAN_CHECK,
                     'post_action': POST_SOYBEAN, 'category': 'farm', 'seed_number': 45,
                     'shop': SHOP_SEED_SOYBEAN},
                    {'name': 'pasture', 'template': TEMPLATE_PASTURE, 'var_name': 'pasture',
                     'selection': SELECT_PASTURE, 'selection_check': SELECT_PASTURE_CHECK,
                     'post_action': POST_PASTURE, 'category': 'farm', 'seed_number': 99,
                     'shop': SHOP_SEED_PASTURE},
                    {'name': 'coffee_bean', 'template': TEMPLATE_COFFEE_BEAN, 'var_name': 'coffee_bean',
                     'selection': SELECT_COFFEE_BEAN, 'selection_check': SELECT_COFFEE_BEAN_CHECK,
                     'post_action': POST_COFFEE_BEAN, 'category': 'farm', 'seed_number': 36,
                     'shop': SHOP_SEED_COFFEE_BEAN},
                ]
            },
            'orchard': {
                'filter': 'orchard',
                'threshold': self.orchard_threshold,
                'items': [
                    {'name': 'apple', 'template': TEMPLATE_APPLE, 'var_name': 'apple',
                     'selection': SELECT_APPLE, 'selection_check': SELECT_APPLE_CHECK,
                     'post_action': POST_APPLE, 'category': 'orchard', 'seed_number': 20,
                     'shop': SHOP_SEED_APPLE},
                    {'name': 'citrus', 'template': TEMPLATE_CITRUS, 'var_name': 'citrus',
                     'selection': SELECT_CITRUS, 'selection_check': SELECT_CITRUS_CHECK,
                     'post_action': POST_CITRUS, 'category': 'orchard', 'seed_number': 20,
                     'shop': SHOP_SEED_CITRUS},
                    {'name': 'banana', 'template': TEMPLATE_BANANA, 'var_name': 'banana',
                     'selection': SELECT_BANANA, 'selection_check': SELECT_BANANA_CHECK,
                     'post_action': POST_BANANA, 'category': 'orchard', 'seed_number': 16,
                     'shop': SHOP_SEED_BANANA},
                    {'name': 'mango', 'template': TEMPLATE_MANGO, 'var_name': 'mango',
                     'selection': SELECT_MANGO, 'selection_check': SELECT_MANGO_CHECK,
                     'post_action': POST_MANGO, 'category': 'orchard', 'seed_number': 16,
                     'shop': SHOP_SEED_MANGO},
                    {'name': 'lemon', 'template': TEMPLATE_LEMON, 'var_name': 'lemon',
                     'selection': SELECT_LEMON, 'selection_check': SELECT_LEMON_CHECK,
                     'post_action': POST_LEMON, 'category': 'orchard', 'seed_number': 28,
                     'shop': SHOP_SEED_LEMON},
                    {'name': 'avocado', 'template': TEMPLATE_AVOCADO, 'var_name': 'avocado',
                     'selection': SELECT_AVOCADO, 'selection_check': SELECT_AVOCADO_CHECK,
                     'post_action': POST_AVOCADO, 'category': 'orchard', 'seed_number': 16,
                     'shop': SHOP_SEED_AVOCADO},
                    {'name': 'rubber', 'template': TEMPLATE_RUBBER, 'var_name': 'rubber',
                     'selection': SELECT_RUBBER, 'selection_check': SELECT_RUBBER_CHECK,
                     'post_action': POST_RUBBER, 'category': 'orchard', 'seed_number': 16,
                     'shop': SHOP_SEED_RUBBER},
                    # 秋季限定（坠香果园）：秋月梨、柿子
                    # 4x1 种植：每次派遣只消耗 4 颗种子（果园其他作物每单至少 4x4=16 颗）
                    {'name': 'pear', 'template': TEMPLATE_PEAR, 'var_name': 'pear',
                     'selection': SELECT_PEAR, 'selection_check': SELECT_PEAR_CHECK,
                     'post_action': POST_PEAR, 'category': 'orchard', 'seed_number': 4,
                     'batch_4x1': True, 'shop': SHOP_SEED_PEAR},
                    {'name': 'persimmon', 'template': TEMPLATE_PERSIMMON, 'var_name': 'persimmon',
                     'selection': SELECT_PERSIMMON, 'selection_check': SELECT_PERSIMMON_CHECK,
                     'post_action': POST_PERSIMMON, 'category': 'orchard', 'seed_number': 4,
                     'batch_4x1': True, 'shop': SHOP_SEED_PERSIMMON},
                ]
            },
            'nursery': {
                'filter': 'nursery',
                'threshold': self.nursery_threshold,
                'items': [
                    {'name': 'carrot', 'template': TEMPLATE_CARROT, 'var_name': 'carrot',
                     'selection': SELECT_CARROT, 'selection_check': SELECT_CARROT_CHECK,
                     'post_action': POST_CARROT, 'category': 'nursery', 'seed_number': 33,
                     'shop': SHOP_SEED_CARROT},
                    {'name': 'onion', 'template': TEMPLATE_ONION, 'var_name': 'onion',
                     'selection': SELECT_ONION, 'selection_check': SELECT_ONION_CHECK,
                     'post_action': POST_ONION, 'category': 'nursery', 'seed_number': 12,
                     'shop': SHOP_SEED_ONION},
                    {'name': 'flax', 'template': TEMPLATE_FLAX, 'var_name': 'flax',
                     'selection': SELECT_FLAX, 'selection_check': SELECT_FLAX_CHECK,
                     'post_action': POST_FLAX, 'category': 'nursery', 'seed_number': 33,
                     'shop': SHOP_SEED_FLAX},
                    {'name': 'strawberry', 'template': TEMPLATE_STRAWBERRY, 'var_name': 'strawberry',
                     'selection': SELECT_STRAWBERRY, 'selection_check': SELECT_STRAWBERRY_CHECK,
                     'post_action': POST_STRAWBERRY, 'category': 'nursery', 'seed_number': 12,
                     'shop': SHOP_SEED_STRAWBERRY},
                    {'name': 'cotton', 'template': TEMPLATE_COTTON, 'var_name': 'cotton',
                     'selection': SELECT_COTTON, 'selection_check': SELECT_COTTON_CHECK,
                     'post_action': POST_COTTON, 'category': 'nursery', 'seed_number': 21,
                     'shop': SHOP_SEED_COTTON},
                    {'name': 'tea', 'template': TEMPLATE_TEA, 'var_name': 'tea',
                     'selection': SELECT_TEA, 'selection_check': SELECT_TEA_CHECK,
                     'post_action': POST_TEA, 'category': 'nursery', 'seed_number': 12,
                     'shop': SHOP_SEED_TEA},
                    {'name': 'lavender', 'template': TEMPLATE_LAVENDER, 'var_name': 'lavender',
                     'selection': SELECT_LAVENDER, 'selection_check': SELECT_LAVENDER_CHECK,
                     'post_action': POST_LAVENDER, 'category': 'nursery', 'seed_number': 12,
                     'shop': SHOP_SEED_LAVENDER},
                    {'name': 'pineapple', 'template': TEMPLATE_PINEAPPLE, 'var_name': 'pineapple',
                     'selection': SELECT_PINEAPPLE, 'selection_check': SELECT_PINEAPPLE_CHECK,
                     'post_action': POST_PINEAPPLE, 'category': 'nursery', 'seed_number': 12,
                     'shop': SHOP_SEED_PINEAPPLE},
                    {'name': 'asparagus', 'template': TEMPLATE_ASPARAGUS, 'var_name': 'asparagus',
                     'selection': SELECT_ASPARAGUS, 'selection_check': SELECT_ASPARAGUS_CHECK,
                     'post_action': POST_ASPARAGUS, 'category': 'nursery', 'seed_number': 12,
                     'shop': SHOP_SEED_ASPARAGUS},
                ]
            }
        }

        # 简化岗位信息，只保留按钮和作物信息
        self.posts = {
            'ISLAND_FARM_POST1': {'button': ISLAND_FARM_POST1, 'crop': None},
            'ISLAND_FARM_POST2': {'button': ISLAND_FARM_POST2, 'crop': None},
            'ISLAND_FARM_POST3': {'button': ISLAND_FARM_POST3, 'crop': None},
            'ISLAND_FARM_POST4': {'button': ISLAND_FARM_POST4, 'crop': None},

            'ISLAND_ORCHARD_POST1': {'button': ISLAND_ORCHARD_POST1, 'crop': None},
            'ISLAND_ORCHARD_POST2': {'button': ISLAND_ORCHARD_POST2, 'crop': None},
            'ISLAND_ORCHARD_POST3': {'button': ISLAND_ORCHARD_POST3, 'crop': None},
            'ISLAND_ORCHARD_POST4': {'button': ISLAND_ORCHARD_POST4, 'crop': None},

            'ISLAND_NURSERY_POST1': {'button': ISLAND_NURSERY_POST1, 'crop': None},
            'ISLAND_NURSERY_POST2': {'button': ISLAND_NURSERY_POST2, 'crop': None}
        }

        self.to_plant_lists = {
            'farm': [],
            'orchard': [],
            'nursery': []
        }
        self.name_to_config = {}
        for category in self.INVENTORY_CONFIG.values():
            for item in category.get('items', []):
                self.name_to_config[item['name']] = item
        self.inventory_counts = {
            'farm': {},
            'orchard': {},
            'nursery': {}
        }

    def check_inventory_and_prepare_lists(self):
        """检查库存并准备需要补种的列表（按库存升序，最少的优先）"""
        for category in ['farm', 'orchard', 'nursery']:
            inventory = self.warehouse_inventory(category)
            config = self.INVENTORY_CONFIG[category]
            threshold = config['threshold']
            self.inventory_counts[category] = inventory
            for item_name, count in inventory.items():
                if category == 'orchard' and item_name == 'avocado' and self.ignore_avocado:
                    continue
                if category == 'nursery' and item_name == 'pineapple' and self.ignore_pineapple:
                    continue
                # === 季节限定：不在当季的果园作物（如秋季的秋月梨/柿子）不列入补种计划 ===
                if category == 'orchard' and hasattr(self, 'season_config'):
                    if not self._is_orchard_crop_in_season(item_name):
                        logger.info(f"[岛屿-农田] 跳过非当季果园作物: {item_name}")
                        continue
                # === 季节限定：不在当季的作物不列入补种计划 ===
                if category == 'nursery' and hasattr(self, 'season_config'):
                    if not self._is_nursery_crop_in_season(item_name):
                        logger.info(f"[岛屿-农田] 跳过非当季苗圃作物: {item_name}")
                        continue
                if count < threshold:
                    self.to_plant_lists[category].append(item_name)
            # 库存最少的作物排最前，轮转分配时优先补种
            self.to_plant_lists[category].sort(key=lambda name: inventory.get(name, 0))

    def _is_orchard_crop_in_season(self, crop_name):
        """
        检查果园作物是否在当季（按季节配置）。

        秋季的秋月梨/柿子属于果园季节限定作物（坠香果园），只在秋季补种；
        非季节限定的果园作物（苹果、橡胶等）始终返回 True。
        """
        if not hasattr(self, 'season_config') or not self.season_config.is_seasonal_enabled:
            return True
        # 获取当前季节的 orchard 限定作物列表
        seasonal_items = self.season_config.get_seasonal_items('orchard')
        # 检查该作物是否是任何季节的限定品
        from module.island.island_season import SEASONAL_ITEMS
        for season_key in ['spring', 'summer', 'autumn', 'winter']:
            other_items = SEASONAL_ITEMS.get(season_key, {}).get('orchard', [])
            if crop_name in other_items:
                # 该作物是季节限定品，检查是否在当季
                return crop_name in seasonal_items
        # 非季节限定作物，始终可用
        return True

    def _is_nursery_crop_in_season(self, crop_name):
        """
        检查苗圃作物是否在当季（按季节配置）
        非季节限定的作物始终返回 True
        """
        if not hasattr(self, 'season_config') or not self.season_config.is_seasonal_enabled:
            return True
        # 获取当前季节的 nursery 限定作物列表
        seasonal_items = self.season_config.get_seasonal_items('nursery')
        # 检查该作物是否是任何季节的限定品
        from module.island.island_season import SEASONAL_ITEMS
        for season_key in ['spring', 'summer', 'autumn', 'winter']:
            other_items = SEASONAL_ITEMS.get(season_key, {}).get('nursery', [])
            if crop_name in other_items:
                # 该作物是季节限定品，检查是否在当季
                return crop_name in seasonal_items
        # 非季节限定作物，始终可用
        return True

    def warehouse_inventory(self, category):
        """
        获取指定区域的仓库库存信息。

        通过 OCR 识别仓库中各作物的数量，同时设置实例属性方便后续访问。

        Args:
            category (str): 区域类型，'farm'、'orchard' 或 'nursery'。

        Returns:
            dict: 作物名称到数量的映射，如 {'wheat': 50, 'corn': 30}。
        """
        config = self.INVENTORY_CONFIG[category]
        self.warehouse_filter(config['filter'])
        image = self.device.screenshot()
        results = {}
        for item_config in config['items']:
            count = self.ocr_item_quantity(image, item_config['template'])
            results[item_config['name']] = count
            setattr(self, item_config['var_name'], count)
            logger.info(f"{item_config['name']}: {count}")
        return results

    def post_plant_check(self, category):
        """
        检查当前岗位正在种植的作物类型。

        通过模板匹配检测岗位详情页面中的作物图标，确定正在种植的作物。

        Args:
            category (str): 区域类型，'farm'、'orchard' 或 'nursery'。

        Returns:
            str 或 None: 正在种植的作物名称，未检测到则返回 None。
        """
        config = self.INVENTORY_CONFIG[category]
        for item in config['items']:
            if self.appear(item['post_action']):
                return item['name']
        return None

    def decided_lists(self, post_button, post_id, category, time_var_name):
        """
        检查指定岗位的状态并更新相关列表。

        打开岗位详情，判断岗位是已完成、正在工作还是空闲：
        - 已完成：清除作物信息和时间变量
        - 正在工作：记录作物类型、读取剩余完成时间，从补种列表中移除
        - 空闲：清除作物信息和时间变量

        Args:
            post_button (Button): 岗位按钮资源。
            post_id (str): 岗位标识，如 'ISLAND_FARM_POST1'。
            category (str): 区域类型，'farm'、'orchard' 或 'nursery'。
            time_var_name (str): 对应的时间变量名，用于存储完成时间。
        """
        self.post_close()
        self.post_open(post_button)
        self.device.screenshot()
        if self.appear(ISLAND_WORK_COMPLETE, offset=1):
            self.posts[post_id]['crop'] = None
            setattr(self, time_var_name, None)
        elif self.appear(ISLAND_WORKING):
            product_name = self.post_plant_check(category)
            if product_name in self.to_plant_lists[category]:
                self.to_plant_lists[category].remove(product_name)
            self.posts[post_id]['crop'] = product_name
            time_work = Duration(ISLAND_WORKING_TIME)
            time_value = time_work.ocr(self.device.image)
            finish_time = current_time() + time_value
            setattr(self, time_var_name, finish_time)
            post_index = int(post_id[-1]) - 1
            if category in self.time_vars and post_index < len(self.time_vars[category]):
                self.time_vars[category][post_index] = finish_time
        elif self.appear(ISLAND_POST_SELECT, offset=1):
            self.posts[post_id]['crop'] = None
            setattr(self, time_var_name, None)
        self.post_get_and_close()

    def get_orchard_character_filter(self, product):
        """根据小天城橡胶树开关生成果园派遣角色优先级。"""
        character_filter = self.worker_filters.get('orchard', "WorkerJuu")
        characters = self.parse_character_filter(character_filter)
        if not self.config.IslandOrchard_AmagiChanRubber:
            return characters

        characters = [
            character
            for character in characters
            if character != "Amagi_chan"
        ]
        if product == 'rubber':
            return ["Amagi_chan", *characters]
        return characters

    def post_plant(self, post_button, product, category, time_var_name):
        """
        在指定岗位上执行播种操作。

        完整流程：打开岗位 -> 选择产品 -> 选择角色派遣 -> 确认订单 -> 记录完成时间。
        种子不足时自动从商店购买补充。

        Args:
            post_button (Button): 岗位按钮资源。
            product (str): 要种植的作物名称，如 'wheat'、'apple'。
            category (str): 区域类型，'farm'、'orchard' 或 'nursery'。
            time_var_name (str): 对应的时间变量名，用于存储完成时间。

        Returns:
            bool: 播种是否成功。
        """
        self.post_close()
        self.post_open(post_button)
        self.device.screenshot()
        time_work = Duration(ISLAND_WORKING_TIME)
        selection = self.name_to_config[product]['selection']
        selection_check = self.name_to_config[product]['selection_check']
        seed_config = self.name_to_config[product]
        # 4x1 作物（秋月梨/柿子）：每次派遣只消耗 4 颗种子，与果园其他作物每单
        # 至少 4x4=16 颗不同，种子补货目标按 4 颗/单计算
        if seed_config.get('batch_4x1'):
            logger.info(
                f"[岛屿-农田] {product} 为 4x1 作物：每次派遣仅消耗 "
                f"{seed_config['seed_number']} 颗种子（果园其他作物每单至少 16 颗）"
            )
        for _ in self.loop(timeout=120, skip_first=False):
            if self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                character_filter = self.worker_filters.get(category, "WorkerJuu")
                if category == 'orchard':
                    character_filter = self.get_orchard_character_filter(product)
                if self.select_character(character_list=character_filter):
                    if not self.confirm_selected_character(f"{product}种植派遣"):
                        self.back_to_postmanage_from_dispatch()
                        return False
                else:
                    logger.warning(f"[岛屿-农田] {product}种植派遣无可用角色: {character_filter}")
                    self.back_to_postmanage_from_dispatch()
                    return False
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                if self.select_product(selection, selection_check):
                    if self.ensure_select_product_material(
                            item_button=seed_config['shop'],
                            required_quantity=seed_config['seed_number'],
                            shop_check=ISLAND_SHOP_SEED_TAB_CHECK,
                            item_name=f"{product}种子",
                    ):
                        continue
                    self.device.sleep(0.3)
                    if not self.confirm_post_add_order(f"{product}种植派遣"):
                        self.back_to_postmanage_from_dispatch()
                        return False
                    break
                else:
                    return self._handle_select_product_failure(product)
        else:
            logger.warning(f"[岛屿-农田] {product}种植派遣超时")
            self.back_to_postmanage_from_dispatch()
            return False

        self.post_open(post_button)
        self.device.sleep(0.5)
        self.device.screenshot()
        time_value = time_work.ocr(self.device.image)
        finish_time = current_time() + time_value
        setattr(self, time_var_name, finish_time)

        # 更新岗位作物信息
        for post_id, post_info in self.posts.items():
            if post_info['button'] == post_button:
                post_info['crop'] = product
                break

        # 关闭详情弹窗，防止后续操作被弹窗遮挡
        self.post_close()
        return True

    def run(self):
        self.island_error = False
        self.ui_ensure(page_island)
        self.check_inventory_and_prepare_lists()

        logger.info("[岛屿-农田] \n当前库存统计:")
        logger.info(f"[岛屿-农田] 农场库存: {self.inventory_counts['farm']}")
        logger.info(f"[岛屿-农田] 果园库存: {self.inventory_counts['orchard']}")
        logger.info(f"[岛屿-农田] 苗圃库存: {self.inventory_counts['nursery']}")

        self.goto_postmanage()
        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_close()
        self.post_manage_swipe(0)

        self.time_vars = {
            'farm': [None] * self.farm_positions,
            'orchard': [None] * self.orchard_positions,
            'nursery': [None] * self.nursery_positions
        }

        post_button_mapping = {
            'farm': [self.posts['ISLAND_FARM_POST1']['button'],
                     self.posts['ISLAND_FARM_POST2']['button'],
                     self.posts['ISLAND_FARM_POST3']['button'],
                     self.posts['ISLAND_FARM_POST4']['button']],
            'orchard': [self.posts['ISLAND_ORCHARD_POST1']['button'],
                        self.posts['ISLAND_ORCHARD_POST2']['button'],
                        self.posts['ISLAND_ORCHARD_POST3']['button'],
                        self.posts['ISLAND_ORCHARD_POST4']['button']],
            'nursery': [self.posts['ISLAND_NURSERY_POST1']['button'],
                        self.posts['ISLAND_NURSERY_POST2']['button']]
        }

        post_buttons = {
            'farm': post_button_mapping['farm'][:self.farm_positions],
            'orchard': post_button_mapping['orchard'][:self.orchard_positions],
            'nursery': post_button_mapping['nursery'][:self.nursery_positions]
        }

        post_id_to_button = {}
        for category in ['farm', 'orchard', 'nursery']:
            positions_count = getattr(self, f'{category}_positions')
            for i, button in enumerate(post_buttons[category]):
                post_id = f'ISLAND_{category.upper()}_POST{i + 1}'
                post_id_to_button[post_id] = button

        idle_posts = {'farm': [], 'orchard': [], 'nursery': []}

        # 先遍历农田和果园
        for category in ['farm', 'orchard']:
            positions = len(self.time_vars[category])
            for i in range(positions):
                post_id = f'ISLAND_{category.upper()}_POST{i + 1}'
                time_var_name = f'{category}_time_{i}'

                button = post_id_to_button[post_id]
                self.decided_lists(button, post_id, category, time_var_name)

                if self.posts[post_id]['crop'] is None:
                    idle_posts[category].append({
                        'post_id': post_id,
                        'button': button,
                        'index': i,
                        'time_var_name': time_var_name
                    })

        # 滑动到苗圃位置
        self.device.sleep(1)
        self.post_manage_up_swipe(450)
        self.device.sleep(0.5)  # 等待滑动动画完成

        # 然后遍历苗圃
        category = 'nursery'
        positions = len(self.time_vars[category])
        for i in range(positions):
            post_id = f'ISLAND_{category.upper()}_POST{i + 1}'
            time_var_name = f'{category}_time_{i}'

            button = post_id_to_button[post_id]
            self.decided_lists(button, post_id, category, time_var_name)

            if self.posts[post_id]['crop'] is None:
                idle_posts[category].append({
                    'post_id': post_id,
                    'button': button,
                    'index': i,
                    'time_var_name': time_var_name
                })

        logger.info(f"[岛屿-农田] \n空闲岗位统计:")
        for category in ['farm', 'orchard', 'nursery']:
            logger.info(f"[岛屿-农田] {category}: {len(idle_posts[category])}个空闲岗位")

        all_plants_to_plant = {'farm': [], 'orchard': [], 'nursery': []}

        for category in ['farm', 'orchard', 'nursery']:
            if not idle_posts[category]:
                continue

            idle_count = len(idle_posts[category])
            plant_config = self.plant_config[category]
            to_plant_list = self.to_plant_lists[category]
            default_crop = plant_config['default_crop']
            default_count = plant_config['plant_default']

            already_planted_default = 0
            positions_count = getattr(self, f'{category}_positions')
            for i in range(positions_count):
                post_id = f'ISLAND_{category.upper()}_POST{i + 1}'
                if self.posts[post_id]['crop'] == default_crop:
                    already_planted_default += 1

            logger.info(f"[岛屿-农田] {category}已有{already_planted_default}个岗位种植了{default_crop}，配置要求{default_count}个")

            need_default = max(0, default_count - already_planted_default)

            if to_plant_list:
                # 未达标作物：按库存升序轮转分配所有空闲岗位（如 A B C A B ...）
                for i in range(idle_count):
                    all_plants_to_plant[category].append(to_plant_list[i % len(to_plant_list)])
            else:
                # 所有未达标作物都已安排后才种植默认作物
                if idle_count > 0 and need_default > 0:
                    actual_default = min(idle_count, need_default)
                    for _ in range(actual_default):
                        all_plants_to_plant[category].append(default_crop)

            if all_plants_to_plant[category]:
                logger.info(f"[岛屿-农田] \n{category}需要种植的作物: {all_plants_to_plant[category]}")

        need_to_plant = any(all_plants_to_plant.values())

        if need_to_plant:
            self.post_manage_swipe(0)
            self.device.sleep(1)

            # 先处理农田和果园的播种，种子不足时在产品选择页即时补买。
            for category in ['farm', 'orchard']:
                if not idle_posts[category]:
                    continue

                idle_posts_list = idle_posts[category]
                crops_to_plant = all_plants_to_plant[category]

                for i, post_info in enumerate(idle_posts_list):
                    if i >= len(crops_to_plant):
                        logger.info(f"[岛屿-农田] 跳过{category}岗位{post_info['post_id']}: 没有需要种植的作物")
                        continue

                    crop_to_plant = crops_to_plant[i]
                    logger.info(f"[岛屿-农田] 尝试播种{category}岗位{post_info['post_id']}: {crop_to_plant}")

                    success = self.post_plant(post_info['button'], crop_to_plant, category, post_info['time_var_name'])

                    if success:
                        logger.info(f"[岛屿-农田] 播种{category}岗位{post_info['post_id']}成功: {crop_to_plant}")
                        if crop_to_plant in self.to_plant_lists[category]:
                            self.to_plant_lists[category].remove(crop_to_plant)

            # 然后处理苗圃的播种
            category = 'nursery'
            if idle_posts[category]:
                self.post_manage_up_swipe(450)
                self.device.sleep(0.5)
                idle_posts_list = idle_posts[category]
                crops_to_plant = all_plants_to_plant[category]

                for i, post_info in enumerate(idle_posts_list):
                    if i >= len(crops_to_plant):
                        logger.info(f"[岛屿-农田] 跳过{category}岗位{post_info['post_id']}: 没有需要种植的作物")
                        continue

                    crop_to_plant = crops_to_plant[i]
                    logger.info(f"[岛屿-农田] 尝试播种{category}岗位{post_info['post_id']}: {crop_to_plant}")

                    success = self.post_plant(post_info['button'], crop_to_plant, category, post_info['time_var_name'])

                    if success:
                        logger.info(f"[岛屿-农田] 播种{category}岗位{post_info['post_id']}成功: {crop_to_plant}")
                        if crop_to_plant in self.to_plant_lists[category]:
                            self.to_plant_lists[category].remove(crop_to_plant)

        logger.info("[岛屿-农田] \n农田管理完成！")
        future_finish = []

        for category in ['farm', 'orchard', 'nursery']:
            positions = len(self.time_vars[category])
            for i in range(positions):
                time_var = self.time_vars[category][i]
                if time_var is not None:
                    future_finish.append(time_var)

        six_hours_later = current_time() + timedelta(hours=6)
        future_finish.append(six_hours_later)
        future_finish.sort()
        self.config.task_delay(target=future_finish)
        logger.info(f'[岛屿-农田] 下次运行时间: {future_finish[0]}')
        if self.island_error:
            from module.exception import GameBugError
            raise GameBugError("检测到岛屿ERROR1，需要重启")
    def test(self):
        self.warehouse_inventory('farm')
if __name__ == "__main__":
    az = IslandFarm('alas', task='Alas')
    az.device.screenshot()
    az.test()

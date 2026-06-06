from module.island_farm.assets import *
from module.island.island import *
from datetime import datetime
from module.handler.login import LoginHandler
from module.island.warehouse import *
from module.logger import logger


class IslandFarm(Island, WarehouseOCR, LoginHandler):
    def __init__(self, *args, **kwargs):
        Island.__init__(self, *args, **kwargs)
        WarehouseOCR.__init__(self)
        
        # === 初始化全局季节配置 ===
        from module.island.island_season import get_global_season_config
        self.season_config = get_global_season_config(self.config)
        if self.season_config.is_seasonal_enabled:
            logger.info(f"当前季节: {self.season_config.season_name}，季节限定作物将根据配置启用")

        self.farm_positions = self.config.IslandFarm_Positions
        self.orchard_positions = self.config.IslandOrchard_Positions
        self.nursery_positions = self.config.IslandNursery_Positions
        self.farm_threshold = self.config.IslandFarm_MinFarm
        self.orchard_threshold = self.config.IslandOrchard_MinOrchard
        self.nursery_threshold = self.config.IslandNursery_MinNursery

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
        """检查库存并准备需要补种的列表"""
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
                # === 季节限定：不在当季的作物不列入补种计划 ===
                if category == 'nursery' and hasattr(self, 'season_config'):
                    if not self._is_nursery_crop_in_season(item_name):
                        logger.info(f"跳过非当季苗圃作物: {item_name}")
                        continue
                if count < threshold:
                    self.to_plant_lists[category].append(item_name)

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
        """获取仓库库存信息"""
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
        config = self.INVENTORY_CONFIG[category]
        for item in config['items']:
            if self.appear(item['post_action']):
                return item['name']
        return None

    def decided_lists(self, post_button, post_id, category, time_var_name):
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
            finish_time = datetime.now() + time_value
            setattr(self, time_var_name, finish_time)
            post_index = int(post_id[-1]) - 1
            if category in self.time_vars and post_index < len(self.time_vars[category]):
                self.time_vars[category][post_index] = finish_time
        elif self.appear(ISLAND_POST_SELECT, offset=1):
            self.posts[post_id]['crop'] = None
            setattr(self, time_var_name, None)
        self.post_get_and_close()

    def post_plant(self, post_button, product, category, time_var_name):
        self.post_close()
        self.post_open(post_button)
        self.device.screenshot()
        time_work = Duration(ISLAND_WORKING_TIME)
        selection = self.name_to_config[product]['selection']
        selection_check = self.name_to_config[product]['selection_check']
        while 1:
            self.device.screenshot()
            if self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                if product == 'rubber' and self.config.IslandOrchard_AmagiChanRubber:
                    if self.select_character(character_list="Amagi_chan"):
                        self.device.click(SELECT_UI_CONFIRM)
                else:
                    if self.select_character():
                        self.device.sleep(0.5)
                        self.device.click(SELECT_UI_CONFIRM)
                        self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                if self.select_product(selection, selection_check):
                    self.device.sleep(0.3)
                    self.device.click(POST_MAX)
                    self.device.sleep(0.3)
                    self.device.click(POST_ADD_ORDER)
                    self.device.sleep(0.5)
                    break
        self.post_open(post_button)
        self.device.sleep(0.5)
        self.device.screenshot()
        time_value = time_work.ocr(self.device.image)
        finish_time = datetime.now() + time_value
        setattr(self, time_var_name, finish_time)

        # 更新岗位作物信息
        for post_id, post_info in self.posts.items():
            if post_info['button'] == post_button:
                post_info['crop'] = product
                break
        return True

    def buy_seeds(self, seed, category):
        category_map = {
            'farm': (SHOP_FARM_CHECK, SHOP_FARM),
            'orchard': (SHOP_ORCHARD_CHECK, SHOP_ORCHARD),
            'nursery': (SHOP_NURSERY_CHECK, SHOP_NURSERY)
        }
        check_const, click_const = category_map[category]
        seed_config = self.name_to_config[seed]
        target = seed_config['seed_number']
        seed_button = seed_config['shop']
        while 1:
            self.device.screenshot()
            if self.appear(check_const):
                break
            if self.appear_then_click(click_const, interval=0.3):
                pass
        while 1:
            self.device.screenshot()
            if self.appear(ISLAND_SHOPPING_CHECK):
                break
            if self.appear_then_click(seed_button, interval=1.2):
                pass
        if self.appear(ISLAND_SHOPPING_CHECK):
            self.set_buy_number(target)
        while 1:
            self.device.screenshot()
            if self.appear(ISLAND_SHOP_CHECK, offset=1):
                break
            if self.appear_then_click(ISLAND_SHOP_CONFIRM):
                self.device.sleep(0.5)
                self.device.click(ISLAND_SHOP_CONFIRM)
                self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SHOP_GET):
                self.device.click(ISLAND_SHOP_CONFIRM)
                continue
        if self.appear(ISLAND_SHOP_GET):
            self.device.click(ISLAND_SHOP_CONFIRM)

    def run(self):
        self.island_error = False
        self.check_inventory_and_prepare_lists()

        logger.info("\n当前库存统计:")
        logger.info(f"农场库存: {self.inventory_counts['farm']}")
        logger.info(f"果园库存: {self.inventory_counts['orchard']}")
        logger.info(f"苗圃库存: {self.inventory_counts['nursery']}")

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

        logger.info(f"\n空闲岗位统计:")
        for category in ['farm', 'orchard', 'nursery']:
            logger.info(f"{category}: {len(idle_posts[category])}个空闲岗位")

        all_plants_to_buy = {'farm': [], 'orchard': [], 'nursery': []}

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

            logger.info(f"{category}已有{already_planted_default}个岗位种植了{default_crop}，配置要求{default_count}个")

            need_default = max(0, default_count - already_planted_default)

            num_from_list = min(len(to_plant_list), idle_count)

            for i in range(num_from_list):
                crop_name = to_plant_list[i]
                all_plants_to_buy[category].append(crop_name)

            remaining_idle = idle_count - num_from_list

            if remaining_idle > 0 and need_default > 0:
                actual_default = min(remaining_idle, need_default)
                for _ in range(actual_default):
                    all_plants_to_buy[category].append(default_crop)

            if all_plants_to_buy[category]:
                logger.info(f"\n{category}需要购买的作物: {all_plants_to_buy[category]}")

        need_to_buy_seeds = any(all_plants_to_buy.values())

        if need_to_buy_seeds:
            self.ui_goto(page_island_shop, get_ship=False)
            self.device.sleep(0.5)
            self.device.click(ISLAND_SHOP_GOTO_SEED_SHOP)
            while 1:
                self.device.screenshot()
                if self.appear(ISLAND_SEED_SHOP_CHECK):
                    break
                self.device.click(ISLAND_SHOP_GOTO_SEED_SHOP)
                self.device.sleep(0.5)

            for category in ['farm', 'orchard', 'nursery']:
                if not all_plants_to_buy[category]:
                    continue

                crop_counts = {}
                for crop_name in all_plants_to_buy[category]:
                    crop_counts[crop_name] = crop_counts.get(crop_name, 0) + 1

                category_map = {
                    'farm': (SHOP_FARM_CHECK, SHOP_FARM),
                    'orchard': (SHOP_ORCHARD_CHECK, SHOP_ORCHARD),
                    'nursery': (SHOP_NURSERY_CHECK, SHOP_NURSERY)
                }
                check_const, click_const = category_map[category]

                while 1:
                    self.device.screenshot()
                    if self.appear(check_const):
                        break
                    if self.appear_then_click(click_const, interval=0.3):
                        pass

                for crop, count in crop_counts.items():
                    logger.info(f"购买{category}类别的{crop}种子，{count}份")
                    for _ in range(count):
                        self.buy_seeds(crop, category)
            while 1:
                self.device.screenshot()
                if self.appear(ISLAND_CHECK):
                    break
                self.device.click(ISLAND_BACK)
                self.device.sleep(0.5)

            self.goto_management()
            self.ui_goto(page_island_postmanage, get_ship=False)
            self.post_manage_mode(POST_MANAGE_PRODUCTION)
            self.post_close()
            self.device.sleep(1)
            self.post_manage_down_swipe(450)
            self.device.sleep(1)
            self.post_manage_down_swipe(450)
            self.device.sleep(1)
            # 先处理农田和果园的播种
            for category in ['farm', 'orchard']:
                if not idle_posts[category]:
                    continue

                idle_posts_list = idle_posts[category]
                crops_to_plant = all_plants_to_buy[category]

                for i, post_info in enumerate(idle_posts_list):
                    if i >= len(crops_to_plant):
                        logger.info(f"跳过{category}岗位{post_info['post_id']}: 没有需要种植的作物")
                        continue

                    crop_to_plant = crops_to_plant[i]
                    logger.info(f"尝试播种{category}岗位{post_info['post_id']}: {crop_to_plant}")

                    success = self.post_plant(post_info['button'], crop_to_plant, category, post_info['time_var_name'])

                    if success:
                        logger.info(f"播种{category}岗位{post_info['post_id']}成功: {crop_to_plant}")
                        if crop_to_plant in self.to_plant_lists[category]:
                            self.to_plant_lists[category].remove(crop_to_plant)
            self.device.sleep(1)
            self.post_manage_down_swipe(450)
            self.device.sleep(1)
            self.post_manage_down_swipe(450)
            self.device.sleep(1)
            # 然后处理苗圃的播种
            category = 'nursery'
            if idle_posts[category]:
                self.device.sleep(1)
                self.post_manage_up_swipe(450)
                self.device.sleep(0.5)
                idle_posts_list = idle_posts[category]
                crops_to_plant = all_plants_to_buy[category]

                for i, post_info in enumerate(idle_posts_list):
                    if i >= len(crops_to_plant):
                        logger.info(f"跳过{category}岗位{post_info['post_id']}: 没有需要种植的作物")
                        continue

                    crop_to_plant = crops_to_plant[i]
                    logger.info(f"尝试播种{category}岗位{post_info['post_id']}: {crop_to_plant}")

                    success = self.post_plant(post_info['button'], crop_to_plant, category, post_info['time_var_name'])

                    if success:
                        logger.info(f"播种{category}岗位{post_info['post_id']}成功: {crop_to_plant}")
                        if crop_to_plant in self.to_plant_lists[category]:
                            self.to_plant_lists[category].remove(crop_to_plant)

        logger.info("\n农田管理完成！")
        future_finish = []

        for category in ['farm', 'orchard', 'nursery']:
            positions = len(self.time_vars[category])
            for i in range(positions):
                time_var = self.time_vars[category][i]
                if time_var is not None:
                    future_finish.append(time_var)

        six_hours_later = datetime.now() + timedelta(hours=6)
        future_finish.append(six_hours_later)
        future_finish.sort()
        self.config.task_delay(target=future_finish)
        logger.info(f'下次运行时间: {future_finish[0]}')
        if self.island_error:
            from module.exception import GameBugError
            raise GameBugError("检测到岛屿ERROR1，需要重启")
    def test(self):
        self.warehouse_inventory('farm')
if __name__ == "__main__":
    az = IslandFarm('alas', task='Alas')
    az.device.screenshot()
    az.test()
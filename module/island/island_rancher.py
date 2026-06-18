from module.island_farm.assets import *
from module.island_rancher.assets import *
from module.island.island import *
from datetime import datetime
from module.handler.login import LoginHandler
from module.island.warehouse import *
from module.logger import logger


class IslandRancher(Island, WarehouseOCR, LoginHandler):
    def __init__(self, *args, **kwargs):
        Island.__init__(self, *args, **kwargs)
        WarehouseOCR.__init__(self)
        self.ranch_chicken_threshold = self.config.IslandRancher_MinChicken
        self.ranch_pork_threshold = self.config.IslandRancher_MinPork
        self.island_shop_grid = ButtonGrid(
            origin=(254, 223),
            delta=(163, 167),
            button_shape=(87, 86),
            grid_shape=(6, 1),
            name="ISLAND_SHOP_GRID"
        )
        self.INVENTORY_CONFIG = {
            'farm': {
                'filter': 'farm',
                'items': [
                    {'name': 'wheat', 'template': TEMPLATE_WHEAT, 'var_name': 'wheat',
                     'category': 'farm'},
                    {'name': 'corn', 'template': TEMPLATE_CORN, 'var_name': 'corn',
                     'category': 'farm'},
                    {'name': 'pasture', 'template': TEMPLATE_PASTURE, 'var_name': 'pasture',
                     'category': 'farm'},
                ]
            },
            'mill': {
                'filter': 'processed',
                'items': [
                    {'name': 'chicken_feed', 'template': TEMPLATE_CHICKEN_FEED, 'var_name': 'chicken_feed',
                     'category': 'mill', 'number': 11, 'mill': MILL_CHICKEN_FEED, 'required_material': 'wheat'},
                    {'name': 'pig_feed', 'template': TEMPLATE_PIG_FEED, 'var_name': 'pig_feed',
                     'category': 'mill', 'number': 11, 'mill': MILL_PIG_FEED, 'required_material': 'corn'},
                    {'name': 'cattle_feed', 'template': TEMPLATE_CATTLE_FEED, 'var_name': 'cattle_feed',
                     'category': 'mill', 'number': 11, 'mill': MILL_CATTLE_FEED, 'required_material': 'pasture'},
                    {'name': 'sheep_feed', 'template': TEMPLATE_SHEEP_FEED, 'var_name': 'sheep_feed',
                     'category': 'mill', 'number': 11, 'mill': MILL_SHEEP_FEED, 'required_material': 'pasture'},
                    {'name': 'wheat_flour', 'template': TEMPLATE_WHEAT_FLOUR, 'var_name': 'wheat_flour',
                     'category': 'mill', 'number': 55, 'mill': MILL_WHEAT_FLOUR, 'required_material': 'wheat'},
                ]
            },
            'ranch': {
                'filter': 'ranch',
                'items': [
                    {'name': 'chicken', 'template': TEMPLATE_CHICKEN, 'var_name': 'chicken',
                     'category': 'ranch', 'threshold': self.config.IslandRancher_MinChicken},
                    {'name': 'pork', 'template': TEMPLATE_PORK, 'var_name': 'pork',
                     'category': 'ranch', 'threshold': self.config.IslandRancher_MinPork},
                ]
            }
        }

        # 定义所有岗位的ID到按钮的映射
        self.all_posts = {
            # 牧场岗位
            'ISLAND_RANCH_POST1': ISLAND_RANCH_POST1,
            'ISLAND_RANCH_POST2': ISLAND_RANCH_POST2,
            'ISLAND_RANCH_POST3': ISLAND_RANCH_POST3,
            'ISLAND_RANCH_POST4': ISLAND_RANCH_POST4,
            # 渔场岗位
            'ISLAND_FISHERY_POST1': ISLAND_FISHERY_POST1,
            'ISLAND_FISHERY_POST2': ISLAND_FISHERY_POST2,
            'ISLAND_FISHERY_POST3': ISLAND_FISHERY_POST3
        }

        # 按类型分组（用于某些特定逻辑）
        self.posts_ranch = {
            'ISLAND_RANCH_POST1': ISLAND_RANCH_POST1,
            'ISLAND_RANCH_POST2': ISLAND_RANCH_POST2,
            'ISLAND_RANCH_POST3': ISLAND_RANCH_POST3,
            'ISLAND_RANCH_POST4': ISLAND_RANCH_POST4
        }
        self.posts_fishery = {
            'ISLAND_FISHERY_POST1': ISLAND_FISHERY_POST1,
            'ISLAND_FISHERY_POST2': ISLAND_FISHERY_POST2,
            'ISLAND_FISHERY_POST3': ISLAND_FISHERY_POST3
        }

        self.name_to_config = {}
        for category in self.INVENTORY_CONFIG.values():
            for item in category.get('items', []):
                self.name_to_config[item['name']] = item
        self.inventory_counts = {
            'mill': {},
            'ranch': {},
            'farm': {}
        }

    def ranch_post_get_and_add(self, is_fish=False, character='WorkerJuu'):
        while 1:
            self.device.screenshot()
            if self.appear(ERROR1, offset=30):
                self.device.click(POST_CLOSE)
                self.island_error = True
                break
            if self.appear(ISLAND_GET, offset=1):
                self.device.click(ISLAND_POST_SAFE_AREA)
                continue
            if self.appear_then_click(POST_GET, offset=(50, 0)):
                self.device.sleep(0.3)
                self.device.click(ISLAND_POST_SAFE_AREA)
                self.device.sleep(0.3)
                self.device.click(ISLAND_POST_SAFE_AREA)
                self.device.sleep(0.3)
                continue
            if self.appear_then_click(POST_ADD):
                continue
            if self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                if self.select_character(character):
                    self.device.sleep(0.5)
                    self.appear_then_click(SELECT_UI_CONFIRM)
                    self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                if is_fish:
                    self.select_product(SELECT_CRAY, SELECT_CRAY_CHECK)
                    image = self.device.screenshot()
                    area = (493, 597, 621, 643)
                    color = get_color(image, area)
                    if color_similar(color, (153, 156, 156), 80):
                        logger.info(f"鱼苗不足")
                        while 1:
                            self.device.click(ISLAND_SELECT_SEED)
                            self.device.sleep(0.5)
                            self.device.screenshot()
                            if self.appear_then_click(ISLAND_SELECT_GOTO_BUY_SEED):
                                continue
                            if self.appear(ISLAND_FISH_FRY_SHOP_CHECK):
                                self.device.click(ISLAND_FISH_FRY_SHOP_OTHER)
                                continue
                            if self.appear(ISLAND_FISH_FRY_SHOP_OTHER_CHECK):
                                break
                            self.device.sleep(0.5)
                        screenshot = self.device.screenshot()
                        template = TEMPLATE_CRAY
                        for _, _, button in self.island_shop_grid.generate():
                            cell_image = crop(screenshot, button.area)
                            if template.match(cell_image, similarity=0.85):
                                self.device.click(button)
                                break
                        self.device.sleep(0.5)
                        self.set_buy_number(11)
                        while 1:
                            self.device.screenshot()
                            if self.appear(ISLAND_FISH_FRY_SHOP_OTHER_CHECK, offset=1):
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
                        self.device.sleep(0.5)
                        self.device.click(ISLAND_SHOP_GOTO_ISLAND)
                        self.device.sleep(0.5)
                if self.appear_then_click(POST_MAX):
                    self.device.sleep(0.3)
                    self.device.click(POST_ADD_ORDER)
                    self.device.sleep(0.5)
                continue
            if (
                    self.appear(ISLAND_POST_CHECK, offset=1)
                    and not self.appear(POST_GET, offset=(50, 0))
                    and not self.appear(POST_ADD)
                    and not self.appear(ISLAND_POST_SELECT, offset=1)
            ):
                self.device.click(POST_CLOSE)
                break
            if (
                    self.appear(ISLAND_POSTMANAGE_CHECK, offset=1)
                    and not self.appear(ISLAND_POST_CHECK)
            ):
                break

    def post_mode_check(self, post_id):
        """检查岗位是否使用特定角色配置"""
        if post_id == 'ISLAND_RANCH_POST3':
            config_str = self.config.IslandRancher_RancherFilter
        elif post_id in ['ISLAND_FISHERY_POST1', 'ISLAND_FISHERY_POST2', 'ISLAND_FISHERY_POST3']:
            config_str = self.config.IslandFishery_RancherFilter
        else:
            return False
        return not config_str.strip() == 'WorkerJuu'

    def ranch_post(self, post_id, time_var_name):
        """执行牧场或渔场岗位任务"""
        # 从所有岗位字典中获取按钮
        if post_id not in self.all_posts:
            logger.error(f"未知的岗位ID: {post_id}")
            return

        post_button = self.all_posts[post_id]

        # 判断是否是渔场
        is_fish = post_id in self.posts_fishery

        # 获取对应的配置
        if post_id == 'ISLAND_RANCH_POST3':
            config_str = self.config.IslandRancher_RancherFilter
        elif is_fish:
            config_str = self.config.IslandFishery_RancherFilter
        else:
            config_str = 'WorkerJuu'

        self.post_close()
        self.post_open(post_button)
        self.device.sleep(0.5)
        self.device.screenshot()
        if self.appear(ISLAND_WORKING) and self.post_mode_check(post_id):
            time_work = Duration(ISLAND_WORKING_TIME)
            time_value = time_work.ocr(self.device.image)
            setattr(self, time_var_name, datetime.now() + time_value)
        else:
            self.ranch_post_get_and_add(is_fish, config_str)
            self.post_open(post_button)
            self.device.sleep(0.5)
            self.device.screenshot()
            time_work = Duration(ISLAND_WORKING_TIME)
            time_value = time_work.ocr(self.device.image)
            setattr(self, time_var_name, datetime.now() + time_value)
        self.post_close()

    def mill_process(self, mill_item):
        mill_config = self.name_to_config[mill_item]
        mill_button = mill_config['mill']
        target = mill_config['number']
        required_material = mill_config['required_material']
        if required_material in self.inventory_counts['farm']:
            if self.inventory_counts['farm'][required_material] < 330:
                logger.info(f"原材料{required_material}不足，无法加工{mill_item}")
                return False
        while True:
            self.device.screenshot()
            if self.appear(ISLAND_SHOPPING_CHECK):
                break
            if self.appear_then_click(mill_button, interval=0.3):
                pass
        if self.appear(ISLAND_SHOPPING_CHECK):
            self.set_buy_number(target)
        while True:
            self.device.screenshot()
            if self.appear(ISLAND_MILL_CHECK, offset=1):
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
        if required_material in self.inventory_counts['farm']:
            self.inventory_counts['farm'][required_material] -= 330
            logger.info(f"扣除原材料{required_material} 330单位")
        self.inventory_counts['mill'][mill_item] = self.inventory_counts['mill'].get(mill_item, 0) + target * 10
        logger.info(f"加工完成：{mill_item} +{target}")
        return True

    def check_mill_needs(self):
        mill_needs = []
        wheat_flour_count = self.inventory_counts['mill'].get('wheat_flour', 0)
        wheat_count = self.inventory_counts['farm'].get('wheat', 0)

        if wheat_flour_count < 150 and wheat_count > 330:
            mill_needs.append('wheat_flour')
            logger.info("需要加工面粉")

        chicken_count = self.inventory_counts['ranch'].get('chicken', 0)
        chicken_feed_count = self.inventory_counts['mill'].get('chicken_feed', 0)

        if (chicken_count < self.config.IslandRancher_MinChicken and
                wheat_count > 330 and
                chicken_feed_count < 50 and
                'wheat_flour' not in mill_needs):
            mill_needs.append('chicken_feed')
            logger.info("需要加工鸡饲料")

        pork_count = self.inventory_counts['ranch'].get('pork', 0)
        pig_feed_count = self.inventory_counts['mill'].get('pig_feed', 0)
        corn_count = self.inventory_counts['farm'].get('corn', 0)

        if (pork_count < self.config.IslandRancher_MinPork and
                corn_count > 330 and
                pig_feed_count < 50):
            mill_needs.append('pig_feed')
            logger.info("需要加工猪饲料")

        cattle_feed_count = self.inventory_counts['mill'].get('cattle_feed', 0)
        pasture_count = self.inventory_counts['farm'].get('pasture', 0)

        if cattle_feed_count < 50 and pasture_count > 330:
            mill_needs.append('cattle_feed')
            logger.info("需要加工牛饲料")

        sheep_feed_count = self.inventory_counts['mill'].get('sheep_feed', 0)

        if sheep_feed_count < 50 and pasture_count > 330:
            mill_needs.append('sheep_feed')
            logger.info("需要加工羊饲料")
        return mill_needs

    def warehouse_mill_ranch(self):
        self.warehouse_filter('processed')
        image = self.device.screenshot()
        self.inventory_counts['mill'] = {}
        for item_config in self.INVENTORY_CONFIG['mill']['items']:
            count = self.ocr_item_quantity(image, item_config['template'])
            self.inventory_counts['mill'][item_config['name']] = count
            logger.info(f"{item_config['name']}: {count}")

        self.warehouse_filter('ranch')
        image = self.device.screenshot()
        self.inventory_counts['ranch'] = {}
        for item_config in self.INVENTORY_CONFIG['ranch']['items']:
            count = self.ocr_item_quantity(image, item_config['template'])
            self.inventory_counts['ranch'][item_config['name']] = count
            logger.info(f"{item_config['name']}: {count}")

        self.warehouse_filter('farm')
        image = self.device.screenshot()
        self.inventory_counts['farm'] = {}
        for item_config in self.INVENTORY_CONFIG['farm']['items']:
            count = self.ocr_item_quantity(image, item_config['template'])
            self.inventory_counts['farm'][item_config['name']] = count
            logger.info(f"{item_config['name']}: {count}")

    def check_ranch_needs(self):
        ranch_needs = []

        chicken_count = self.inventory_counts['ranch'].get('chicken', 0)
        chicken_feed_count = self.inventory_counts['mill'].get('chicken_feed', 0)

        if chicken_count < self.ranch_chicken_threshold and chicken_feed_count >= 50:
            ranch_needs.append('ISLAND_RANCH_POST1')
            logger.info("需要执行养鸡任务")

        pork_count = self.inventory_counts['ranch'].get('pork', 0)
        pig_feed_count = self.inventory_counts['mill'].get('pig_feed', 0)

        if pork_count < self.ranch_pork_threshold and pig_feed_count >= 50:
            ranch_needs.append('ISLAND_RANCH_POST2')
            logger.info("需要执行养猪任务")

        cattle_feed_count = self.inventory_counts['mill'].get('cattle_feed', 0)
        if cattle_feed_count >= 50:
            ranch_needs.append('ISLAND_RANCH_POST3')
            logger.info("需要执行养牛任务")

        sheep_feed_count = self.inventory_counts['mill'].get('sheep_feed', 0)
        if sheep_feed_count >= 50:
            ranch_needs.append('ISLAND_RANCH_POST4')
            logger.info("需要执行养羊任务")
        return ranch_needs

    def run(self):
        self.island_error = False
        time_vars = ['time_ranch1', 'time_ranch2', 'time_ranch3', 'time_ranch4']
        all_configs = [
            ('ISLAND_RANCH_POST1', 'time_ranch1'),
            ('ISLAND_RANCH_POST2', 'time_ranch2'),
            ('ISLAND_RANCH_POST3', 'time_ranch3'),
            ('ISLAND_RANCH_POST4', 'time_ranch4'),
        ]
        for var in time_vars:
            setattr(self, var, None)
        self.warehouse_mill_ranch()
        logger.info("\n当前库存统计:")
        logger.info(f"农场库存: {self.inventory_counts['farm']}")
        logger.info(f"磨坊库存: {self.inventory_counts['mill']}")
        logger.info(f"牧场库存: {self.inventory_counts['ranch']}")

        logger.info("\n[3/5] 检查并执行磨坊加工...")
        mill_needs = self.check_mill_needs()
        if mill_needs:
            self.ui_goto(page_island_shop, get_ship=False)
            self.device.sleep(1)
            while 1:
                self.device.click(ISLAND_SHOP_GOTO_MILL)
                self.device.screenshot()
                if self.appear(MILL_WHEAT_FLOUR):
                    break
                self.device.sleep(0.5)

            logger.info(f"需要加工的项目: {mill_needs}")
            priority_order = ['wheat_flour', 'chicken_feed', 'pig_feed', 'cattle_feed', 'sheep_feed']

            processed_items = []
            for item in priority_order:
                if item in mill_needs:
                    # 重新检查库存是否足够
                    mill_config = self.name_to_config[item]
                    required_material = mill_config['required_material']

                    if required_material in self.inventory_counts['farm']:
                        current_material = self.inventory_counts['farm'][required_material]
                        if current_material < 330:
                            logger.info(f"原材料{required_material}不足 ({current_material}/330)，跳过加工{item}")
                            continue

                    success = self.mill_process(item)
                    if success:
                        processed_items.append(item)
                        # 立即更新内存中的库存计数
                        if required_material in self.inventory_counts['farm']:
                            self.inventory_counts['farm'][required_material] -= 330
                            logger.info(
                                f"更新库存: {required_material} = {self.inventory_counts['farm'][required_material]}")
                        logger.info(f"成功加工: {item}")
                    else:
                        logger.warning(f"加工失败: {item}")

            if processed_items:
                logger.info(f"本次运行共加工了 {len(processed_items)} 个项目: {processed_items}")
            else:
                logger.info("本次运行未成功加工任何项目")

            while 1:
                self.device.click(ISLAND_SHOP_GOTO_ISLAND)
                self.device.screenshot()
                if self.appear(ISLAND_CHECK):
                    break
                self.device.sleep(0.5)
        else:
            logger.info("没有磨坊加工需求")

        ranch_needs = self.check_ranch_needs()
        self.goto_postmanage()
        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_close()
        self.post_manage_swipe(0)

        all_needs = []

        # 添加牧场需求
        for post_id in ranch_needs:
            if post_id not in all_needs:
                all_needs.append(post_id)

        # 执行牧场岗位
        if all_needs:
            logger.info(f"需要执行的牧场岗位: {all_needs}")
            for post_id in all_needs:
                # 找到对应的时间变量名
                time_var_name = None
                for config_post, var_name in all_configs:
                    if config_post == post_id:
                        time_var_name = var_name
                        break

                if time_var_name:
                    self.ranch_post(post_id, time_var_name)
                else:
                    logger.warning(f"未找到岗位 {post_id} 对应的时间变量名")
        else:
            logger.info("没有需要执行的牧场岗位")

        finish_times = [getattr(self, var) for var in time_vars if getattr(self, var) is not None]
        six_hours_later = datetime.now() + timedelta(hours=6)
        finish_times.append(six_hours_later)
        finish_times.sort()
        logger.info(f'牧场任务完成，暂存 {len(finish_times)} 个计时器，最早结束时间: {finish_times[0]}')
        # 不立即写入 task_delay，而是将牧场结束时间传给渔场，
        # 等渔场任务执行完后合并比较，写入最早的时间

        # 牧场任务执行完毕，继续执行渔场任务
        from module.island.island_fishery import IslandFishery
        try:
            IslandFishery(config=self.config, device=self.device).run(ranch_finish_times=finish_times)
        except Exception as e:
            logger.error(f"渔场任务执行失败: {e}")
            raise

        if self.island_error:
            from module.exception import GameBugError
            raise GameBugError("检测到岛屿ERROR1，需要重启")

    def test(self):
        self.select_product(SELECT_CRAY, SELECT_CRAY_CHECK)


if __name__ == "__main__":
    az = IslandRancher('alas', task='Alas')
    az.device.screenshot()
    az.run()
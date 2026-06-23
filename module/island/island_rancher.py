from module.island_farm.assets import *
from module.island_rancher.assets import *
from module.island.island import *
from datetime import datetime, timedelta
from module.handler.login import LoginHandler
from module.island.warehouse import *
from module.logger import logger


class IslandRancher(Island, WarehouseOCR, LoginHandler):
    def __init__(self, *args, **kwargs):
        Island.__init__(self, *args, **kwargs)
        WarehouseOCR.__init__(self)
        self.ranch_chicken_threshold = self.config.IslandRancher_MinChicken
        self.ranch_pork_threshold = self.config.IslandRancher_MinPork
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

        self.posts_ranch = {
            'ISLAND_RANCH_POST1': ISLAND_RANCH_POST1,
            'ISLAND_RANCH_POST2': ISLAND_RANCH_POST2,
            'ISLAND_RANCH_POST3': ISLAND_RANCH_POST3,
            'ISLAND_RANCH_POST4': ISLAND_RANCH_POST4,
        }

        self.ranch_feed_map = {
            'ISLAND_RANCH_POST1': 'chicken_feed',
            'ISLAND_RANCH_POST2': 'pig_feed',
            'ISLAND_RANCH_POST3': 'cattle_feed',
            'ISLAND_RANCH_POST4': 'sheep_feed',
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
        self.ranch_last_finish_time = None

    def process_mill_item(self, mill_item, quantity=None):
        mill_config = self.name_to_config[mill_item]
        mill_button = mill_config['mill']
        target = mill_config['number'] if quantity is None else max(1, int(quantity))

        logger.info(f"加工 {mill_item} x{target}")
        for _ in self.loop(timeout=10, skip_first=False):
            if self.appear(ISLAND_SHOPPING_CHECK):
                break
            if self.appear_then_click(mill_button, interval=0.3):
                continue
        else:
            logger.warning(f"打开磨坊加工弹窗超时: {mill_item}")
            return False

        if self.appear(ISLAND_SHOPPING_CHECK):
            self.set_buy_number(target)

        for _ in self.loop(timeout=15, skip_first=False):
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
        else:
            logger.warning(f"确认磨坊加工超时: {mill_item}")
            return False

        if self.appear(ISLAND_SHOP_GET):
            self.device.click(ISLAND_SHOP_CONFIRM)
        return True

    def check_feed_needs(self, target_quantity=50):
        feed_needs = []
        for post_id, feed_item in self.ranch_feed_map.items():
            current_quantity = self.inventory_counts['mill'].get(feed_item, 0)
            if current_quantity < target_quantity:
                logger.info(f"{feed_item}库存不足: {current_quantity}/{target_quantity}")
                feed_needs.append((post_id, feed_item))
        return feed_needs

    @staticmethod
    def mill_material_needed(mill_item, quantity):
        if mill_item == 'wheat_flour':
            return quantity * 6
        return quantity * 30

    @staticmethod
    def mill_output_quantity(mill_item, quantity):
        if mill_item == 'wheat_flour':
            return quantity
        return quantity * 10

    def check_mill_supplement_needs(self, feed_target_quantity=50):
        mill_needs = []

        wheat_flour_count = self.inventory_counts['mill'].get('wheat_flour', 0)
        if wheat_flour_count < 150:
            target = 200 - wheat_flour_count
            mill_needs.append(('wheat_flour', target))
            logger.info(f"wheat_flour库存不足: {wheat_flour_count}/150，需加工 {target} 个补到 200")

        for _, feed_item in self.ranch_feed_map.items():
            current_quantity = self.inventory_counts['mill'].get(feed_item, 0)
            if current_quantity < feed_target_quantity:
                target = self.name_to_config[feed_item]['number']
                mill_needs.append((feed_item, target))
                logger.info(f"{feed_item}库存不足: {current_quantity}/{feed_target_quantity}，固定加工 {target} 组")

        return mill_needs

    def process_mill_supplements(self, feed_target_quantity=50):
        mill_needs = self.check_mill_supplement_needs(feed_target_quantity=feed_target_quantity)
        if not mill_needs:
            logger.info("牧场饲料和面粉库存充足")
            return []

        logger.info(f"需要补充的磨坊项目: {mill_needs}")
        self.goto_postmanage()
        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_close()
        self.post_manage_swipe(0)

        if not self.goto_mill_from_any_ranch_post():
            logger.warning("四个牧场岗位均无法进入磨坊，本次跳过饲料和面粉补充")
            return []

        processed_items = []
        for mill_item, quantity in mill_needs:
            if self.process_mill_item_with_inventory(mill_item, quantity):
                processed_items.append(mill_item)
                continue
            logger.warning(f"{mill_item}补充失败，跳过")

        if not self.back_to_postmanage_after_mill_purchase():
            logger.warning("磨坊补充后返回岗位管理页失败")

        return processed_items

    def process_mill_item_with_inventory(self, mill_item, quantity):
        mill_config = self.name_to_config[mill_item]
        required_material = mill_config['required_material']
        material_needed = self.mill_material_needed(mill_item, quantity)
        current_material = self.inventory_counts['farm'].get(required_material)

        if current_material is not None and current_material < material_needed:
            logger.info(
                f"{required_material}不足，无法加工{mill_item}: {current_material}/{material_needed}"
            )
            return False

        if not self.process_mill_item(mill_item, quantity=quantity):
            return False
        if required_material in self.inventory_counts['farm']:
            self.inventory_counts['farm'][required_material] = max(
                0,
                self.inventory_counts['farm'][required_material] - material_needed,
            )
            logger.info(f"扣除原材料{required_material} {material_needed}单位")

        self.inventory_counts['mill'][mill_item] = (
            self.inventory_counts['mill'].get(mill_item, 0) + self.mill_output_quantity(mill_item, quantity)
        )
        logger.info(f"加工完成：{mill_item} +{self.mill_output_quantity(mill_item, quantity)}")
        return True

    def back_to_postmanage_after_mill_purchase(self):
        """从派遣详情页进入磨坊加工后，逐层返回岗位管理页。"""
        self.interval_clear([ISLAND_MILL_BACK, SELECT_UI_BACK, POST_CLOSE])
        for _ in self.loop(timeout=20, skip_first=False):
            if (
                    self.ui_page_appear(page_island_postmanage)
                    and not self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1)
                    and not self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1)
                    and not self.appear(ISLAND_POST_CHECK, offset=1)
                    and not self.appear(ISLAND_POST_VACANT_CHECK, offset=1)
            ):
                return True
            if self.appear(ISLAND_SHOP_GET):
                self.device.click(ISLAND_SHOP_CONFIRM)
                continue
            if self.appear(ISLAND_MILL_CHECK, offset=1):
                self.device.click(ISLAND_MILL_BACK)
                continue
            if self.appear(ISLAND_CHECK, offset=(20, 20)) or self.appear(ISLAND_MANAGEMENT_CHECK, offset=1):
                self.goto_postmanage()
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                self.device.click(SELECT_UI_BACK)
                continue
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                self.device.click(SELECT_UI_BACK)
                continue
            if self.appear(ISLAND_POST_CHECK, offset=1) or self.appear(ISLAND_POST_VACANT_CHECK, offset=1):
                self.device.click(POST_CLOSE)
                continue

        logger.warning("磨坊加工后返回岗位管理页超时")
        return False

    def back_to_postmanage_after_feed_purchase(self):
        return self.back_to_postmanage_after_mill_purchase()

    def goto_mill_from_any_ranch_post(self):
        for post_id in self.posts_ranch:
            logger.info(f"尝试通过牧场岗位{post_id}进入磨坊")
            if self.goto_mill_from_ranch_post(post_id):
                logger.info(f"已通过牧场岗位{post_id}进入磨坊")
                return True
            self.back_to_postmanage_after_mill_purchase()
        return False

    def goto_mill_from_ranch_post(self, post_id):
        post_button = self.posts_ranch.get(post_id)
        if post_button is None:
            logger.warning(f"未知的牧场岗位: {post_id}")
            return False

        self.post_close()
        if not self.post_open(post_button):
            logger.info(f"牧场岗位{post_id}未开放，无法通过派遣详情进入磨坊")
            return False
        add_opened = False
        for _ in self.loop(timeout=30, skip_first=False):
            if self.appear(ERROR1, offset=30):
                self.device.click(POST_CLOSE)
                self.island_error = True
                return False
            if self.appear(ISLAND_WORKING):
                logger.info(f"牧场岗位{post_id}正在工作，无法通过派遣详情进入磨坊")
                self.device.click(POST_CLOSE)
                return False
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
                add_opened = True
                continue
            in_vacant_post = self.appear(ISLAND_POST_VACANT_CHECK, offset=1)
            if (add_opened or in_vacant_post) and self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                self.device.sleep(0.5)
                continue
            if (
                    self.appear(ISLAND_POST_CHECK, offset=1)
                    and not self.appear(POST_GET, offset=(50, 0))
                    and not self.appear(POST_ADD)
                    and not add_opened
            ):
                logger.info(f"牧场岗位{post_id}没有可追加位置，无法通过派遣详情进入磨坊")
                self.device.click(POST_CLOSE)
                return False
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                if not self.select_character('WorkerJuu'):
                    logger.warning(f"牧场岗位{post_id}无法选择补饲料用角色")
                    self.device.click(SELECT_UI_BACK)
                    return False
                if not self.confirm_selected_character(f"牧场岗位{post_id}补饲料派遣"):
                    self.back_to_postmanage_from_dispatch()
                    return False
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                return self.goto_shop_from_select_product(shop_check=ISLAND_MILL_CHECK)
        logger.warning(f"通过牧场岗位{post_id}进入磨坊超时")
        return False

    def ranch_post_get_and_add(self, post_id, character='WorkerJuu'):
        add_opened = False
        self.ranch_last_finish_time = None
        for _ in self.loop(timeout=40, skip_first=False):
            if self.appear(ERROR1, offset=30):
                self.device.click(POST_CLOSE)
                self.island_error = True
                return False
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
                add_opened = True
                continue
            in_vacant_post = self.appear(ISLAND_POST_VACANT_CHECK, offset=1)
            if (add_opened or in_vacant_post) and self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                if in_vacant_post and not add_opened:
                    logger.info(f"牧场岗位{post_id}为空闲岗位，直接进入派遣")
                self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                if self.select_character(character):
                    if not self.confirm_selected_character(f"牧场岗位{post_id}派遣"):
                        self.back_to_postmanage_from_dispatch()
                        return False
                else:
                    logger.warning(f"牧场岗位{post_id}派遣无可用角色: {character}")
                    self.back_to_postmanage_from_dispatch()
                    return False
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                feed_item = self.ranch_feed_map.get(post_id)
                if feed_item and self.inventory_counts['mill'].get(feed_item, 0) < 50:
                    logger.info(f"{feed_item}仓库库存仍不足 50，跳过牧场岗位{post_id}")
                    self.back_to_postmanage_after_feed_purchase()
                    return False
                if not self.confirm_post_add_order(f"牧场岗位{post_id}派遣"):
                    self.back_to_postmanage_from_dispatch()
                    return False
                continue
            if (
                    self.appear(ISLAND_POST_CHECK, offset=1)
                    and not self.appear(POST_GET, offset=(50, 0))
                    and not self.appear(POST_ADD)
                    and not self.appear(ISLAND_POST_SELECT, offset=1)
            ):
                logger.info(f"牧场岗位{post_id}没有可追加位置，按已满岗位处理")
                self.ranch_last_finish_time = self.ranch_ocr_finish_time(post_id)
                self.device.click(POST_CLOSE)
                return True
            if (
                    self.appear(ISLAND_POST_CHECK, offset=1)
                    and not self.appear(POST_GET, offset=(50, 0))
                    and not self.appear(POST_ADD)
                    and self.appear(ISLAND_POST_SELECT, offset=1)
                    and not add_opened
            ):
                logger.info(f"牧场岗位{post_id}没有可追加位置，跳过现有岗位槽位")
                self.ranch_last_finish_time = self.ranch_ocr_finish_time(post_id)
                self.device.click(POST_CLOSE)
                return True
            if (
                    self.appear(ISLAND_POSTMANAGE_CHECK, offset=1)
                    and not self.appear(ISLAND_POST_CHECK)
                    and not self.appear(ISLAND_POST_VACANT_CHECK, offset=1)
            ):
                return True
        logger.warning(f"牧场岗位{post_id}收取并追加派遣超时")
        return False

    def ranch_ocr_finish_time(self, post_id):
        """读取当前牧场岗位详情页的剩余时间并换算为完成时间。"""
        if (
                self.appear(ISLAND_POST_VACANT_CHECK, offset=1)
                or self.appear(ISLAND_WORK_COMPLETE, offset=1)
                or self.appear(POST_GET, offset=(50, 0))
        ):
            logger.info(f"牧场岗位{post_id}当前为空闲或可收取状态，不记录完成时间")
            return None

        if not self.appear(ISLAND_WORKING):
            logger.info(f"牧场岗位{post_id}当前未确认处于工作状态，不记录完成时间")
            return None

        time_work = Duration(ISLAND_WORKING_TIME)
        for retry in range(2):
            if retry:
                self.device.screenshot()
            if (
                    self.appear(ISLAND_POST_VACANT_CHECK, offset=1)
                    or self.appear(ISLAND_WORK_COMPLETE, offset=1)
                    or self.appear(POST_GET, offset=(50, 0))
            ):
                logger.info(f"牧场岗位{post_id}复检为空闲或可收取状态，不记录完成时间")
                return None
            if not self.appear(ISLAND_WORKING):
                logger.info(f"牧场岗位{post_id}复检后未处于工作状态，不记录完成时间")
                return None
            time_value = time_work.ocr(self.device.image)
            if time_value.total_seconds() > 0:
                finish_time = datetime.now() + time_value
                logger.info(f"牧场岗位{post_id}当前队列最早剩余时间: {time_value}")
                return finish_time

        logger.warning(f"牧场岗位{post_id}疑似工作中，但未识别到有效剩余时间")
        return None

    def post_mode_check(self, post_id):
        """检查岗位是否使用特定角色配置"""
        if post_id == 'ISLAND_RANCH_POST3':
            config_str = self.config.IslandRancher_RancherFilter
        elif post_id == 'ISLAND_RANCH_POST4':
            config_str = self.config.IslandRancher_WoolWorkerFilter
        else:
            return False
        return not config_str.strip() == 'WorkerJuu'

    def ranch_post(self, post_id, time_var_name):
        """执行牧场岗位任务"""
        if post_id not in self.posts_ranch:
            logger.error(f"未知的岗位ID: {post_id}")
            return

        post_button = self.posts_ranch[post_id]

        if post_id == 'ISLAND_RANCH_POST3':
            config_str = self.config.IslandRancher_RancherFilter
        elif post_id == 'ISLAND_RANCH_POST4':
            config_str = self.config.IslandRancher_WoolWorkerFilter
        else:
            config_str = 'WorkerJuu'

        self.post_close()
        self.post_open(post_button)
        self.device.sleep(0.5)
        self.device.screenshot()
        if self.appear(ISLAND_WORKING) and self.post_mode_check(post_id):
            finish_time = self.ranch_ocr_finish_time(post_id)
            if finish_time is not None:
                setattr(self, time_var_name, finish_time)
                self.post_close()
                return True

            logger.warning(f"牧场岗位{post_id}工作状态疑似误判，继续尝试收取或追加派遣")

        self.ranch_last_finish_time = None
        if not self.ranch_post_get_and_add(post_id, config_str):
            self.post_close()
            return False
        if self.ranch_last_finish_time is not None:
            setattr(self, time_var_name, self.ranch_last_finish_time)
            return True

        self.post_open(post_button)
        self.device.sleep(0.5)
        self.device.screenshot()
        finish_time = self.ranch_ocr_finish_time(post_id)
        if finish_time is None:
            self.post_close()
            logger.warning(f"牧场岗位{post_id}未取得有效完成时间，本次不写入岗位计时器")
            return False
        setattr(self, time_var_name, finish_time)
        self.post_close()
        return True

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
        if chicken_count < self.ranch_chicken_threshold:
            ranch_needs.append('ISLAND_RANCH_POST1')
            logger.info("需要执行养鸡任务")

        pork_count = self.inventory_counts['ranch'].get('pork', 0)
        if pork_count < self.ranch_pork_threshold:
            ranch_needs.append('ISLAND_RANCH_POST2')
            logger.info("需要执行养猪任务")

        ranch_needs.append('ISLAND_RANCH_POST3')
        logger.info("需要执行养牛任务")

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

        logger.info("\n[3/5] 检查并补充牧场饲料和面粉...")
        processed_mill_items = self.process_mill_supplements(feed_target_quantity=50)
        if processed_mill_items:
            logger.info(f"本次运行补充了 {len(processed_mill_items)} 个磨坊项目: {processed_mill_items}")
        else:
            logger.info("本次运行未补充磨坊项目")

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
                    if not self.ranch_post(post_id, time_var_name):
                        logger.warning(f"牧场岗位 {post_id} 执行失败，跳过")
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

if __name__ == "__main__":
    az = IslandRancher('alas', task='Alas')
    az.device.screenshot()
    az.run()

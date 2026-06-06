import os
from module.island.island import Island
from module.island.assets import *
from module.island_business.assets import *
from module.ui.page import *
from module.island_select_character.assets import *
from module.logger import logger
from module.base.button import Button
from module.base.template import Template
from module.base.utils import crop
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
        
        self._init_season_config()
        self.season = self.season_config.season
        logger.info(f"当前季节: {self.season_config.season_name}")
        
        # 读取每个商店配置的角色和餐品
        self._load_shop_configs()
        
        logger.info("经营模块初始化完成")
        
        
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
    
    def _parse_character_config(self, config_str):
        if isinstance(config_str, str):
            return [char.strip() for char in config_str.split('>')]
        return ['WorkerJuu']
    
    def run(self):
        logger.info("=== 开始经营模块 ===")
        self.goto_postmanage()
        self.device.sleep(1)
        logger.info("切换到经营页签")
        self.post_manage_mode(POST_MANAGE_BUSINESS)
        self.device.sleep(3)
        
        # 处理每日首次进入可能出现的美食评审界面
        self._handle_food_review()
        
        # 标记本轮是否曾处理过蓝色开始经营按钮
        self._has_seen_blue = False
        
        # 无限循环处理，直到所有商店处理完毕（灰色按钮/经营中状态会 return 退出）
        while True:
            logger.info("--- 处理商店 ---")
            
            # 先检测开始经营按钮状态
            status = self._check_start_button_status()
            
            if status == 'blue':
                self._has_seen_blue = True
                logger.info("检测到蓝色按钮，点击进入商店")
                self.device.click(BUSINESS_START_BUTTON_BLUE)
                self.device.sleep(1)
                
                # 进入商店后，检测商店标签确定当前是哪个商店
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
                # 经营完成后重新进入经营页签，自动切换到下一个商店
                self.post_manage_mode(POST_MANAGE_BUSINESS)
                self.device.sleep(0.5)
            elif status == 'yellow':
                logger.info("检测到黄色领取奖励按钮")
                self._claim_business_reward()
                self.post_manage_mode(POST_MANAGE_BUSINESS)
                self.device.sleep(0.5)
            elif status == 'darkblue':
                if self._has_seen_blue:
                    # 此前处理过蓝色按钮（已启动经营），返回后按钮变深蓝 → 正常退出
                    logger.info("经营已启动，正常退出")
                    # 整个经营模块结束，重置所有生产任务延时使其立即补充商品
                    self._trigger_shop_refill()
                    self._set_task_delay()
                    return
                # 首次识别到深蓝（所有商店已在经营中）→ OCR 剩余时间并精确延时
                logger.info("经营中，检测剩余时间")
                ocr_remain = Duration(BUSINESS_REMAIN_TIME_AREA, lang='azur_lane',
                                      letter=(255, 255, 255), threshold=128,
                                      name='OCR_BUSINESS_REMAIN')
                remain = ocr_remain.ocr(self.device.image)
                if remain and remain.total_seconds() > 0:
                    # 剩余时间 + 5分钟余量
                    delay_seconds = remain.total_seconds() + 300
                    logger.info(f"经营剩余 {remain}，延时 {delay_seconds / 60:.1f} 分钟后检测")
                    self.config.task_delay(minute=delay_seconds / 60)
                else:
                    logger.warning("剩余时间OCR失败，使用默认2小时延时")
                    next_time = self._calculate_darkblue_delay()
                    self.config.task_delay(target=next_time)
                return
            elif status == 'gray':
                logger.info("不可经营，延后至明天0点")
                tomorrow = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                self.config.task_delay(target=tomorrow)
                return
            else:
                logger.info("按钮状态未知，跳过")
                continue
        
        self._trigger_shop_refill()
        self._set_task_delay()
        logger.info("=== 经营模块完成 ===")
    
    # 商店标签到对应 Template 的映射
    SHOP_TEMPLATE_MAP = {
        '有鱼餐馆': TEMPLATE_BUSINESS_SHOP_FISH_RESTAURANT,
        '白熊饮品': TEMPLATE_BUSINESS_SHOP_TEAHOUSE,
        '啾啾简餐': TEMPLATE_BUSINESS_SHOP_JUU_EATERY,
        '乌鱼烤肉': TEMPLATE_BUSINESS_SHOP_GRILL,
        '啾咖啡': TEMPLATE_BUSINESS_SHOP_JUU_COFFEE,
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
    
    def _claim_business_reward(self):
        logger.info("领取经营奖励")
        # 第1步：点击黄色按钮进入结算界面
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
        
        # 第2步：等待"经营结算"按钮出现并点击（未出现时点安全区域）
        timeout = 0
        self.device.sleep(1)
        while not self.appear(BUSINESS_SETTLEMENT, offset=30):
            timeout += 1
            if timeout > 10:
                logger.warning("等待经营结算按钮超时，跳过")
                return
            self.device.click(BUSINESS_REWARD_SAFE_AREA)
            self.device.sleep(0.5)
            self.device.screenshot()
        logger.info("检测到经营结算按钮")
        self.device.click(BUSINESS_SETTLEMENT)
        self.device.sleep(1)
        
        # 第3步：等待"销售情况"出现，点击安全区域（未出现时点安全区域）
        self.device.screenshot()
        timeout = 0
        while not self.appear(BUSINESS_SALES_STATUS, offset=30):
            timeout += 1
            if timeout > 10:
                logger.warning("等待销售情况图片超时，跳过")
                return
            self.device.click(BUSINESS_REWARD_SAFE_AREA)
            self.device.sleep(0.5)
            self.device.screenshot()
        logger.info("检测到销售情况")
        self.device.click(BUSINESS_REWARD_SAFE_AREA)
        self.device.sleep(1)
        
        # 第4步：等待"获得物品"出现，点击安全区域（同时检测是否已跳过此步或回到经营界面）
        self.device.screenshot()
        timeout = 0
        obtained = False
        while not self.appear(BUSINESS_OBTAINED_ITEMS, offset=30):
            # 如果已经出现返回按钮，说明已跳过获得物品步骤，直接进入第5步
            if self.appear(ISLAND_BACK, offset=30):
                logger.info("检测到返回按钮，跳过获得物品步骤")
                obtained = True
                break
            # 如果已经退出到经营界面，直接退出
            if self.appear(POST_MANAGE_BUSINESS, offset=30) or self.appear(POST_MANAGE_PRODUCTION, offset=30):
                logger.info("已回到经营界面，退出领取")
                return
            timeout += 1
            if timeout > 10:
                logger.warning("等待获得物品图片超时，跳过")
                obtained = True
                break
            self.device.click(BUSINESS_REWARD_SAFE_AREA)
            self.device.sleep(1)
            self.device.screenshot()
        if not obtained:
            logger.info("检测到获得物品")
            self.device.click(BUSINESS_REWARD_SAFE_AREA)
            self.device.sleep(1)
        
        # 第5步：等待ISLAND_BACK出现并点击返回（同时检测是否已回到经营界面）
        self.device.screenshot()
        timeout = 0
        while not self.appear(ISLAND_BACK, offset=30):
            # 如果已经退出到经营界面，直接退出
            if self.appear(POST_MANAGE_BUSINESS, offset=30) or self.appear(POST_MANAGE_PRODUCTION, offset=30):
                logger.info("已回到经营界面，退出领取")
                return
            timeout += 1
            if timeout > 10:
                logger.warning("等待ISLAND_BACK超时，跳过")
                return
            self.device.click(BUSINESS_REWARD_SAFE_AREA)
            self.device.sleep(1)
            self.device.screenshot()
        logger.info("检测到返回按钮，点击结束领取")
        self.device.click(ISLAND_BACK)
        self.device.sleep(1)
        # 点完后确保回到经营页签，如果检测不到经营选中页签则继续点击返回按钮
        self.device.screenshot()
        confirm_timeout = 0
        while not self.appear(POST_MANAGE_BUSINESS, offset=30):
            confirm_timeout += 1
            if confirm_timeout > 10:
                logger.warning("返回后检测经营选中页签超时，跳过")
                break
            logger.info("未检测到经营选中页签，继续点击返回按钮")
            self.device.click(ISLAND_BACK)
            self.device.sleep(1)
            self.device.screenshot()
    
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

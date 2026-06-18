from module.island.island import *
from module.island_mine_forest.assets import *
from module.ui.page import *
from module.handler.login import LoginHandler
from module.config.utils import *
from module.island.warehouse import *


class IslandMineForest(Island,LoginHandler):
    def __init__(self, *args, **kwargs):
        Island.__init__(self, *args, **kwargs)

        # 矿山和林场的库存配置（模仿农田模块的 INVENTORY_CONFIG）
        self.inventory_config = {
            'mine': {
                'filter': 'mine',
                'items': [
                    {'name': 'Copper', 'template': TEMPLATE_COPPER, 'selection': SELECT_COPPER, 'selection_check': SELECT_COPPER_CHECK},
                    {'name': 'Aluminium', 'template': TEMPLATE_ALUMINIUM, 'selection': SELECT_ALUMINIUM, 'selection_check': SELECT_ALUMINIUM_CHECK},
                    {'name': 'Iron', 'template': TEMPLATE_IRON, 'selection': SELECT_IRON, 'selection_check': SELECT_IRON_CHECK},
                    {'name': 'Sulphur', 'template': TEMPLATE_SULPHUR, 'selection': SELECT_SULPHUR, 'selection_check': SELECT_SULPHUR_CHECK},
                    {'name': 'Silver', 'template': TEMPLATE_SILVER, 'selection': SELECT_SILVER, 'selection_check': SELECT_SILVER_CHECK},
                ]
            },
            'forest': {
                'filter': 'forest',
                'items': [
                    {'name': 'Elegant', 'template': TEMPLATE_ELEGANT, 'selection': SELECT_ELEGANT, 'selection_check': SELECT_ELEGANT_CHECK},
                    {'name': 'Practical', 'template': TEMPLATE_PRACTICAL, 'selection': SELECT_PRACTICAL, 'selection_check': SELECT_PRACTICAL_CHECK},
                    {'name': 'Selected', 'template': TEMPLATE_SELECTED, 'selection': SELECT_SELECTED, 'selection_check': SELECT_SELECTED_CHECK},
                ]
            }
        }

    # 产物配置（选角色/选产物/检测用，模仿农田 name_to_config）
    PRODUCT_CONFIGS = {
        "Copper": (SELECT_COPPER, SELECT_COPPER_CHECK, POST_COPPER),
        "Aluminium": (SELECT_ALUMINIUM, SELECT_ALUMINIUM_CHECK, POST_ALUMINIUM),
        "Iron": (SELECT_IRON, SELECT_IRON_CHECK, POST_IRON),
        "Sulphur": (SELECT_SULPHUR, SELECT_SULPHUR_CHECK, POST_SULPHUR),
        "Silver": (SELECT_SILVER, SELECT_SILVER_CHECK, POST_SILVER),
        "Elegant": (SELECT_ELEGANT, SELECT_ELEGANT_CHECK, POST_ELEGANT),
        "Practical": (SELECT_PRACTICAL, SELECT_PRACTICAL_CHECK, POST_PRACTICAL),
        "Selected": (SELECT_SELECTED, SELECT_SELECTED_CHECK, POST_SELECTED),
    }

    # 每岗产 4 个
    UNITS_PER_RUN = 4
    # 各产物的最大生产次数（实用之木9次，铜矿12次，铁矿8次，其他5次）
    PRODUCT_MAX_RUNS = {
        # 矿山
        'Copper': 12, 'Aluminium': 5, 'Iron': 8,
        'Sulphur': 5, 'Silver': 5,
        # 林场
        'Elegant': 5, 'Practical': 9, 'Selected': 5,
    }


    # 仓库文字识别区域：基坐标 (300,258,408,289)，每项右移 142px
    # y 范围 258~289 以完整捕获中文文字（测试确认 y=261~283 为最佳识别区域）
    OCR_TEXT_BASE = (300, 258, 408, 289)
    OCR_TEXT_DELTA = 142
    # 数字区域：使用 WarehouseOCR 网格的相对偏移 (45, 90, 99, 110)
    # 网格原点 (301,150)，列间距 142px
    WAREHOUSE_GRID_ORIGIN = (301, 150)
    WAREHOUSE_GRID_DELTA = (142, 167)
    NUMBER_REL = (45, 90, 99, 110)

    def _get_threshold(self, product_name):
        """获取指定产品的最低库存阈值"""
        mine_products = ['Copper', 'Aluminium', 'Iron', 'Sulphur', 'Silver']
        forest_products = ['Elegant', 'Practical', 'Selected']
        if product_name in mine_products:
            return getattr(self.config, f'IslandMine_Min{product_name}', 0)
        elif product_name in forest_products:
            return getattr(self.config, f'IslandForest_Min{product_name}', 0)
        return 0

    # ==================== 仓库检测（OCR 文字识别物品，再用 Digit 读数量） ====================
    # 所有可识别物品的中文名映射（矿山 + 林场）
    # OCR 可能识别不完全，每个物品提供多个可能的名称
    ITEM_CN_NAMES = {
        'Copper': ['铜矿'],
        'Aluminium': ['铝矿'],
        'Iron': ['铁矿'],
        'Sulphur': ['硫磺', '硫矿'],
        'Silver': ['银矿'],
        'Practical': ['实用之木', '实用之本'],
        'Selected': ['精选之木', '精选之本'],
        'Elegant': ['典雅之木', '典雅之本'],
    }

    def warehouse_inventory(self, category):
        """
        获取仓库库存。
        扫描仓库网格所有 6 个位置：
        1. OCR 读取每个位置的中文文字确定物品
        2. 匹配到后读取对应图标右下角的数字
        3. 仓库内物品顺序不固定，缺省项数量记为 0
        """
        config = self.inventory_config[category]
        self.warehouse_filter(config['filter'])
        image = self.device.screenshot()

        # 初始化所有物品数量为 0
        results = {item['name']: 0 for item in config['items']}

        # 扫描所有 6 个网格位置（物品顺序不固定）
        for idx in range(6):
            # 文字识别区域
            tx1 = self.OCR_TEXT_BASE[0] + idx * self.OCR_TEXT_DELTA
            ty1 = self.OCR_TEXT_BASE[1]
            tx2 = self.OCR_TEXT_BASE[2] + idx * self.OCR_TEXT_DELTA
            ty2 = self.OCR_TEXT_BASE[3]
            text_area = (tx1, ty1, tx2, ty2)
            text_btn = Button(area=text_area, color=(), button=text_area, name=f'TEXT_POS{idx}')
            ocr = Ocr(text_btn, lang='cnocr')
            text = ocr.ocr(image)

            if not text:
                # 空位，跳过
                continue

            # 匹配识别到的文字与已知物品名
            matched_name = None
            for name, cn_names in self.ITEM_CN_NAMES.items():
                for cn_name in cn_names:
                    if cn_name in text:
                        matched_name = name
                        break
                if matched_name:
                    break

            if matched_name is None:
                logger.info(f"  pos{idx}: 识别到'{text}' → 无法匹配已知物品，跳过")
                continue

            # 只统计当前分类的物品
            if matched_name not in results:
                continue

            # 读取数字区域
            cx = self.WAREHOUSE_GRID_ORIGIN[0] + idx * self.WAREHOUSE_GRID_DELTA[0]
            cy = self.WAREHOUSE_GRID_ORIGIN[1]  # row 0
            nx1 = cx + self.NUMBER_REL[0]
            ny1 = cy + self.NUMBER_REL[1]
            nx2 = cx + self.NUMBER_REL[2]
            ny2 = cy + self.NUMBER_REL[3]
            num_area = (nx1, ny1, nx2, ny2)
            num_btn = Button(area=num_area, color=(), button=num_area, name=f'NUM_{matched_name}')
            digit = Digit(num_btn, letter=(255, 255, 255), threshold=200, alphabet='0123456789')
            count = digit.ocr(image)
            results[matched_name] = count if count else 0
            logger.info(f"  pos{idx}: {matched_name}({text.strip()}) = {results[matched_name]}")

        return results

    def check_inventory_and_prepare_lists(self):
        """
        检查仓库库存 + 生产中数量，返回需要生产的产物及缺口数量。
        返回 {'mine': [need1, ...], 'forest': [need1, ...]}
        同时设置 self.needs_count = {(category, product): count_needed}
        """
        needs = {'mine': [], 'forest': []}
        self.needs_count = {}

        for category in ['mine', 'forest']:
            inventory = self.warehouse_inventory(category)
            for item in self.inventory_config[category]['items']:
                name = item['name']
                warehouse_count = inventory.get(name, 0)

                # 加上已在生产中的数量（生产中的岗位 × 每岗4个）
                in_production = 0
                post_ids = self.mine_post_ids if category == 'mine' else self.forest_post_ids
                for pid in post_ids:
                    if self.posts.get(pid, {}).get('crop') == name:
                        runs = self.posts.get(pid, {}).get('runs', 0)
                        in_production += runs * self.UNITS_PER_RUN

                effective_count = warehouse_count + in_production
                threshold = self._get_threshold(name)
                if effective_count < threshold:
                    needs[category].append(name)
                    need_count = threshold - effective_count
                    self.needs_count[(category, name)] = need_count
                    logger.info(f"  {name}: 仓库{warehouse_count}+生产中{in_production}={effective_count} < {threshold} → 缺 {need_count}")
                else:
                    logger.info(f"  {name}: 仓库{warehouse_count}+生产中{in_production}={effective_count} ≥ {threshold} → 不缺")

        logger.info(f"需要生产的产物: {needs}")
        return needs

    # ==================== 岗位检测（模仿农田 decided_lists） ====================
    def post_plant_check(self, category):
        """检测当前打开的岗位正在生产什么产物"""
        for item in self.inventory_config[category]['items']:
            name = item['name']
            if name in self.PRODUCT_CONFIGS:
                _, _, post_check = self.PRODUCT_CONFIGS[name]
                if post_check is not None and self.appear(post_check):
                    return name
        return None

    def collect_and_detect_post(self, post_button, post_id, category, time_var_name):
        """
        打开岗位，收获已完成产物，并检测当前状态。
        一次打开完成收获+检测，避免重复开岗。
        对工作中岗位，读取生产次数用于后续计算防止多产。
        """
        self.post_close()
        self.post_open(post_button)
        self.device.screenshot()

        if self.appear(ISLAND_WORK_COMPLETE, offset=1):
            # 已完成 → 先收获，再标记为空
            self.post_get_and_close()
            # 重新打开以检测状态
            self.post_open(post_button)
            self.device.screenshot()
            if self.appear(ISLAND_POST_SELECT, offset=1):
                self.posts[post_id]['crop'] = None
                self.posts[post_id]['runs'] = 0
                setattr(self, time_var_name, None)
                logger.info(f"  {post_id}: 收获完成，空闲")
            else:
                self.posts[post_id]['crop'] = None
                self.posts[post_id]['runs'] = 0
                setattr(self, time_var_name, None)
                logger.info(f"  {post_id}: 收获完成")

        elif self.appear(ISLAND_WORKING):
            # 正在工作 → 检测产物
            product_name = self.post_plant_check(category)
            if product_name:
                self.posts[post_id]['crop'] = product_name
            else:
                self.posts[post_id]['crop'] = None
            # 读取生产次数
            ocr_post_number = Digit(OCR_POST_NUMBER, letter=(57, 58, 60), threshold=100,
                                    alphabet='0123456789')
            number = ocr_post_number.ocr(self.device.image)
            self.posts[post_id]['runs'] = number if number else 0
            logger.info(f"  {post_id}: 正在生产 {product_name or '未知'}，剩余 {self.posts[post_id]['runs']} 次")
            # 记录时间
            time_work = Duration(ISLAND_WORKING_TIME)
            time_value = time_work.ocr(self.device.image)
            finish_time = datetime.now() + time_value
            setattr(self, time_var_name, finish_time)

        elif self.appear(ISLAND_POST_SELECT, offset=1):
            # 空闲
            self.posts[post_id]['crop'] = None
            self.posts[post_id]['runs'] = 0
            setattr(self, time_var_name, None)
            logger.info(f"  {post_id}: 空闲")

        self.post_close()

    # ==================== 设置生产（模仿农田 post_plant，去掉选种） ====================
    def post_plant(self, post_button, product, category, time_var_name, need_count=None):
        """
        设置岗位生产（模仿农田 post_plant，去掉买种子步骤）。
        按缺口数量计算生产次数，避免浪费。
        """
        self.post_close()
        self.post_open(post_button)
        self.device.screenshot()

        # 获取该产物的选择按钮和确认检测按钮
        selection = None
        selection_check = None
        for item in self.inventory_config[category]['items']:
            if item['name'] == product:
                selection = item['selection']
                selection_check = item['selection_check']
                break

        # 计算需要生产多少单位
        max_runs = self.PRODUCT_MAX_RUNS.get(product, 5)
        max_units = max_runs * self.UNITS_PER_RUN
        if need_count and need_count > 0:
            # 每岗最少 1 次（4 单位），不超过该产物最大次数
            runs = max(1, min(max_runs, -(-need_count // self.UNITS_PER_RUN)))  # ceil 除法
            target_units = runs * self.UNITS_PER_RUN
        else:
            runs = max_runs
            target_units = max_units  # 默认满产
        logger.info(f"  {product}: 缺 {need_count or '满产'} 单位，安排 {runs}/{max_runs} 次生产 ({target_units} 单位)")

        while 1:
            self.device.screenshot()

            if self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                continue

            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                if self.select_character():
                    self.device.sleep(0.3)
                    self.appear_then_click(SELECT_UI_CONFIRM)
                    self.device.sleep(0.3)
                continue

            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                # 点击产物按钮
                if selection is not None:
                    self.device.click(selection)
                    self.device.sleep(0.3)
                # 验证产物是否选对（检查 selection_check 出现）
                if selection_check is not None:
                    self.device.screenshot()
                    if not self.match_template_color(selection_check, offset=20, similarity=0.85, threshold=10):
                        logger.warning(f"产物 {product} 选择未被确认，可能需要滑动查找")
                        self.device.swipe_vector(vector=(0, -200), box=(333, 142, 431, 602), name="SelectionUpSwipe")
                        self.device.sleep(0.3)
                        self.device.click(SELECT_PRODUCT_INERTIA_STOP)
                        self.device.sleep(0.2)
                        continue
                # 设置生产数量
                if runs == max_runs:
                    # 满产直接用 POST_MAX
                    self.device.click(POST_MAX)
                    self.device.sleep(0.3)
                elif runs > 1:
                    # 默认1次，用 POST_ADD_ONE 增加次数
                    for _ in range(runs - 1):
                        self.device.click(POST_ADD_ONE)
                        self.device.sleep(0.1)
                # runs == 1 时默认就是1次，不用操作
                self.device.click(POST_ADD_ORDER)
                self.device.sleep(0.5)
                break

        # 重新打开 → 记录时间
        self.post_open(post_button)
        self.device.sleep(0.3)
        self.device.screenshot()
        time_work = Duration(ISLAND_WORKING_TIME)
        time_value = time_work.ocr(self.device.image)
        finish_time = datetime.now() + time_value
        setattr(self, time_var_name, finish_time)

        # 更新岗位记录
        for pid, pinfo in self.posts.items():
            if pinfo['button'] == post_button:
                pinfo['crop'] = product
                break

        # 关闭详情弹窗，防止后续滑动/操作被弹窗遮挡
        self.post_close()
        return True

    # ==================== 主运行流程 ====================
    def run(self):
        """
        流程：
          1. 初始化岗位信息，进入管理 → 收获 + 检测所有岗位（一次遍历）
          2. 退出管理，去仓库检查库存
          3. 回到管理 → 分配空闲岗位
          4. 执行生产
        """
        self.island_error = False

        # ===== 读取岗位数量 =====
        mine_positions = self.config.IslandMine_Positions
        forest_positions = self.config.IslandForest_Positions

        # ===== 初始化岗位信息 =====
        self.posts = {}
        MINE_POST_BUTTONS = [ISLAND_MINE_POST1, ISLAND_MINE_POST2, ISLAND_MINE_POST3, ISLAND_MINE_POST4]
        FOREST_POST_BUTTONS = [ISLAND_FOREST_POST1, ISLAND_FOREST_POST2, ISLAND_FOREST_POST3, ISLAND_FOREST_POST4]
        self.time_vars = {'mine': [None] * mine_positions, 'forest': [None] * forest_positions}

        self.mine_post_ids = []
        for i in range(mine_positions):
            pid = f'ISLAND_MINE_POST{i + 1}'
            self.mine_post_ids.append(pid)
            self.posts[pid] = {'button': MINE_POST_BUTTONS[i], 'crop': None, 'runs': 0}

        self.forest_post_ids = []
        for i in range(forest_positions):
            pid = f'ISLAND_FOREST_POST{i + 1}'
            self.forest_post_ids.append(pid)
            self.posts[pid] = {'button': FOREST_POST_BUTTONS[i], 'crop': None, 'runs': 0}

        # ===== 步骤1：进入管理 → 收获 + 检测所有岗位 =====
        logger.info("进入管理页面，收获已完成产物并检测岗位状态")
        self.goto_postmanage()
        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_close()
        self.post_manage_down_swipe(450)
        self.post_manage_down_swipe(450)

        # 矿山（在上方可见）
        for pid in self.mine_post_ids:
            info = self.posts[pid]
            time_var = f'time_{pid}'
            setattr(self, time_var, None)
            self.collect_and_detect_post(info['button'], pid, 'mine', time_var)

        # 滑动到林场
        self.device.sleep(1)
        self.post_manage_down_swipe(600)
        self.device.sleep(0.5)

        # 林场
        for pid in self.forest_post_ids:
            info = self.posts[pid]
            time_var = f'time_{pid}'
            setattr(self, time_var, None)
            self.collect_and_detect_post(info['button'], pid, 'forest', time_var)

        # ===== 步骤2：退出管理 → 去仓库检查库存 =====
        logger.info("退出管理，检查仓库库存")
        self.ui_goto(page_island_management)
        needs = self.check_inventory_and_prepare_lists()
        # 检查库存后回到管理页面
        self.goto_postmanage()
        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_close()

        # ===== 步骤3：分配空闲岗位 =====
        # 找出空闲岗位（crop == None）
        idle_posts = {'mine': [], 'forest': []}
        for category, post_ids in [('mine', self.mine_post_ids), ('forest', self.forest_post_ids)]:
            for pid in post_ids:
                if self.posts[pid]['crop'] is None:
                    idle_posts[category].append(pid)

        logger.info(f"空闲岗位: 矿山 {len(idle_posts['mine'])} 个, 林场 {len(idle_posts['forest'])} 个")

        # 产物有缺口的先分配，剩下的默认
        all_to_plant = {'mine': [], 'forest': []}
        for category in ['mine', 'forest']:
            # needs 中属于该分类的产物
            cat_needs = needs.get(category, [])
            idle_count = len(idle_posts[category])

            # 取 min(空闲数, 缺口数) 个配给缺口产物
            num_from_needs = min(len(cat_needs), idle_count)
            for i in range(num_from_needs):
                all_to_plant[category].append(cat_needs[i])

            # 剩余空闲 → 按配置分配默认产物，其余空着不动
            remaining = idle_count - num_from_needs
            if category == 'mine':
                # MineSilver: 几个空闲岗位产银矿，其余空着
                silver_count = min(self.config.IslandMine_MineSilver, remaining)
                for _ in range(silver_count):
                    all_to_plant['mine'].append('Silver')
            else:
                # CutElegant: 几个空闲岗位产典雅之木，其余空着
                elegant_count = min(self.config.IslandForest_CutElegant, remaining)
                for _ in range(elegant_count):
                    all_to_plant['forest'].append('Elegant')

            if all_to_plant[category]:
                logger.info(f"{category} 需要种植: {all_to_plant[category]}")

        # ===== 步骤4：执行种植（无需买种子） =====
        if any(all_to_plant.values()):
            # 先回到顶部（矿山可见）
            self.post_manage_down_swipe(450)
            self.post_manage_down_swipe(450)
            self.device.sleep(0.5)

            # 处理矿山
            for i, pid in enumerate(idle_posts['mine']):
                if i >= len(all_to_plant['mine']):
                    break
                product = all_to_plant['mine'][i]
                need_count = self.needs_count.get(('mine', product), None)
                time_var = f'time_{pid}'
                logger.info(f"种植矿山 {pid}: {product}")
                self.post_plant(self.posts[pid]['button'], product, 'mine', time_var, need_count=need_count)

            # 滑动到林场
            self.device.sleep(1)
            self.post_manage_down_swipe(600)
            self.device.sleep(0.5)

            # 处理林场
            for i, pid in enumerate(idle_posts['forest']):
                if i >= len(all_to_plant['forest']):
                    break
                product = all_to_plant['forest'][i]
                need_count = self.needs_count.get(('forest', product), None)
                time_var = f'time_{pid}'
                logger.info(f"种植林场 {pid}: {product}")
                self.post_plant(self.posts[pid]['button'], product, 'forest', time_var, need_count=need_count)

        # ===== 收集完成时间 =====
        future_finish = []
        for category in ['mine', 'forest']:
            post_ids = self.mine_post_ids if category == 'mine' else self.forest_post_ids
            for pid in post_ids:
                time_var = f'time_{pid}'
                ft = getattr(self, time_var, None)
                if ft is not None:
                    future_finish.append(ft)

        six_hours_later = datetime.now() + timedelta(hours=6)
        future_finish.append(six_hours_later)
        future_finish.sort()
        self.config.task_delay(target=future_finish)
        logger.info(f'下次运行时间: {future_finish[0]}')

        if self.island_error:
            from module.exception import GameBugError
            raise GameBugError("检测到岛屿ERROR1，需要重启")

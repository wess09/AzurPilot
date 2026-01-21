
# 导入基础计时器（控制操作间隔，避免高频点击）
from module.base.timer import Timer
# 导入联合活动的界面元素（按钮、页面标识等，如关卡入口、模式开关）
from module.coalition.assets import *
# 导入战斗相关的界面元素（战斗准备页面标识）
from module.combat.assets import BATTLE_PREPARATION
# 导入战斗基类（提供通用战斗方法，如处理剧情跳过、低情绪等）
from module.combat.combat import Combat
# 导入自定义异常类（关卡名称错误、请求人工接管、脚本错误）
from module.exception import CampaignNameError, RequestHumanTakeover, ScriptError
# 导入日志工具（输出脚本运行信息，便于调试和监控）
from module.logger import logger
# 导入UI通用元素（返回箭头按钮）
from module.ui.assets import BACK_ARROW
# 导入页面标识（联合活动主页面）
from module.ui.page import page_coalition
# 导入开关切换基类（处理界面上的开关/选择器）
from module.ui.switch import Switch


class NeoncitySwitch(Switch):
    """
    霓虹城活动（coalition_20250626）专用的开关状态检测类
    继承自基础Switch类，重写get方法以适配该活动的红色文本状态识别逻辑
    """

    def get(self, main):
        """
        获取开关当前状态（story/battle）
        核心逻辑：检测按钮区域内红色文本的像素数量，判断当前选中状态

        Args:
            main: 主控制器实例（提供截图、图像识别等方法）

        Returns:
            str: 识别到的状态（story/battle），未识别则返回'unknown'
        """
        # 遍历所有已注册的状态（story/battle）
        for data in self.state_list:
            # 检测指定按钮区域内 红色文本(RGB:123,41,41) 的像素数量
            # threshold=221：颜色匹配阈值（容错），count=100：像素数量阈值（避免误识别）
            if main.image_color_count(
                    data['check_button'],  # 要检测的按钮元素
                    color=(123, 41, 41),  # 目标颜色（红色文本）
                    threshold=221,  # 颜色匹配容错值
                    count=100  # 满足条件的最小像素数
            ):
                return data['state']  # 返回匹配到的状态

        return 'unknown'  # 未识别到任何状态


class CoalitionUI(Combat):
    """
    联合活动核心操作类，继承自Combat战斗基类
    封装所有联合活动的UI交互逻辑：页面判断、模式切换、关卡进入、异常处理等
    """

    def in_coalition(self):
        """
        判断是否处于联合活动主页面

        Returns:
            bool: True（在联合活动页面）/False（不在）
        """
        # ui_page_appear：检测指定页面标识是否出现
        # offset=(20,20)：页面元素偏移容错（避免界面微小偏移导致误判）
        return self.ui_page_appear(page_coalition, offset=(20, 20))

    def in_coalition_20251120_difficulty_selection(self):
        """
        专门判断是否处于2025年11月20日版本活动的难度选择页面

        Returns:
            bool: True（在难度选择页）/False（不在）
        """
        # appear：检测指定界面元素是否出现在屏幕上
        return self.appear(DAL_DIFFICULTY_EXIT, offset=(20, 20))
    def in_coalition_20260122_difficulty_selection(self):
        """
        专门判断是否处于2025年11月20日版本活动的难度选择页面

        Returns:
            bool: True（在难度选择页）/False（不在）
        """
        # appear：检测指定界面元素是否出现在屏幕上
        return self.appear(Light_Shadow_Fashion_DIFFICULTY_EXIT, offset=(20, 20))

    def coalition_ensure_mode(self, event, mode):
        """
        确保切换到指定的活动模式（剧情/战斗）

        Args:
            event (str): 活动名称，如'coalition_20230323'
            mode (str): 目标模式，'story'（剧情）或'battle'（战斗）

        Pages:
            in: 联合活动主页面
        """
        # 不同活动对应不同的模式开关按钮，逐个适配
        if event == 'coalition_20230323':
            # 初始化开关实例，offset=(20,20)：按钮偏移容错
            mode_switch = Switch('CoalitionMode', offset=(20, 20))
            # 注意：该活动的开关按钮是反向的（剧情对应战斗按钮，战斗对应剧情按钮）
            mode_switch.add_state('story', FROSTFALL_MODE_STORY)  # 剧情模式对应按钮
            mode_switch.add_state('battle', FROSTFALL_MODE_BATTLE)  # 战斗模式对应按钮
        elif event == 'coalition_20240627':
            mode_switch = Switch('CoalitionMode', offset=(20, 20))
            mode_switch.add_state('story', ACADEMY_MODE_BATTLE)
            mode_switch.add_state('battle', ACADEMY_MODE_STORY)
        elif event == 'coalition_20250626':
            # 该活动使用自定义的NeoncitySwitch类（基于红色文本识别状态）
            mode_switch = NeoncitySwitch('CoalitionMode', offset=(20, 20))
            mode_switch.add_state('story', NEONCITY_MODE_STORY)
            mode_switch.add_state('battle', NEONCITY_MODE_BATTLE)
        elif event == 'coalition_20260122':
            # 该活动使用自定义的NeoncitySwitch类（基于红色文本识别状态）
            mode_switch = NeoncitySwitch('CoalitionMode', offset=(20, 20))
            mode_switch.add_state('story', NEONCITY_MODE_STORY)
            mode_switch.add_state('battle', NEONCITY_MODE_BATTLE)
        elif event == 'coalition_20251120':
            # 该活动无剧情/战斗模式切换，直接返回
            logger.info('Coalition event coalition_20251120 has no mode switch')
            return
        else:
            # 未定义的活动，输出错误日志并抛出脚本异常
            logger.error(f'MODE_SWITCH is not defined in event {event}')
            raise ScriptError

        # 执行模式切换操作
        if mode == 'story':
            mode_switch.set('story', main=self)  # 切换到剧情模式
        elif mode == 'battle':
            mode_switch.set('battle', main=self)  # 切换到战斗模式
        else:
            # 未知模式，仅输出警告日志（不抛异常，保留容错）
            logger.warning(f'Unknown coalition campaign mode: {mode}')

    def coalition_ensure_fleet(self, event, mode):
        """
        确保切换到指定的舰队模式（单舰队/多舰队）

        Args:
            event (str): 活动名称，如'coalition_20230323'
            mode (str): 目标舰队模式，'single'（单舰队）或'multi'（多舰队）

        Pages:
            in: 舰队准备页面
        """
        # 初始化舰队开关实例
        # is_selector=True：该开关是选择器类型（非普通开关）
        # offset=0：无偏移（精准颜色匹配，避免误判）
        fleet_switch = Switch('FleetMode', is_selector=True, offset=0)

        # 不同活动对应不同的舰队开关按钮，逐个适配
        if event == 'coalition_20230323':
            fleet_switch.add_state('single', FROSTFALL_SWITCH_SINGLE)  # 单舰队按钮
            fleet_switch.add_state('multi', FROSTFALL_SWITCH_MULTI)  # 多舰队按钮
        elif event == 'coalition_20240627':
            fleet_switch.add_state('single', ACADEMY_SWITCH_SINGLE)
            fleet_switch.add_state('multi', ACADEMY_SWITCH_MULTI)
        elif event == 'coalition_20250626':
            fleet_switch.add_state('single', NEONCITY_SWITCH_SINGLE)
            fleet_switch.add_state('multi', NEONCITY_SWITCH_MULTI)
        elif event == 'coalition_20260122':
            fleet_switch.add_state('single', Light_Shadow_Fashion_SWITCH_SINGLE)
            fleet_switch.add_state('multi', Light_Shadow_Fashion_SWITCH_MULTI)
        else:
            # 未定义的活动，输出错误日志并抛出脚本异常
            logger.error(f'FLEET_SWITCH is not defined in event {event}')
            raise ScriptError

        # 执行舰队模式切换操作
        if mode == 'single':
            fleet_switch.set('single', main=self)  # 切换到单舰队
        elif mode == 'multi':
            fleet_switch.set('multi', main=self)  # 切换到多舰队
        else:
            # 未知舰队模式，仅输出警告日志
            logger.warning(f'Unknown coalition fleet mode: {mode}')

    @staticmethod
    def coalition_get_entrance(event, stage):
        """
        根据活动名称和关卡名称，返回对应的关卡入口按钮

        Args:
            event (str): 活动名称，如'coalition_20230323'
            stage (str): 关卡名称，如'tc1'/'area1-normal'

        Returns:
            Button: 关卡入口按钮（包含坐标、截图区域等信息）

        Raises:
            CampaignNameError: 未找到对应活动+关卡的映射时抛出
        """
        # 活动+关卡 到 入口按钮的映射字典（核心配置）
        dic = {
            # 2023年3月23日活动
            ('coalition_20230323', 'tc1'): FROSTFALL_TC1,
            ('coalition_20230323', 'tc2'): FROSTFALL_TC2,
            ('coalition_20230323', 'tc3'): FROSTFALL_TC3,
            ('coalition_20230323', 'sp'): FROSTFALL_SP,
            ('coalition_20230323', 'ex'): FROSTFALL_EX,

            # 2024年6月27日活动
            ('coalition_20240627', 'easy'): ACADEMY_EASY,
            ('coalition_20240627', 'normal'): ACADEMY_NORMAL,
            ('coalition_20240627', 'hard'): ACADEMY_HARD,
            ('coalition_20240627', 'sp'): ACADEMY_SP,
            ('coalition_20240627', 'ex'): ACADEMY_EX,

            # 2025年6月26日活动
            ('coalition_20250626', 'easy'): NEONCITY_EASY,
            ('coalition_20250626', 'normal'): NEONCITY_NORMAL,
            ('coalition_20250626', 'hard'): NEONCITY_HARD,
            ('coalition_20250626', 'sp'): NEONCITY_SP,
            ('coalition_20250626', 'ex'): NEONCITY_EX,

            # 2025年11月20日活动（修改：Light_Shadow_Fashion → DAL）
            ('coalition_20251120', 'area1-normal'): DAL_AREA1,
            ('coalition_20251120', 'area2-normal'): DAL_AREA2,
            ('coalition_20251120', 'area3-normal'): DAL_AREA3,
            ('coalition_20251120', 'area4-normal'): DAL_AREA4,
            ('coalition_20251120', 'area5-normal'): DAL_AREA5,
            ('coalition_20251120', 'area6-normal'): DAL_AREA6,
            ('coalition_20251120', 'area1-hard'): DAL_AREA1,
            ('coalition_20251120', 'area2-hard'): DAL_AREA2,
            ('coalition_20251120', 'area3-hard'): DAL_AREA3,
            ('coalition_20251120', 'area4-hard'): DAL_AREA4,
            ('coalition_20251120', 'area5-hard'): DAL_AREA5,
            ('coalition_20251120', 'area6-hard'): DAL_AREA6,

            # 2026年01月22日活动（修改：DAL → Light_Shadow_Fashion）
            ('coalition_20260122', 'area1-normal'): Light_Shadow_Fashion_AREA1,
            ('coalition_20260122', 'area2-normal'): Light_Shadow_Fashion_AREA2,
            ('coalition_20260122', 'area3-normal'): Light_Shadow_Fashion_AREA3,
            ('coalition_20260122', 'area4-normal'): Light_Shadow_Fashion_AREA4,
            ('coalition_20260122', 'area5-normal'): Light_Shadow_Fashion_AREA5,
            ('coalition_20260122', 'area6-normal'): Light_Shadow_Fashion_AREA6,
            ('coalition_20260122', 'area1-hard'): Light_Shadow_Fashion_AREA1,
            ('coalition_20260122', 'area2-hard'): Light_Shadow_Fashion_AREA2,
            ('coalition_20260122', 'area3-hard'): Light_Shadow_Fashion_AREA3,
            ('coalition_20260122', 'area4-hard'): Light_Shadow_Fashion_AREA4,
            ('coalition_20260122', 'area5-hard'): Light_Shadow_Fashion_AREA5,
            ('coalition_20260122', 'area6-hard'): Light_Shadow_Fashion_AREA6,

        }
        # 统一转为小写（避免大小写不一致导致匹配失败）
        stage = stage.lower()
        try:
            return dic[(event, stage)]  # 返回匹配的关卡入口按钮
        except KeyError as e:
            logger.error(e)  # 输出错误日志
            raise CampaignNameError  # 抛出关卡名称错误异常

    @staticmethod
    def coalition_20251120_get_entrance_difficulty(event, stage):
        """
        专门为2025年11月20日活动，返回对应关卡的难度选择按钮

        Args:
            stage (str): 关卡名称，如'area1-normal'/'area1-hard'

        Returns:
            Button: 难度按钮（普通/困难）

        Raises:
            CampaignNameError: 未找到对应映射时抛出
        """
        dic = {
            # 普通难度
            ('coalition_20251120', 'area1-normal'): DAL_NORMAL,
            ('coalition_20251120', 'area2-normal'): DAL_NORMAL,
            ('coalition_20251120', 'area3-normal'): DAL_NORMAL,
            ('coalition_20251120', 'area4-normal'): DAL_NORMAL,
            ('coalition_20251120', 'area5-normal'): DAL_NORMAL,
            ('coalition_20251120', 'area6-normal'): DAL_NORMAL,
            # 困难难度
            ('coalition_20251120', 'area1-hard'): DAL_HARD,
            ('coalition_20251120', 'area2-hard'): DAL_HARD,
            ('coalition_20251120', 'area3-hard'): DAL_HARD,
            ('coalition_20251120', 'area4-hard'): DAL_HARD,
            ('coalition_20251120', 'area5-hard'): DAL_HARD,
            ('coalition_20251120', 'area6-hard'): DAL_HARD,
            # 普通难度（修改：20251120→20260122；DAL_NORMAL→Light_Shadow_Fashion_NORMAL）
            ('coalition_20260122', 'area1-normal'): Light_Shadow_Fashion_NORMAL,
            ('coalition_20260122', 'area2-normal'): Light_Shadow_Fashion_NORMAL,
            ('coalition_20260122', 'area3-normal'): Light_Shadow_Fashion_NORMAL,
            ('coalition_20260122', 'area4-normal'): Light_Shadow_Fashion_NORMAL,
            ('coalition_20260122', 'area5-normal'): Light_Shadow_Fashion_NORMAL,
            ('coalition_20260122', 'area6-normal'): Light_Shadow_Fashion_NORMAL,
            # 困难难度（修改：20251120→20260122；DAL_HARD→Light_Shadow_Fashion_HARD）
            ('coalition_20260122', 'area1-hard'): Light_Shadow_Fashion_HARD,
            ('coalition_20260122', 'area2-hard'): Light_Shadow_Fashion_HARD,
            ('coalition_20260122', 'area3-hard'): Light_Shadow_Fashion_HARD,
            ('coalition_20260122', 'area4-hard'): Light_Shadow_Fashion_HARD,
            ('coalition_20260122', 'area5-hard'): Light_Shadow_Fashion_HARD,
            ('coalition_20260122', 'area6-hard'): Light_Shadow_Fashion_HARD,
        }
        stage = stage.lower()
        try:
            return dic[(event, stage)]
        except KeyError as e:
            logger.error(e)
            raise CampaignNameError

    @staticmethod
    def coalition_get_battles(event, stage):
        """
        根据活动和关卡，返回该关卡需要进行的战斗次数

        Args:
            event (str): 活动名称
            stage (str): 关卡名称

        Returns:
            int: 战斗次数

        Raises:
            CampaignNameError: 未找到对应映射时抛出
        """
        dic = {
            # 2023年3月23日活动
            ('coalition_20230323', 'tc1'): 1,
            ('coalition_20230323', 'tc2'): 2,
            ('coalition_20230323', 'tc3'): 3,
            ('coalition_20230323', 'sp'): 1,
            ('coalition_20230323', 'ex'): 1,

            # 2024年6月27日活动
            ('coalition_20240627', 'easy'): 1,
            ('coalition_20240627', 'normal'): 2,
            ('coalition_20240627', 'hard'): 3,
            ('coalition_20240627', 'sp'): 4,
            ('coalition_20240627', 'ex'): 5,

            # 2025年6月26日活动
            ('coalition_20250626', 'easy'): 1,
            ('coalition_20250626', 'normal'): 2,
            ('coalition_20250626', 'hard'): 3,
            ('coalition_20250626', 'sp'): 4,
            ('coalition_20250626', 'ex'): 5,

            # 2025年11月20日活动
            ('coalition_20251120', 'area1-normal'): 2,
            ('coalition_20251120', 'area2-normal'): 3,
            ('coalition_20251120', 'area3-normal'): 3,
            ('coalition_20251120', 'area4-normal'): 3,
            ('coalition_20251120', 'area5-normal'): 3,
            ('coalition_20251120', 'area6-normal'): 4,
            ('coalition_20251120', 'area1-hard'): 2,
            ('coalition_20251120', 'area2-hard'): 3,
            ('coalition_20251120', 'area3-hard'): 3,
            ('coalition_20251120', 'area4-hard'): 3,
            ('coalition_20251120', 'area5-hard'): 3,
            ('coalition_20251120', 'area6-hard'): 4,

            # 2026年01月22日活动（原2025年11月20日活动，已替换活动标识）
            ('coalition_20260122', 'area1-normal'): 2,
            ('coalition_20260122', 'area2-normal'): 3,
            ('coalition_20260122', 'area3-normal'): 3,
            ('coalition_20260122', 'area4-normal'): 3,
            ('coalition_20260122', 'area5-normal'): 3,
            ('coalition_20260122', 'area6-normal'): 4,
            ('coalition_20260122', 'area1-hard'): 2,
            ('coalition_20260122', 'area2-hard'): 3,
            ('coalition_20260122', 'area3-hard'): 3,
            ('coalition_20260122', 'area4-hard'): 3,
            ('coalition_20260122', 'area5-hard'): 3,
            ('coalition_20260122', 'area6-hard'): 4,
        }
        stage = stage.lower()
        try:
            return dic[(event, stage)]
        except KeyError as e:
            logger.error(e)
            raise CampaignNameError

    @staticmethod
    def coalition_get_fleet_preparation(event):
        """
        根据活动名称，返回对应的舰队准备页面按钮

        Args:
            event (str): 活动名称

        Returns:
            Button: 舰队准备按钮

        Raises:
            ScriptError: 未定义的活动时抛出
        """
        if event == 'coalition_20230323':
            return FROSTFALL_FLEET_PREPARATION
        elif event == 'coalition_20240627':
            return ACEDEMY_FLEET_PREPARATION  # 注：原代码此处拼写错误（ACEDEMY），保留原逻辑
        elif event == 'coalition_20250626':
            return NEONCITY_FLEET_PREPARATION
        elif event == 'coalition_20251120':
            return DAL_FLEET_PREPARATION
        elif event == 'coalition_20260122':
            return Light_Shadow_Fashion_PREPARATION
        else:
            logger.error(f'FLEET_PREPARATION is not defined in event {event}')
            raise ScriptError

    def handle_fleet_preparation(self, event, stage, mode):
        """
        处理舰队准备逻辑：判断是否需要切换舰队模式，需要则执行切换

        Args:
            event (str): 活动名称
            stage (str): 关卡名称
            mode (str): 目标舰队模式（single/multi）

        Returns:
            bool: True（执行了舰队切换）/False（无需切换）
        """
        stage = stage.lower()

        # 部分关卡无需切换舰队模式，直接返回False
        if event == 'coalition_20230323':
            if stage in ['tc1', 'sp']:
                return False
        if event == 'coalition_20240627':
            if stage in ['easy', 'sp', 'ex']:
                return False
        if event == 'coalition_20250626':
            if stage in ['easy', 'sp', 'ex']:
                return False

        # 需要切换则执行舰队模式切换
        self.coalition_ensure_fleet(event, mode)
        return True

    def coalition_map_exit(self, event):
        """
        从战斗准备/舰队准备页面退出，返回联合活动主页面

        Pages:
            in: 战斗准备页面 / 舰队准备页面
            out: 联合活动主页面
        """
        logger.info('Coalition map exit')
        # 获取当前活动的舰队准备按钮
        fleet_preparation = self.coalition_get_fleet_preparation(event)

        # 循环执行退出操作，直到回到目标页面
        for _ in self.loop():
            # 终止条件：回到联合活动主页面 或 游戏主界面
            if self.in_coalition():
                break
            if self.is_in_main():
                break

            # 场景1：在战斗准备页面 → 点击返回箭头
            if self.appear(BATTLE_PREPARATION, offset=(20, 20), interval=3):
                logger.info(f'{BATTLE_PREPARATION} -> {BACK_ARROW}')
                self.device.click(BACK_ARROW)
                continue
            # 场景2：在舰队准备页面 → 点击舰队准备退出按钮
            if self.appear(fleet_preparation, offset=(20, 20), interval=3):
                logger.info(f'{fleet_preparation} -> {NEONCITY_PREPARATION_EXIT}')
                self.device.click(NEONCITY_PREPARATION_EXIT)
                continue
            # 场景3：在20251120活动的难度选择页面 → 点击难度退出按钮
            if self.appear_then_click(DAL_DIFFICULTY_EXIT, offset=(20, 20), interval=3):
                logger.info(f'{DAL_DIFFICULTY_EXIT} -> {DAL_DIFFICULTY_EXIT}')
                continue
            # 场景4：在20260122活动的难度选择页面 → 点击难度退出按钮
            if self.appear_then_click(Light_Shadow_Fashion_EXIT, offset=(20, 20), interval=3):
                logger.info(f'{Light_Shadow_Fashion_EXIT} -> {Light_Shadow_Fashion_EXIT}')
                continue

    def enter_map(self, event, stage, mode, skip_first_screenshot=True):
        """
        自动化进入指定活动的指定关卡，直到到达战斗准备页面
        核心流程：点击关卡入口 → （可选）选择难度 → 配置舰队 → 进入战斗准备

        Args:
            event (str): 活动名称，如'coalition_20230323'
            stage (str): 关卡名称，如'tc3'/'area1-normal'
            mode (str): 舰队模式，'single'（单舰队）或'multi'（多舰队）
            skip_first_screenshot (bool): 是否跳过首次截图（优化性能）

        Pages:
            in: 联合活动主页面
            out: 战斗准备页面

        Raises:
            RequestHumanTakeover: 点击次数超限/舰队未配置时，请求人工接管
            CampaignNameError: 关卡名称错误时抛出
        """
        # 获取关卡入口按钮
        button = self.coalition_get_entrance(event, stage)
        # 20251120活动需要额外获取难度按钮
        if event in ['coalition_20251120']:
            button_difficulty = self.coalition_20251120_get_entrance_difficulty(event, stage)
        else:
            button_difficulty = None
        button = self.coalition_get_entrance(event, stage)
        # 20251120活动需要额外获取难度按钮
        if event in ['coalition_20260122']:
            button_difficulty = self.coalition_20260122_get_entrance_difficulty(event, stage)
        else:
            button_difficulty = None
        # 获取舰队准备按钮
        fleet_preparation = self.coalition_get_fleet_preparation(event)

        # 初始化计时器（控制点击间隔，避免高频点击）
        campaign_timer = Timer(5)  # 关卡入口点击计时器（5秒间隔）
        campaign_difficulty_timer = Timer(5)  # 难度按钮点击计时器
        fleet_timer = Timer(5)  # 舰队准备按钮点击计时器

        # 初始化点击计数（防止无限点击，触发人工接管）
        campaign_click = 0  # 关卡入口点击次数
        campaign_difficulty_click = 0  # 难度按钮点击次数
        fleet_click = 0  # 舰队准备按钮点击次数

        # 主循环：直到进入战斗准备页面
        while 1:
            # 截图控制：首次跳过（优化性能），后续每次循环都截图
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # ========== 异常检测：点击次数超限（防止卡死） ==========
            if campaign_click > 5:
                logger.critical(f"Failed to enter {button}, too many click on {button}")
                logger.critical("Possible reason #1: You haven't cleared previous stage to unlock the stage.")
                raise RequestHumanTakeover  # 请求人工接管
            if campaign_difficulty_click > 5:
                logger.critical(f"Failed to enter {button_difficulty}, too many click on {button_difficulty}")
                logger.critical("Possible reason #1: The difficulty asset is not correct.")
                raise RequestHumanTakeover
            if fleet_click > 5:
                logger.critical(f"Failed to enter {button}, too many click on FLEET_PREPARATION")
                logger.critical(
                    "Possible reason #1: Your fleets haven't satisfied the stat restrictions of this stage.")
                logger.critical(
                    "Possible reason #2: This stage can only be farmed once a day, but it's the second time that you are entering")
                raise RequestHumanTakeover

            # ========== 异常检测：舰队未配置 ==========
            if self.appear(FLEET_NOT_PREPARED, offset=(20, 20)):
                logger.critical('FLEET_NOT_PREPARED')
                logger.critical('Please prepare you fleets before running coalition battles')
                raise RequestHumanTakeover
            if self.appear(EMPTY_FLAGSHIP, offset=(20, 20)):
                logger.critical('EMPTY_FLAGSHIP, Please prepare you fleets before running coalition battles')
                raise RequestHumanTakeover
            if self.appear(EMPTY_VANGUARD, offset=(20, 20)):
                logger.critical('EMPTY_VANGUARD, Please prepare you fleets before running coalition battles')
                raise RequestHumanTakeover
            if self.appear(Light_Shadow_Fashion_FLEET_NOT_PREPARED, offset=(20, 20)):
                logger.critical('Light_Shadow_Fashion_FLEET_NOT_PREPARED')
                logger.critical('Please prepare you fleets before running coalition battles')
                raise RequestHumanTakeover
            if self.appear(Light_Shadow_Fashion_EMPTY_FLAGSHIP, offset=(20, 20)):
                logger.critical('EMPTY_FLAGSHIP, Please prepare you fleets before running coalition battles')
                raise RequestHumanTakeover
            if self.appear(Light_Shadow_Fashion_EMPTY_VANGUARD, offset=(20, 20)):
                logger.critical('Light_Shadow_Fashion_EMPTY_VANGUARD, Please prepare you fleets before running coalition battles')
                raise RequestHumanTakeover

            # ========== 终止条件：到达战斗准备页面 ==========
            if self.appear(BATTLE_PREPARATION, offset=(20, 20)):
                break

            # ========== 处理各类干扰项（弹窗/剧情等） ==========
            # 处理公会弹窗（取消）
            if self.handle_guild_popup_cancel():
                continue
            # 自动搜索继续
            if self.handle_auto_search_continue():
                campaign_timer.reset()
                continue
            # 处理角色退役弹窗
            if self.handle_retirement():
                continue
            # 处理战斗低情绪提示
            if self.handle_combat_low_emotion():
                continue
            # 处理紧急委托弹窗
            if self.handle_urgent_commission(drop=None):
                continue
            # 跳过剧情
            if self.handle_story_skip():
                campaign_timer.reset()
                continue
            # 自动确认战斗自动化设置
            if self.handle_combat_automation_confirm():
                continue

            # ========== 核心操作：点击关卡入口 ==========
            if campaign_timer.reached() and self.in_coalition():
                self.device.click(button)  # 点击关卡入口
                campaign_click += 1  # 点击次数+1
                campaign_timer.reset()  # 重置计时器
                continue

            # ========== 核心操作：20251120活动点击难度按钮 ==========
            if event in ['coalition_20251120']:
                if campaign_difficulty_timer.reached() and self.in_coalition_20251120_difficulty_selection() and button_difficulty:
                    self.device.click(button_difficulty)  # 点击难度按钮
                    campaign_difficulty_click += 1  # 点击次数+1
                    campaign_difficulty_timer.reset()  # 重置计时器
                    continue
            if event in ['coalition_20260122']:
                if campaign_difficulty_timer.reached() and self.in_coalition_20260122_difficulty_selection() and button_difficulty:
                    self.device.click(button_difficulty)  # 点击难度按钮
                    campaign_difficulty_click += 1  # 点击次数+1
                    campaign_difficulty_timer.reset()  # 重置计时器
                    continue
            # ========== 核心操作：点击舰队准备按钮（并配置舰队） ==========
            if fleet_timer.reached() and self.appear(fleet_preparation, offset=(20, 50)):
                self.handle_fleet_preparation(event, stage, mode)  # 配置舰队模式
                self.device.click(fleet_preparation)  # 点击舰队准备按钮
                fleet_click += 1  # 点击次数+1
                fleet_timer.reset()  # 重置舰队计时器
                campaign_timer.reset()  # 重置关卡入口计时器
                continue
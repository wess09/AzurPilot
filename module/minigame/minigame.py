"""
小游戏自动化模块。

管理学院游戏室（Game Room）中的小游戏自动化流程。
负责游戏券/代币的收集、小游戏选择、游玩和退出。

主要功能：
    - OCR 识别当前代币数量
    - 自动收集游戏代币
    - 导航至游戏室主页
    - 选择并游玩特定小游戏（如新年挑战）
    - 处理弹窗（代币已满、游戏券不足等）

代币机制：
    - 最大代币上限为 40，OCR 超过 40 时截断
    - 代币数量 <= 30 时尝试自动收集
    - 代币为 0 时结束游玩循环
    - 每局游玩后根据配置决定下次游玩时间

依赖关系：
    - MinigameUI: 共享游戏列表与滚动条滑块识别
    - MinigameRun: 小游戏运行基类，定义选择/游玩/退出模板方法
    - Minigame: 主任务类，组合代币管理、游戏室导航和游玩循环

Pages:
    游戏室页面：page_game_room
    学院页面：page_academy
"""

import numpy as np

import module.config.server as server
from module.base.timer import Timer
from module.base.utils import random_rectangle_point
from module.combat.assets import GET_ITEMS_1
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.minigame.assets import *
from module.ocr.ocr import Digit
from module.ui.assets import ACADEMY_GOTO_GAME_ROOM
from module.ui.page import page_academy, page_game_room
from module.ui.scroll import Scroll
from module.ui.ui import UI

if server.server != 'jp':
    OCR_COIN = Digit(COIN_HOLDER,
                    name='OCR_COIN',
                    letter=(255, 235, 115),
                    threshold=128)
else:
    OCR_COIN = Digit(COIN_HOLDER,
                    name='OCR_COIN',
                    letter=(211, 196, 95),
                    threshold=128)


class MinigameScroll(Scroll):
    """小游戏专用滚动条，避免残留开始按钮的白色边框干扰定位。"""

    def cal_position(self, main):
        """按滑块模板计算位置，滑块被遮挡时返回 None。

        Args:
            main (MinigameUI): 持有当前截图的小游戏界面。

        Returns:
            float | None: 归一化位置，0 为顶部，1 为底部；不可见时为 None。
        """
        y = main.minigame_scroll_y()
        if y is None:
            return None
        # 参考资源中的滑块位于轨道顶部，用其中心反推滑块长度。
        reference_y = (MINIGAME_SCROLL_KNOB.area[1] + MINIGAME_SCROLL_KNOB.area[3]) / 2
        self.length = 2 * (reference_y - self.area[1])
        position = (y - reference_y) / (self.total - self.length)
        position = min(max(position, 0.0), 1.0)
        logger.attr(self.name, f'{position:.2f} (knob y={y})')
        return position

    def set(self, position, main, random_range=(-0.05, 0.05), distance_check=True, skip_first_screenshot=True):
        """定位到指定百分比，滑块遮挡时通过滑动卡片恢复。

        Args:
            position (float): 目标位置，0 为顶部，1 为底部。
            main (MinigameUI): 持有当前截图的小游戏界面。
            random_range (tuple): 目标滑块位置的随机偏移范围。
            distance_check (bool): 是否检查滑动距离。
            skip_first_screenshot (bool): 是否复用已有截图。

        Returns:
            int: 实际执行的滑动次数，已在目标位置时为 0。

        Raises:
            RequestHumanTakeover: 达到 8 次滑动或 20 秒仍未确认定位完成。

        Pages:
            in: page_game_room 选游戏界面
            out: page_game_room 选游戏界面
        """
        logger.info(f'{self.name} set to {position}')
        timeout = Timer(20).start()
        interval = Timer(1)
        dragged = 0
        previous = None
        stationary = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()
            current = self.cal_position(main)
            if current is not None and abs(position - current) < self.drag_threshold:
                return dragged
            if dragged >= 8 or timeout.reached():
                raise RequestHumanTakeover('无法定位小游戏滚动条')
            if not interval.reached():
                continue
            if position >= 1 - self.edge_threshold:
                # 底部滑块可能被遮挡，通过连续滑动后卡片不再移动确认到底。
                cards = main.image_crop((300, 110, 600, 500))
                if previous is not None and np.mean(np.abs(cards.astype(float) - previous)) < 1:
                    stationary += 1
                    if stationary >= 2:
                        return dragged
                else:
                    stationary = 0
                previous = cards.astype(float)
                p1, p2 = (600, 550), (600, 250)
            elif current is None:
                # 通过卡片向顶部滚动，直到重新识别到滑块。
                p1, p2 = (600, 250), (600, 550)
            else:
                p1 = random_rectangle_point(self.position_to_screen(current), n=1)
                p2 = random_rectangle_point(self.position_to_screen(position, random_range=random_range), n=1)
            main.device.swipe(p1, p2, name=self.name, distance_check=distance_check)
            dragged += 1
            interval.reset()


MINIGAME_SCROLL = MinigameScroll(MINIGAME_SCROLL_AREA, color=(247, 247, 247), name='MINIGAME_SCROLL')


class MinigameUI(UI):
    """小游戏任务和具体游戏共享的页面识别。"""

    def minigame_scroll_y(self):
        """返回当前截图中的滑块中心纵坐标，遮挡时返回 None。"""
        if self.appear(MINIGAME_SCROLL_KNOB, offset=(-9, -73, 12, 495)):
            return int((MINIGAME_SCROLL_KNOB.button[1] + MINIGAME_SCROLL_KNOB.button[3]) // 2)
        return None

    def minigame_list_appear(self):
        """联合滚动条与卡片标记，正向确认当前截图为游戏列表。"""
        # 两列分别使用自身模板作为横向锚点，并沿纵向搜索滚动后的卡片。
        return MINIGAME_SCROLL.appear(main=self) and (
            self.appear(GAME_LIST_CHECK_LEFT, offset=(5, 500))
            or self.appear(GAME_LIST_CHECK_RIGHT, offset=(5, 500))
        )


class MinigameRun(MinigameUI):
    """
    小游戏运行基类。

    定义小游戏的通用运行流程模板：导航至游戏列表、选择游戏、
    投入代币、游玩、退出。具体游戏逻辑由子类实现。

    子类需要重写以下方法：
        - choose_game(): 从游戏列表中选择目标游戏
        - use_coin(): 投入代币并准备游玩
        - play_game(): 执行游戏的具体操作
        - exit_game(): 退出当前游戏
        - deal_specific_popup(): 处理特定游戏的弹窗

    属性:
        无额外属性，所有状态通过方法参数传递
    """

    def minigame_run(self, skip_first_screenshot=True):
        """执行单次小游戏的进入、选择、投币、游玩与退出流程。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 成功投币并完成游玩返回 True，无法投币或跳过游玩返回 False。

        Pages:
            in: page_game_room 主页
            out: page_game_room 主页或选游戏界面
        """
        logger.hr('[小游戏] 运行', level=1)

        # page_game_room main_page -> MINIGAME_SCROLL
        logger.info("[小游戏] 进入小游戏")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            # 结束判断：列表界面出现
            if self.minigame_list_appear():
                break
            # 处理无法获取更多游戏券等弹窗
            if self.deal_popup():
                continue
            if self.appear_then_click(GOTO_CHOOSE_GAME, offset=(5, 5), interval=3):
                continue

        logger.info("[小游戏] 选择小游戏")
        self.choose_game()
        # 尝试投币，失败则跳过游玩
        add_coin_result = self.use_coin()
        if add_coin_result:
            logger.hr("[小游戏] 游玩", level=2)
            self.play_game()
        logger.info("[小游戏] 退出小游戏")
        self.exit_game()
        return add_coin_result

    def deal_popup(self):
        """处理可能出现的弹窗（代币已满、获得物品等）。

        Returns:
            bool: 成功处理了弹窗返回 True，需要重新截图。
        """
        if self.deal_specific_popup():
            return True
        if self.handle_popup_confirm('TICKETS_FULL'):
            self.interval_reset(COIN_POPUP, interval=3)
            return True
        # 代币超过 31 枚时处理弹窗
        if self.appear_then_click(COIN_POPUP, offset=(5, 5), interval=3):
            return True
        # 收到代币或游戏券
        if self.appear_then_click(GET_ITEMS_1, offset=(5, 5), interval=3):
            return True
        return False

    def deal_specific_popup(self):
        """处理特定小游戏专有的弹窗，由子类重写。

        Returns:
            bool: 是否处理了弹窗。
        """
        return False

    def choose_game(self, skip_first_screenshot=True):
        """在游戏列表中选择目标小游戏，由子类实现。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: page_game_room 选游戏界面
            out: page_game_room 游戏入口界面
        """
        pass

    def use_coin(self, skip_first_screenshot=True):
        """投入代币准备游玩，由子类实现。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 成功投币返回 True，否则返回 False。
        """
        return False

    def play_game(self, skip_first_screenshot=True):
        """执行小游戏的具体游玩操作，由子类实现。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。
        """
        pass

    def exit_game(self, skip_first_screenshot=True):
        """退出当前小游戏返回至游戏室界面，由子类实现。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: page_game_room 游戏结束界面
            out: page_game_room 选游戏界面
        """
        pass


class Minigame(MinigameUI):
    """
    小游戏主任务类。

    管理小游戏任务的完整生命周期：从学院页面导航到游戏室，
    收集代币，选择并游玩小游戏，直到代币耗尽或达到游玩上限。

    流程概要：
        1. 从任意页面导航至学院 -> 游戏室主页
        2. OCR 读取代币数量
        3. 代币 <= 30 时尝试自动收集
        4. 代币 > 0 时选择小游戏并游玩（最多 10 次）
        5. 代币耗尽后调度下次运行

    配置项:
        通过 self.config.task_delay(server_update=True) 调度下次运行

    Pages:
        任务入口页面：任意页面
        任务结束页面：page_game_room
    """

    def get_coin_amount(self, skip_first_screenshot=True):
        """识别当前拥有的游戏代币数量。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            int: 代币数量（上限截断至 40）。

        Pages:
            in: page_game_room 主页
            out: page_game_room 主页
        """
        if not skip_first_screenshot:
            self.device.screenshot()
        amount = OCR_COIN.ocr(self.device.image)
        if amount >= 40:
            amount = 40
        return amount

    def go_to_main_page(self, skip_first_screenshot=True):
        """返回游戏室主界面。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: page_game_room 主页或选游戏界面
            out: page_game_room 主页
        """
        logger.info('[小游戏] 前往主页')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.ui_additional():
                continue
            if self.appear_then_click(COIN_POPUP, offset=(5, 5), interval=2):
                continue
            if self.minigame_list_appear():
                self.appear_then_click(BACK, offset=(5, 5), interval=2)
                continue
            if self.appear(GOTO_CHOOSE_GAME, offset=(5, 5)):
                break

    def collect_coin(self, skip_first_screenshot=True):
        """自动收集游戏室中生成的代币。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 是否成功收集了代币。

        Pages:
            in: page_game_room 主页或选游戏界面
            out: page_game_room 主页
        """
        coin_collected = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.ui_additional():
                continue
            if self.appear_then_click(COIN_POPUP, offset=(5, 5), interval=3):
                continue
            # 游戏室与选游戏界面顶部相同，优先返回游戏室
            if self.minigame_list_appear():
                self.appear_then_click(BACK, offset=(5, 5), interval=3)
                continue
            # 收集代币
            if not coin_collected and self.appear(COIN, offset=(5, 5)):
                self.appear_then_click(COIN, offset=(5, 5), interval=3)
                coin_collected = True
                continue
            if self.appear(GOTO_CHOOSE_GAME, offset=(5, 5)):
                break
        return coin_collected

    def run(self):
        """运行小游戏日常自动化任务。

        导航至学院游戏室，识别并收集代币，循环运行配置的小游戏直至代币耗尽。

        Pages:
            in: 任意页面
            out: page_game_room
        """
        self.ui_ensure(page_academy)
        # page_academy -> page_game_room
        for _ in self.loop():
            if self.ui_page_appear(page_game_room):
                break
            if self.ui_page_appear(page_academy, interval=5):
                self.device.click(ACADEMY_GOTO_GAME_ROOM)
                continue
            # 每月游戏券达到上限时弹窗处理
            if self.handle_popup_confirm('MINIGAME_ENTER'):
                continue

        # 确保回到游戏室主界面
        self.go_to_main_page()
        coin_collected = False
        play_count = 0

        # 选择具体小游戏
        specific_game_name = "new_year_challenge"
        minigame_instance = None
        if specific_game_name == "new_year_challenge":
            from module.minigame.new_year_challenge import NewYearChallenge
            minigame_instance = NewYearChallenge(config=self.config, device=self.device)

        while 1:
            # 游玩次数上限控制
            if play_count >= 10:
                break
            # OCR 获取代币数量
            coin_count = self.get_coin_amount()
            logger.info(f"[小游戏] 游戏币数量: {coin_count}")
            # 收集代币
            if coin_count <= 30 and not coin_collected:
                coin_collected = True
                if self.collect_coin():
                    continue
            # 无代币剩余
            if coin_count == 0:
                logger.info(f"[小游戏] 游戏币数量: {coin_count}, 游玩结束")
                break
            logger.info("[小游戏] 游戏币数量 > 0，消费")
            # 具体小游戏逻辑
            if minigame_instance is not None and minigame_instance.minigame_run():
                play_count += 1
                continue
            elif minigame_instance is None:
                logger.error(f"[小游戏] 未知的游戏名称 {specific_game_name}")
                break
            else:
                break

        self.config.task_delay(server_update=True)

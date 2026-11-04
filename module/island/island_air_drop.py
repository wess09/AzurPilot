"""岛屿空投任务模块。

处理岛屿每日空投领取逻辑，根据上次偷取时间判断是否执行空投流程。
管理空投冷却时间（5小时）与每日重置边界，支持重复尝试与超时跳过。
"""
from module.island.island import *
from time import sleep
from module.ui.scroll import Scroll
from datetime import timedelta
from module.config.time_source import now as current_time
from module.config.utils import get_server_last_update


# 补给气泡在固定位置（与 ISLAND_AIR_DROP_A/B/C 同一区域），白色圆角条
AIR_DROP_BUBBLE_AREA = (800, 378, 1025, 408)
AIR_DROP_BUBBLE_CLICK_LIMIT = 2
# 奖励弹窗（每日补给、获得物品）横跨全屏的白色横带，点下方「点击关闭」处关闭
AIR_DROP_POPUP_CLOSE = Button(area=(560, 588, 720, 612), color=(0, 0, 0), button=(560, 588, 720, 612),
                              name='AIR_DROP_POPUP_CLOSE')
# 国际服「分享剩余补给」邀请窗口：底部两个深蓝按钮（公开邀请 / 全部邀请），右上角 ✕
AIR_DROP_SHARE_DIALOG_BUTTONS = ((470, 585, 640, 615), (685, 585, 855, 615))
AIR_DROP_SHARE_DIALOG_COLOR = (37, 72, 107)
AIR_DROP_SHARE_DIALOG_CLOSE = Button(area=(846, 104, 876, 134), color=(0, 0, 0), button=(846, 104, 876, 134),
                                     name='AIR_DROP_SHARE_DIALOG_CLOSE')


def _color_fraction(image, area, color, threshold=30):
    x1, y1, x2, y2 = area
    region = image[y1:y2, x1:x2].astype(int)
    return float((np.abs(region - np.array(color)).max(axis=2) < threshold).mean())


def air_drop_bubble_appear(image):
    """补给气泡区域大部分为白色。"""
    x1, y1, x2, y2 = AIR_DROP_BUBBLE_AREA
    return float((image[y1:y2, x1:x2].min(axis=2) > 235).mean()) > 0.6


def air_drop_reward_popup_appear(image):
    """奖励弹窗：画面中部横跨全屏的白色横带。"""
    return float((image[300:480, :, :].min(axis=2) > 225).mean()) > 0.9


def air_drop_share_dialog_appear(image):
    """分享补给邀请窗口：底部两个深蓝按钮都在。"""
    return all(_color_fraction(image, area, AIR_DROP_SHARE_DIALOG_COLOR) > 0.5
               for area in AIR_DROP_SHARE_DIALOG_BUTTONS)


class IslandAirDrop(Island):
    """岛屿空投日常任务执行器。"""

    def run(self):
        """执行岛屿空投任务流程。

        包含自己岛屿空投领取、好友岛屿补给拜访、冷却调度与卡死异常处理。
        """
        self.island_error = False
        now = current_time()
        # 每日边界以服务器 0 点为准（换算为本机时间轴）
        today = get_server_last_update('00:00')
        next_daily_time = today + timedelta(days=1, hours=1)  # 服务器次日 01:00
        last_steal_time = self.config.IslandAirDrop_LastSteal
        next_steal_time = now + timedelta(hours=5)
        last_attempt_today = today + timedelta(hours=23)  # 服务器当日 23:00
        if last_steal_time < today:
            self.goto_postmanage()
            if self.appear_then_click(MY_AIR_DROP_ALREADY):
                self.ui_goto(page_island, get_ship=False)
                self.island_air_drop()
                while 1:
                    self.device.screenshot()
                    if self.appear(ISLAND_CHECK):
                        break
                    if self.appear(ISLAND_PHONE_CHECK, offset=1):
                        self.device.click(ISLAND_SEASON_GOTO_ISLAND)
                        continue
                    if self.appear(ISLAND_SEASON_CHECK, offset=1):
                        self.device.click(ISLAND_SEASON_GOTO_ISLAND)
                        continue
                    if self.appear_then_click(AIR_DROP_SKIP, offset=1):
                        self.device.sleep(0.5)
                        continue
                    self.device.sleep(0.5)
                if self.appear(ISLAND_SEASON_CHECK, offset=1):
                    self.device.click(ISLAND_SEASON_GOTO_ISLAND)
                self.device.sleep(1)
                self.island_walk_route('AirDropSelf')
                self.island_air_drop()
        # 是否前往其他玩家岛屿拿补给
        if self.config.IslandAirDrop_VisitOtherIsland:
            has_drops = True
            self.goto_management()
            while 1:
                self.ui_goto(page_island_visit, get_ship=False)
                ocr_air_drop = DigitCounter(
                    OCR_AIR_DROP,
                    name="air_drop",
                    letter=(150, 150, 150),
                    threshold=80,
                    alphabet="0123456789/",
                )
                image = self.device.screenshot()
                number1, number2, number3 = ocr_air_drop.ocr(image)
                if number1 > 0:
                    has_drops = True
                    if self.find_air_drop():
                        self.device.sleep(1)
                        self.run_and_get()
                        self.device.sleep(3)
                        # 每次完成补给后立即重新检测剩余次数，确认消耗是否成功
                        # 因为运行可能失败导致次数没使用成功
                        self.ui_goto(page_island_visit, get_ship=False)
                        ocr_air_drop = DigitCounter(
                            OCR_AIR_DROP,
                            name="air_drop",
                            letter=(150, 150, 150),
                            threshold=80,
                            alphabet="0123456789/",
                        )
                        image = self.device.screenshot()
                        number1, number2, number3 = ocr_air_drop.ocr(image)
                        if number1 > 0:
                            logger.info(
                                f"剩余补给次数: {number1}/{number2}，继续执行好友补给"
                            )
                            continue
                        else:
                            logger.info("[岛屿-每日补给] 补给次数已用尽")
                            has_drops = False
                            break
                    else:
                        break
                else:
                    has_drops = False
                    break
        else:
            logger.info("[岛屿-每日补给] 已禁用拜访其他玩家岛屿，跳过好友补给")
            has_drops = False
        self.config.IslandAirDrop_LastSteal = current_time().replace(microsecond=0)

        if has_drops and next_steal_time < last_attempt_today:
            self.config.task_delay(target=next_steal_time)
        elif has_drops and next_steal_time > last_attempt_today > now:
            self.config.task_delay(target=last_attempt_today)
        else:
            self.config.task_delay(target=next_daily_time)
        if self.island_error:
            from module.exception import GameBugError

            raise GameBugError("检测到岛屿拜访卡死，需要重启")
        self.device.sleep(1)

    def find_air_drop(self):
        """在好友岛屿拜访列表中搜索可用的空投目标。

        Returns:
            bool: 找到并成功进入可用好友岛屿返回 True，未找到或不可用返回 False。
        """
        search_area = (662, 90, 720, 660)
        VISIT_SCROLL = Scroll(
            VISIT_SCROLL_AREA, color=(255, 255, 255), name="VISIT_SCROLL"
        )
        max_swipe_attempts = 15
        swipe_count = 0
        last_attempt_swipe = 1
        while swipe_count <= max_swipe_attempts:
            self.device.screenshot()
            region_image = self.image_crop(search_area, copy=False)
            air_drop_buttons = TEMPLATE_AIR_DROP.match_multi(
                region_image, similarity=0.85, threshold=5, name="air_drop_buttons"
            )

            if not air_drop_buttons:
                logger.info("[岛屿-每日补给] 在指定区域内未找到补给")

                # 检查是否在底部
                if VISIT_SCROLL.at_bottom(main=self) and last_attempt_swipe > 0:
                    last_attempt_swipe -= 1
                    logger.info("[岛屿-每日补给] 滑动槽已在底部，最后尝试滑动")
                    continue
                elif VISIT_SCROLL.at_bottom(main=self) and last_attempt_swipe <= 0:
                    logger.info("[岛屿-每日补给] 滑动槽已在底部，停止搜索")
                    return False
                # 如果还有滑动次数，尝试滑动
                if swipe_count < max_swipe_attempts:
                    logger.info(f"[岛屿-每日补给] 滑动尝试 {swipe_count + 1}/{max_swipe_attempts}")
                    self.visit_swipe(480)
                    swipe_count += 1
                    self.device.sleep(0.5)
                    continue
                else:
                    logger.info("[岛屿-每日补给] 达到最大滑动次数，停止搜索")
                    return False

            logger.info(f"[岛屿-每日补给] 找到 {len(air_drop_buttons)} 个补给目标")
            air_drop_buttons.sort(key=lambda btn: btn.area[1])

            # 标记是否有至少一个可以点击的补给
            has_clickable_air_drop = False

            for air_drop_button in air_drop_buttons:
                air_drop_button_x = air_drop_button.area[0] + search_area[0]
                air_drop_button_y = air_drop_button.area[1] + search_area[1]

                visit_button = self.calculate_visit_position(
                    air_drop_button_x, air_drop_button_y
                )
                if not self.check_visit_friend_island(visit_button):
                    continue
                has_clickable_air_drop = True
                return True
            # 如果当前页面所有补给都不可用（全部skip或timeout）
            if not has_clickable_air_drop:
                logger.info("[岛屿-每日补给] 当前页面没有可用补给目标")
                # 检查是否在底部
                if VISIT_SCROLL.at_bottom(main=self) and last_attempt_swipe > 0:
                    last_attempt_swipe -= 1
                    logger.info("[岛屿-每日补给] 滑动槽已在底部，最后尝试滑动")
                    continue
                elif VISIT_SCROLL.at_bottom(main=self) and last_attempt_swipe <= 0:
                    logger.info("[岛屿-每日补给] 滑动槽已在底部，停止搜索")
                    return False
                # 滑动继续查找
                if swipe_count < max_swipe_attempts:
                    logger.info(f"[岛屿-每日补给] 滑动尝试 {swipe_count + 1}/{max_swipe_attempts}")
                    self.visit_swipe(480)
                    swipe_count += 1
                    self.device.sleep(0.5)
                    continue
                else:
                    logger.info("[岛屿-每日补给] 达到最大滑动次数，停止搜索")
                    return False

            if swipe_count < max_swipe_attempts:
                logger.info(
                    f"所有补给尝试失败，滑动尝试 {swipe_count + 1}/{max_swipe_attempts}"
                )
                self.visit_swipe(480)
                swipe_count += 1
                self.device.sleep(0.5)
                continue

        logger.info("[岛屿-每日补给] 未检测到可用补给")
        return False

    def calculate_visit_position(self, air_drop_button_x, air_drop_button_y):
        """根据空投图标位置计算对应的拜访按钮区域。

        Args:
            air_drop_button_x (int): 空投图标左上角 X 坐标。
            air_drop_button_y (int): 空投图标左上角 Y 坐标。

        Returns:
            Button: 计算得到的拜访按钮实例。
        """
        visit_button_x1 = air_drop_button_x + 225  # x偏移
        visit_button_y1 = air_drop_button_y + 25  # y偏移
        visit_button_width = 73  # 960 - 887 = 73
        visit_button_height = 24  # 302 - 278 = 24
        visit_button_x2 = visit_button_x1 + visit_button_width
        visit_button_y2 = visit_button_y1 + visit_button_height

        visit_button = Button(
            area=(visit_button_x1, visit_button_y1, visit_button_x2, visit_button_y2),
            color=(),
            button=(visit_button_x1, visit_button_y1, visit_button_x2, visit_button_y2),
            name="visit_button",
        )
        return visit_button

    def visit_swipe(self, distance):
        """在好友拜访列表中向上滑动并点击停止滑动惯性。

        Args:
            distance (int): 滑动距离像素值。
        """
        stop_button = Button(
            area=(500, 90, 630, 660),
            color=(),
            button=(500, 90, 630, 660),
            name="stop_button",
        )
        self.device.swipe_vector(
            vector=(0, -distance), box=(500, 90, 630, 660), name="VisitSwipe"
        )
        self.device.click(stop_button)
        self.device.click_record_clear()

    def island_air_drop(self, skip_first_screenshot=False):
        """点击补给气泡（每日补给 / 领取补给 / 好友岛拿补给），关闭奖励弹窗；不点「分享剩余补给」。

        原来在气泡位置连点 6 次：领取后气泡变为「分享剩余补给」，国际服点它会弹出邀请好友窗口，
        后续盲点会落在好友的「邀请」按钮上（气泡区域与第三位好友的邀请按钮重叠）。现在每次点击前
        先看当前画面：奖励弹窗点下方关闭；邀请窗口点右上角 ✕ 关闭、不邀请任何人；气泡已是
        「分享剩余补给」即领取完成；其余气泡最多点 AIR_DROP_BUBBLE_CLICK_LIMIT 次。
        气泡消失（如进入空投动画）且一段时间无变化时退出，动画由调用方处理。

        Returns:
            bool: 是否点击过补给气泡。
        """
        clicked = 0
        click_timer = Timer(1.5)
        idle_timer = Timer(2, count=4).start()
        for image in self.loop(skip_first=skip_first_screenshot, timeout=20):
            if air_drop_share_dialog_appear(image):
                logger.info("[岛屿-空投] 关闭分享补给邀请窗口（不邀请好友）")
                self.device.click(AIR_DROP_SHARE_DIALOG_CLOSE)
                idle_timer.reset()
                continue
            if air_drop_reward_popup_appear(image):
                self.device.click(AIR_DROP_POPUP_CLOSE)
                idle_timer.reset()
                continue
            if self.appear(ISLAND_AIR_DROP_A, offset=(30, 30)):
                logger.info("[岛屿-空投] 补给已领取，气泡为「分享剩余补给」，不点击")
                break
            if air_drop_bubble_appear(image) and clicked < AIR_DROP_BUBBLE_CLICK_LIMIT:
                if click_timer.reached():
                    self.device.click(ISLAND_AIR_DROP_A)
                    clicked += 1
                    click_timer.reset()
                idle_timer.reset()
                continue
            if idle_timer.reached():
                break
        return clicked > 0

    def run_and_get(self):
        """在好友岛屿上跑位寻路并拾取空投补给。

        规则（方向与时长）走岛屿计划全局配置 `IslandPlan.IslandWalk.AirDrop`，
        对所有控制方式生效；拿不到补给时的补滑走 `AirDropRetry`。
        """
        self.island_walk_route('AirDrop')
        self.island_air_drop()
        # 补滑中途要反复检测补给，方向固定为 上/右/下，配置只给每一步的时长
        retry_durations = self.island_walk_composite_durations('AirDropRetry', 3)
        for _ in range(1):
            self.device.screenshot()
            if self.appear(ISLAND_AIR_DROP_ALREADY_GETTED, offset=200):
                break
            self.island_up(retry_durations[0])
            self.island_air_drop()
            self.device.screenshot()
            if self.appear(ISLAND_AIR_DROP_ALREADY_GETTED, offset=200):
                break
            self.island_right(retry_durations[1])
            self.island_air_drop()
            self.device.screenshot()
            if self.appear(ISLAND_AIR_DROP_ALREADY_GETTED, offset=200):
                break
            self.island_down(retry_durations[2])
            self.island_air_drop()
        self.exit_friend_island()

    def test(self):
        """测试 OCR 参数提取效果。"""
        image = self.device.screenshot()
        area = OCR_AIR_DROP.area if hasattr(OCR_AIR_DROP, "area") else OCR_AIR_DROP
        cropped = crop(image, area)

        # 测试不同参数
        letter = (150, 150, 150)
        threshold = 80
        processed = extract_letters(cropped, letter=letter, threshold=threshold)

        # 显示处理后的图像
        cv2.imshow("Processed OCR", processed)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    def test1(self):
        """测试进入岛屿管理页面。"""
        self.goto_management()


if __name__ == "__main__":
    az = IslandAirDrop("alas", task="Alas")
    az.device.screenshot()
    az.test1()

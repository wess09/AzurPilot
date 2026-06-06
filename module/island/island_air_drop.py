from module.island.island import *
from time import sleep
from module.ui.scroll import Scroll

class IslandAirDrop(Island):
    def run(self):
        self.island_error = False
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        next_daily_time = today.replace(hour=1, minute=0, second=0, microsecond=0) + timedelta(days=1)
        last_steal_time = self.config.IslandAirDrop_LastSteal
        next_steal_time = now + timedelta(hours=5)
        last_attempt_today = now.replace(hour=23, minute=0, second=0, microsecond=0)
        if last_steal_time < today:
            self.goto_postmanage()
            if self.appear_then_click(MY_AIR_DROP_ALREADY):
                self.ui_goto(page_island,get_ship=False)
                self.island_air_drop()
                while 1:
                    self.device.screenshot()
                    if self.appear(ISLAND_CHECK):
                        break
                    if self.appear(ISLAND_PHONE_CHECK, offset=1):
                        break
                    if self.appear(ISLAND_SEASON_CHECK, offset=1):
                        self.device.click(ISLAND_SEASON_GOTO_ISLAND)
                        continue
                    if self.appear_then_click(AIR_DROP_SKIP, offset=1):
                        continue
                    self.device.sleep(0.5)
                if self.appear(ISLAND_SEASON_CHECK, offset=1):
                    self.device.click(ISLAND_SEASON_GOTO_ISLAND)
                self.device.sleep(1)
                self.island_down(1000)
                self.island_air_drop()
        has_drops = True
        self.goto_management()
        while 1:
            self.ui_goto(page_island_visit, get_ship=False)
            ocr_air_drop = DigitCounter(OCR_AIR_DROP, name='air_drop', letter=(150, 150, 150), threshold=80,
                                        alphabet='0123456789/')
            image = self.device.screenshot()
            number1,number2,number3 = ocr_air_drop.ocr(image)
            if number1 > 0:
                has_drops = True
                if self.find_air_drop():
                    self.device.sleep(1)
                    self.run_and_get()
                    self.device.sleep(3)
                    # 每次完成补给后立即重新检测剩余次数，确认消耗是否成功
                    # 因为运行可能失败导致次数没使用成功
                    self.ui_goto(page_island_visit, get_ship=False)
                    ocr_air_drop = DigitCounter(OCR_AIR_DROP, name='air_drop', letter=(150, 150, 150), threshold=80,
                                                alphabet='0123456789/')
                    image = self.device.screenshot()
                    number1, number2, number3 = ocr_air_drop.ocr(image)
                    if number1 > 0:
                        logger.info(f"剩余补给次数: {number1}/{number2}，继续执行好友补给")
                        continue
                    else:
                        logger.info("补给次数已用尽")
                        has_drops = False
                        break
                else:
                    break
            else:
                has_drops = False
                break
        self.config.IslandAirDrop_LastSteal = datetime.now().replace(microsecond=0)

        if has_drops and next_steal_time<last_attempt_today:
            self.config.task_delay(target=next_steal_time)
        elif has_drops and next_steal_time>last_attempt_today>now:
            self.config.task_delay(target=last_attempt_today)
        else:
            self.config.task_delay(target=next_daily_time)
        if self.island_error:
            from module.exception import GameBugError
            raise GameBugError("检测到岛屿拜访卡死，需要重启")
        self.device.sleep(1)


    def find_air_drop(self):
        search_area = (662, 90, 720, 660)
        VISIT_SCROLL = Scroll(VISIT_SCROLL_AREA, color=(255, 255, 255), name='VISIT_SCROLL')
        max_swipe_attempts = 15
        swipe_count = 0
        last_attempt_swipe = 1
        while swipe_count <= max_swipe_attempts:
            self.device.screenshot()
            region_image = self.image_crop(search_area, copy=False)
            air_drop_buttons = TEMPLATE_AIR_DROP.match_multi(
                region_image,
                similarity=0.85,
                threshold=5,
                name="air_drop_buttons"
            )

            if not air_drop_buttons:
                logger.info("在指定区域内未找到补给")

                # 检查是否在底部
                if VISIT_SCROLL.at_bottom(main=self) and last_attempt_swipe>0:
                    last_attempt_swipe -= 1
                    logger.info("滑动槽已在底部，最后尝试滑动")
                    continue
                elif VISIT_SCROLL.at_bottom(main=self) and last_attempt_swipe<=0:
                    logger.info("滑动槽已在底部，停止搜索")
                    return False
                # 如果还有滑动次数，尝试滑动
                if swipe_count < max_swipe_attempts:
                    logger.info(f"滑动尝试 {swipe_count + 1}/{max_swipe_attempts}")
                    self.visit_swipe(480)
                    swipe_count += 1
                    self.device.sleep(0.5)
                    continue
                else:
                    logger.info("达到最大滑动次数，停止搜索")
                    return False

            logger.info(f"找到 {len(air_drop_buttons)} 个补给目标")
            air_drop_buttons.sort(key=lambda btn: btn.area[1])

            # 标记是否有至少一个可以点击的补给
            has_clickable_air_drop = False

            for air_drop_button in air_drop_buttons:
                air_drop_button_x = air_drop_button.area[0] + search_area[0]
                air_drop_button_y = air_drop_button.area[1] + search_area[1]

                visit_button = self.calculate_visit_position(air_drop_button_x, air_drop_button_y)
                result = self.check_visit(visit_button)
                if result == "skip":
                    logger.info("无法访问，跳过当前补给")
                    continue
                elif result == "success":
                    logger.info("成功进入拜访状态，返回True")
                    return True
                elif result == "timeout":
                    self.island_error = True
                    return False
                has_clickable_air_drop = True
            # 如果当前页面所有补给都不可用（全部skip或timeout）
            if not has_clickable_air_drop:
                logger.info("当前页面没有可用补给目标")
                # 检查是否在底部
                if VISIT_SCROLL.at_bottom(main=self) and last_attempt_swipe>0:
                    last_attempt_swipe -= 1
                    logger.info("滑动槽已在底部，最后尝试滑动")
                    continue
                elif VISIT_SCROLL.at_bottom(main=self) and last_attempt_swipe<=0:
                    logger.info("滑动槽已在底部，停止搜索")
                    return False
                # 滑动继续查找
                if swipe_count < max_swipe_attempts:
                    logger.info(f"滑动尝试 {swipe_count + 1}/{max_swipe_attempts}")
                    self.visit_swipe(480)
                    swipe_count += 1
                    self.device.sleep(0.5)
                    continue
                else:
                    logger.info("达到最大滑动次数，停止搜索")
                    return False

            if swipe_count < max_swipe_attempts:
                logger.info(f"所有补给尝试失败，滑动尝试 {swipe_count + 1}/{max_swipe_attempts}")
                self.visit_swipe(480)
                swipe_count += 1
                self.device.sleep(0.5)
                continue

        logger.info("未检测到可用补给")
        return False

    def check_visit(self, visit_button):
        number = 20
        self.device.click(visit_button)
        self.device.sleep(5)
        while number:
            self.device.screenshot()
            if self.appear(ISLAND_ACCESS_MAP, offset=1):
                return "success"
            if self.appear(CANT_ACCESS, similarity=0.85):
                return "skip"
            self.device.sleep(1)
            self.device.click(visit_button)
            number -= 1
        return "timeout"

    def calculate_visit_position(self, air_drop_button_x, air_drop_button_y):

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
            name="visit_button"
        )
        return visit_button

    def visit_swipe(self, distance):
        stop_button = Button(
            area=(500, 90, 630, 660),
            color=(),
            button=(500, 90, 630, 660),
            name="stop_button"
        )
        self.device.swipe_vector(vector=(0, -distance), box=(500, 90, 630, 660), name="VisitSwipe")
        self.device.click(stop_button)
        self.device.click_record_clear()



    def island_access_map_check(self):
        while True:
            self.device.screenshot()
            if self.appear(ISLAND_ACCESS_MAP):
                return False
            if self.appear(CANT_ACCESS):
                return True
            self.device.sleep(0.5)

    def island_air_drop(self):
        self.device.click(ISLAND_AIR_DROP_A)
        sleep(0.1)
        self.device.click(ISLAND_AIR_DROP_B)
        sleep(0.1)
        self.device.click(ISLAND_AIR_DROP_C)
        sleep(0.5)
        self.device.click(ISLAND_AIR_DROP_A)
        sleep(0.1)
        self.device.click(ISLAND_AIR_DROP_B)
        sleep(0.1)
        self.device.click(ISLAND_AIR_DROP_C)
    def run_and_get(self):
        self.island_up(3000)
        self.island_right(700)
        self.island_up(2000)
        self.device.click(ISLAND_JUMP)
        self.island_up(1200)
        self.island_right(2000)
        self.island_up(6500)
        self.island_right(1000)
        self.island_up(2300)
        self.island_right(2000)
        self.island_up(4000)
        self.island_right(2600)
        self.island_up(300)
        self.device.click(ISLAND_JUMP)
        self.island_up(1300)
        self.island_air_drop()
        for _ in range(1):
            self.device.screenshot()
            if self.appear(ISLAND_AIR_DROP_ALREADY_GETTED, offset=200):
                break
            self.island_up(500)
            self.island_air_drop()
            self.device.screenshot()
            if self.appear(ISLAND_AIR_DROP_ALREADY_GETTED, offset=200):
                break
            self.island_right(500)
            self.island_air_drop()
            self.device.screenshot()
            if self.appear(ISLAND_AIR_DROP_ALREADY_GETTED, offset=200):
                break
            self.island_down(500)
            self.island_air_drop()
        self.device.click(AIR_DROP_RUN_AWAY)
    def test(self):
        image = self.device.screenshot()
        area = OCR_AIR_DROP.area if hasattr(OCR_AIR_DROP, 'area') else OCR_AIR_DROP
        cropped = crop(image, area)

        # 测试不同参数
        letter = (150, 150, 150)
        threshold = 80
        processed = extract_letters(cropped, letter=letter, threshold=threshold)

        # 显示处理后的图像
        cv2.imshow('Processed OCR', processed)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    def test1(self):
        self.goto_management()

if __name__ == "__main__":
    az =IslandAirDrop('alas', task='Alas')
    az.device.screenshot()
    az.test1()
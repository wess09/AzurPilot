from module.awaken.assets import *
from module.base.timer import Timer
from module.exception import ScriptError
from module.logger import logger
from module.ocr.ocr import Digit
from module.retire.dock import DOCK_EMPTY, Dock
from module.ui.assets import BACK_ARROW
from module.ui.page import page_dock, page_main


class ShipLevel(Digit):
    def after_process(self, result):
        result = super().after_process(result)
        if result < 100 or result > 125:
            logger.warning('Unexpected ship level')
            result = 0
        return result


class Awaken(Dock):
    def _get_button_state(self, button: Button):
        """
        获取指定资源按钮的状态。

        Args:
            button: COST_COIN、COST_CHIP 或 COST_ARRAY 按钮

        Returns:
            bool: 资源充足返回 True，不足返回 False，该资源不需要时返回 None
        """
        # 如果 COST_ARRAY 不存在，COST_COIN 和 COST_CHIP 会右移 54px
        if button.match(self.device.image, offset=(75, 20)):
            # Look down, see if there are red letters
            area = button.button
            area = (area[0], area[3], area[2], area[3] + 60)
            if self.image_color_count(area, color=(214, 53, 33), threshold=180, count=16):
                return False
            else:
                return True
        else:
            return None

    def _get_awaken_cost(self, use_array=False):
        """
        获取觉醒所需资源的状态。

        Args:
            use_array: True 表示觉醒到 125 级，False 表示 120 级

        Returns:
            bool or str:
                True 表示所有所需资源充足，
                False 表示任一资源不足，
                'unexpected_array' 表示不打算使用心智阵列但阵列出现了，
                'invalid' 表示结果无效
        """
        coin = self._get_button_state(COST_COIN)
        chip = self._get_button_state(COST_CHIP)
        array = self._get_button_state(COST_ARRAY)

        logger.attr('AwakenCost', {'coin': coin, 'chip': chip, 'array': array})

        def is_right_moved(button):
            # 如果 COST_ARRAY 不存在，COST_COIN 和 COST_CHIP 会右移 54px
            return button.button[0] - button.area[0] > 20

        # 检查结果是否有效
        if array is not None:
            if not use_array:
                logger.warning('Not going to use array but array presents')
                return 'unexpected_array'
            # 如果需要阵列，金币和芯片应该同时存在
            if coin is not None and not is_right_moved(COST_COIN) \
                    and chip is not None and not is_right_moved(COST_CHIP):
                result = coin and chip and array
                logger.attr('AwakenSufficient', result)
                return result
        else:
            # 如果不需要阵列，金币和芯片应该同时存在且右移
            if coin is not None and is_right_moved(COST_COIN) \
                    and chip is not None and is_right_moved(COST_CHIP):
                result = coin and chip
                logger.attr('AwakenSufficient', result)
                return result

        logger.warning('Invalid awaken cost')
        return 'invalid'

    def handle_awaken_finish(self):
        return self.appear_then_click(AWAKEN_FINISH, offset=(20, 20), interval=1)

    def is_in_awaken(self):
        return SHIP_LEVEL_CHECK.match_luma(self.device.image, similarity=0.7)

    def awaken_popup_close(self, skip_first_screenshot=True):
        logger.info('Awaken popup close')
        self.interval_clear(AWAKEN_CANCEL)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_in_awaken():
                break
            if self.appear_then_click(AWAKEN_CANCEL, offset=(20, 20), interval=3):
                continue
            if self.handle_awaken_finish():
                continue

    def awaken_once(self, use_array=False, skip_first_screenshot=True):
        """
        执行一次觉醒操作。

        Args:
            use_array (bool): 是否使用心智阵列（觉醒到 125 级）
            skip_first_screenshot (bool): 是否跳过首次截图

        Returns:
            str: 结果状态，'no_exp'、'unexpected_array'、'insufficient'、'timeout'、'success'

        Pages:
            in: is_in_awaken
            out: is_in_awaken
        """
        logger.hr('Awaken once', level=2)
        interval = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(AWAKEN_CONFIRM):
                break
            if LEVEL_UP.match_luma(self.device.image):
                logger.info(f'awaken_once ended at {LEVEL_UP}')
                return 'no_exp'
            # 由于随机背景，降低相似度阈值
            if interval.reached() and AWAKENING.match_luma(self.device.image, similarity=0.7):
                self.device.click(AWAKENING)
                interval.reset()
                continue

        logger.info('Get awaken cost')
        timeout = Timer(2, count=6).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            result = self._get_awaken_cost(use_array)
            if result == 'unexpected_array':
                # 这种情况不应该发生
                self.awaken_popup_close()
                return result
            elif result is False:
                logger.info('Insufficient resources to awaken')
                self.awaken_popup_close()
                return 'insufficient'
            elif result is True:
                # 资源充足
                break
            elif result == 'invalid':
                # 重试，同时检查超时
                pass
            else:
                raise ScriptError(f'Unexpected _get_awaken_cost result: {result}')
            if timeout.reached():
                logger.warning('Get awaken cost timeout')
                self.awaken_popup_close()
                return 'timeout'

        # 资源充足，确认觉醒
        logger.info('Awaken confirm')
        self.interval_clear(AWAKEN_CONFIRM)
        # 觉醒弹窗在经验足够时需要 10 秒才出现，点击关闭需要 2 秒
        # 因此此处超时设置较长
        timeout = Timer(30, count=30).start()
        finished = False
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件
            if timeout.reached():
                logger.warning('Awaken confirm timeout')
                self.awaken_popup_close()
                break
            if finished and self.is_in_awaken():
                logger.info('Awaken finished')
                break
            # 点击操作
            if self.appear_then_click(AWAKEN_CONFIRM, offset=(20, 20), interval=3):
                continue
            if self.handle_popup_confirm('AWAKEN'):
                continue
            if self.handle_awaken_finish():
                finished = True
                continue

        self.device.click_record_clear()
        return 'success'

    def get_ship_level(self, skip_first_screenshot=True):
        """
        获取当前舰船的等级。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图

        Returns:
            int: 等级 100~125，出错时返回 0
        """
        ocr = ShipLevel(OCR_SHIP_LEVEL, letter=(255, 255, 255), threshold=128, name='ShipLevel')
        timeout = Timer(2, count=4).start()
        level = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_in_awaken():
                level = ocr.ocr(self.device.image)
                if level > 0:
                    return level
            if timeout.reached():
                logger.warning('get_ship_level timeout')
                return level

    def awaken_ship(self, use_array=False, skip_first_screenshot=True):
        """
        对单艘舰船执行觉醒，直到经验不足或达到目标等级。

        Args:
            use_array (bool): True 表示觉醒到 125 级，False 表示 120 级
            skip_first_screenshot (bool): 是否跳过首次截图

        Returns:
            str: 'level_max'、'insufficient'、'no_exp'、'timeout'

        Pages:
            in: is_in_awaken
            out: is_in_awaken
        """
        logger.hr('Awaken ship', level=1)
        logger.info(f'Awaken ship, use_array={use_array}')

        if use_array:
            stop_level = 125
        else:
            stop_level = 120

        if not skip_first_screenshot:
            self.device.screenshot()

        for _ in range(7):
            level = self.get_ship_level()
            if level > 0:
                if level >= stop_level:
                    logger.info(f'Awaken ship ended at stop_level')
                    return 'level_max'
                else:
                    result = self.awaken_once(use_array)
                    # 'no_exp'、'unexpected_array'、'insufficient'、'timeout'、'success'
                    if result == 'success':
                        continue
                    if result in ['insufficient', 'no_exp']:
                        # 直接返回原始结果
                        return result
                    if result == 'unexpected_array':
                        # 可能只是误入觉醒确认界面，重新执行 awaken_once 会重新检查
                        continue
                    if result == 'timeout':
                        # 获取资源超时，重试应该能修复
                        continue
                    raise ScriptError(f'Unexpected awaken_once result: {result}')
            else:
                # 获取等级超时，请求退出
                return 'timeout'

        # 错误，请求退出
        logger.warning('Too many awaken trial on one ship')
        return 'timeout'

    def awaken_exit(self, skip_first_screenshot=True):
        """
        退出觉醒界面，返回船坞。

        Pages:
            in: is_in_awaken
            out: DOCK_CHECK
        """
        logger.info('Awaken exit')
        interval = Timer(3)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.ui_page_appear(page_dock):
                logger.info(f'Awaken exit at {page_dock}')
                break
            if interval.reached() and self.is_in_awaken():
                logger.info(f'is_in_awaken -> {BACK_ARROW}')
                self.device.click(BACK_ARROW)
                interval.reset()
                continue
            if self.handle_awaken_finish():
                continue
            if self.appear_then_click(AWAKEN_CANCEL, offset=(20, 20), interval=3):
                continue
            if self.is_in_main(interval=5):
                self.device.click(page_main.links[page_dock])
                continue

    def awaken_run(self, use_array=False, favourite=False):
        """
        觉醒船坞中所有舰船，直到资源耗尽。

        Args:
            use_array (bool): True 表示觉醒到 125 级，False 表示 120 级
            favourite (bool): True 表示仅觉醒收藏舰船，False 表示觉醒所有舰船

        Returns:
            str: 'insufficient'、'finish'、'timeout'

        Pages:
            in: Any
            out: page_dock
        """
        logger.hr('Awaken run', level=1)
        self.ui_ensure(page_dock)
        self.dock_favourite_set(enable=favourite, wait_loading=False)
        self.dock_sort_method_dsc_set(wait_loading=False)
        if use_array:
            extra = ['can_awaken_plus']
        else:
            extra = ['can_awaken']
        self.dock_filter_set(extra=extra)

        while 1:
            # 在 page_dock 页面
            if self.appear(DOCK_EMPTY, offset=(20, 20)):
                logger.info('awaken_run finished, no ships to awaken')
                result = 'finish'
                break

            # page_dock -> SHIP_DETAIL_CHECK
            entered = self.dock_enter_first()
            if not entered:
                logger.info('awaken_run finished, no ships to awaken')
                result = 'finish'
                break

            # 在 is_in_awaken 页面
            result = self.awaken_ship(use_array)
            self.awaken_exit()
            # 'insufficient'、'no_exp'、'timeout'
            if result in ['no_exp', 'level_max']:
                # Awaken next ship
                continue
            if result == 'insufficient':
                logger.info('awaken_run finished, resources exhausted')
                break
            if result == 'timeout':
                logger.info(f'awaken_run finished, result={result}')
                break
            raise ScriptError(f'Unexpected awaken_ship result: {result}')

        return result

    def run(self):
        # 优先执行觉醒+（使用心智阵列）
        favourite = self.config.Awaken_Favourite
        if self.config.Awaken_LevelCap == 'level125':
            # 使用心智阵列
            result = self.awaken_run(use_array=True, favourite=favourite)
            # 使用心智芯片
            if result != 'timeout':
                self.awaken_run(favourite=favourite)
        elif self.config.Awaken_LevelCap == 'level120':
            # 使用心智芯片
            self.awaken_run(favourite=favourite)
        else:
            raise ScriptError(f'Unknown Awaken_LevelCap={self.config.Awaken_LevelCap}')

        # 重置船坞筛选器
        logger.hr('Awaken run exit', level=1)
        if favourite:
            self.dock_favourite_set(wait_loading=False)
        self.dock_filter_set(wait_loading=False)

        # 调度下一次运行
        self.config.task_delay(server_update=True)

"""大世界存储管理模块。

管理大世界（Operation Siren）的仓库操作，包括舰船维修箱的
使用与结果判断、仓库物品的滚动浏览以及存储界面的导航逻辑。
提供维修结果枚举（成功/数量不足/超时）用于状态判断。
"""
from enum import Enum
import time

from module.base.timer import Timer
from module.base.utils import area_offset, crop, rgb2gray
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.exception import ScriptError
from module.handler.assets import GET_MISSION, POPUP_CANCEL
from module.logger import logger
from module.os.globe_operation import GlobeOperation
from module.os.globe_zone import ZoneManager
from module.os_handler.assets import *
from module.storage.assets import BOX_USE
from module.ui.scroll import Scroll


class RepairResult(Enum):
    """
    维修操作的结果枚举。

    SUCCESS: 舰船修复成功。
    PACK_INSUFFICIENT: 维修箱数量不足，游戏弹出"道具不足"弹窗。
    TIMEOUT: 超时或遇到未知弹窗，无法确认修复结果。
    """
    SUCCESS = 'success'
    PACK_INSUFFICIENT = 'pack_insufficient'
    TIMEOUT = 'timeout'

SCROLL_STORAGE = Scroll(STORATE_SCROLL, color=(247, 211, 66))


class StorageHandler(GlobeOperation, ZoneManager):
    def is_in_storage(self):
        return self.appear(STORAGE_CHECK, offset=(20, 20))

    def storage_enter(self):
        """
        Pages:
            in: is_in_map, STORAGE_ENTER
            out: STORAGE_CHECK
        """
        logger.info('[大世界-仓库] 进入仓库')
        wait_seconds = 0
        for _ in self.loop():
            # End
            if self.is_in_storage():
                break

            if self.appear(MISSION_CHECK, offset=(20, 20)):
                logger.warning('[大世界-仓库] 误进入情报界面，尝试退出')
                self.ui_click(
                    MISSION_QUIT,
                    check_button=self.is_in_map,
                    offset=(20, 20),
                    skip_first_screenshot=True
                )
                wait_seconds += 1
                time.sleep(wait_seconds)
                continue

            if self.is_in_globe():
                logger.info('[大世界-仓库] 误进入全球地图，尝试返回海域')
                self.os_globe_goto_map()
                wait_seconds += 1
                time.sleep(wait_seconds)
                continue

            if self.appear_then_click(STORAGE_ENTER, offset=(200, 5), interval=3):
                continue
            # A game bug that AUTO_SEARCH_REWARD from the last cleared zone popups
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                continue
            if self.handle_map_event():
                continue

        self.handle_info_bar()

    def storage_quit(self):
        """
        Pages:
            in: STORAGE_CHECK
            out: is_in_map
        """
        logger.info('[大世界-仓库] 退出仓库')
        self.ui_back(STORAGE_ENTER, offset=(200, 5), skip_first_screenshot=True)

    def _storage_item_use(self, button):
        """
        Args:
            button (Button): Item

        Pages:
            in: STORAGE_CHECK
            out: STORAGE_CHECK
        """
        success = False
        get_mission_counter = 0
        self.interval_clear(STORAGE_CHECK)
        self.interval_clear(STORAGE_USE)
        self.interval_clear(GET_ITEMS_1)
        self.interval_clear(GET_ITEMS_2)
        self.interval_clear(GET_ADAPTABILITY)
        self.interval_clear(GET_MISSION)

        for _ in self.loop():
            # Accidentally clicked on an item, having popups for its info
            if self.appear(GET_MISSION, offset=True, interval=2):
                logger.info(f'[大世界-仓库] 使用物品信息 -> {GET_MISSION}')
                self.device.click(GET_MISSION)
                self.interval_reset(STORAGE_CHECK)
                get_mission_counter += 1
                if get_mission_counter >= 3:
                    logger.warning('[大世界-仓库] 可能卡在能量存储设备上，重新检测记录仪物品')
                    break
                continue
            # Item rewards
            if self.appear_then_click(STORAGE_USE, offset=(180, 30), interval=5):
                self.interval_reset(STORAGE_CHECK)
                continue
            if self.appear_then_click(BOX_USE, offset=(180, 30), interval=5):
                self.interval_reset(STORAGE_CHECK)
                success = True
                continue
            if self.appear_then_click(GET_ITEMS_1, interval=5):
                self.interval_reset(STORAGE_CHECK)
                success = True
                continue
            if self.appear_then_click(GET_ITEMS_2, interval=5):
                self.interval_reset(STORAGE_CHECK)
                success = True
                continue
            if self.appear(GET_ADAPTABILITY, offset=5, interval=2):
                self.device.click(CLICK_SAFE_AREA)
                success = True
                continue
            if self.handle_story_skip():
                continue
            # Use item
            if self.appear(STORAGE_CHECK, offset=(20, 20), interval=5):
                self.device.click(button)
                continue

            # End
            if success and self.appear(STORAGE_CHECK, offset=(20, 20)):
                break

    def storage_logger_use_all(self):
        """
        Pages:
            in: STORAGE_CHECK
            out: STORAGE_CHECK, scroll to bottom
        """
        logger.hr('使用所有记录仪')
        for _ in self.loop():
            if SCROLL_STORAGE.appear(main=self):
                SCROLL_STORAGE.set_bottom(main=self, skip_first_screenshot=True)

            image = rgb2gray(self.device.image)
            items = TEMPLATE_STORAGE_LOGGER.match_multi(image, similarity=0.5)
            items.extend(TEMPLATE_STORAGE_LOGGER_UNLOCK.match_multi(image, similarity=0.75))
            logger.attr('记录仪数量', len(items))

            if len(items):
                self._storage_item_use(items[0])
                continue
            else:
                logger.info('[大世界-仓库] 仓库中所有记录仪已使用')
                break

    def logger_use(self):
        logger.hr('使用记录仪')
        self.storage_enter()
        self.storage_logger_use_all()
        self.storage_quit()

    def storage_sample_use_all(self):
        """
        Pages:
            in: STORAGE_CHECK
            out: STORAGE_CHECK, scroll to bottom
        """
        sample_types = [
            TEMPLATE_STORAGE_OFFENSE, TEMPLATE_STORAGE_SURVIVAL, TEMPLATE_STORAGE_COMBAT,
            TEMPLATE_STORAGE_QUALITY_OFFENSE, TEMPLATE_STORAGE_QUALITY_SURVIVAL, TEMPLATE_STORAGE_QUALITY_COMBAT
        ]
        for sample_type in sample_types:
            for _ in self.loop():
                image = rgb2gray(self.device.image)
                items = sample_type.match_multi(image, similarity=0.75)
                logger.attr('样本数量', len(items))

                if len(items):
                    self._storage_item_use(items[0])
                else:
                    break
        logger.info('[大世界-仓库] 仓库中所有样本已使用')

    def tuning_sample_use(self, quit=True):
        logger.hr('使用转化样本')
        self.storage_enter()
        self.storage_sample_use_all()
        if quit:
            self.storage_quit()

    def repair_ship_select(self, button, skip_first_screenshot=True):
        """
        Args:
            button (Button): Ship
            skip_first_screenshot:

        Returns:
            bool: if selected

        Pages:
            in: STORAGE_FLEET_CHOOSE
            out: STORAGE_FLEET_CHOOSE
        """
        # click area above hp bar to avoid click effects
        click_area = (button.area[0] + 40, button.area[1] - 100, button.area[2] - 10, button.area[3] - 50)
        click_button = Button(area=click_area, color=(0, 0, 0), button=click_area, name='STORAGE_SHIP_SELECT')
        timeout = Timer(5, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            image = self.image_crop(area_offset(button.area, (0, 10)), copy=False)
            # End
            # blue background for area below hp bar means ship selected
            if self.image_color_count(image, color=(93, 148, 203), count=300):
                logger.info('[大世界-仓库] 仓库舰船已选择')
                self.interval_clear(STORAGE_FLEET_CHOOSE)
                return True
            if timeout.reached():
                logger.warning('[大世界-仓库] 等待仓库舰船选择超时')
                self.interval_clear(STORAGE_FLEET_CHOOSE)
                return False

            if self.appear(STORAGE_FLEET_CHOOSE, offset=(20, 20), interval=2):
                self.device.click(click_button)
                continue

    def repair_pack_use_confirm(self, button, skip_first_screenshot=True):
        """
        Args:
            button (Button): Ship
            skip_first_screenshot:

        Returns:
            RepairResult:
                RepairResult.SUCCESS          — 舰船修复成功（或满血无需修复）。
                RepairResult.PACK_INSUFFICIENT — 维修箱耗尽，游戏弹出"道具不足"弹窗。
                RepairResult.TIMEOUT          — 超时或遇到未知弹窗，无法确认修复结果。

        Pages:
            in: STORAGE_FLEET_CHOOSE
            out: STORAGE_FLEET_CHOOSE
        """
        self.interval_clear(POPUP_CANCEL)
        self.device.click_record_clear()
        # 超时保护：维修箱耗尽时游戏弹出"道具不足"弹窗，若未被识别则超时退出
        timeout = Timer(15, count=30).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            image = self.image_crop(area_offset(button.area, (0, 10)), copy=False)
            # End - ship fixed (blue selection background disappeared)
            if self.appear(STORAGE_REPAIR_CONFIRM, offset=(20, 20)) and \
                    not self.image_color_count(image, color=(93, 148, 203), count=300):
                logger.info('[大世界-仓库] 舰船已修复')
                return RepairResult.SUCCESS
            # End - ship already at full HP
            if self.handle_popup_cancel('STORAGE_REPAIR_FULL_CANCEL'):
                logger.info('[大世界-仓库] 无需修复此舰船')
                return RepairResult.SUCCESS
            # 处理"道具不足"弹窗：维修箱数量不足时游戏弹出此提示，需点击取消退出
            # 截图显示弹窗标题为"信息 INFORMATION"，内容为"道具不足"，底部有取消按钮
            if self.appear_then_click(POPUP_CANCEL, offset=(20, 20), interval=2):
                logger.warning('[大世界处理-存储] 维修包不足（道具不足），跳过此舰船')
                return RepairResult.PACK_INSUFFICIENT
            # 超时保护：防止未知弹窗导致死循环
            if timeout.reached():
                logger.warning('[大世界-仓库] 维修包使用确认超时，未知弹窗或卡住状态')
                return RepairResult.TIMEOUT

            if self.appear_then_click(STORAGE_REPAIR_CONFIRM, offset=(20, 20)):
                continue

    def repair_pack_use(self, button):
        """
        Select a ship that needs to be repaired, then use repair packs.

        Args:
            button (Button): Ship

        Returns:
            RepairResult: Result of the repair attempt, propagated from repair_pack_use_confirm().
                RepairResult.SUCCESS          — 舰船修复成功（或满血无需修复）。
                RepairResult.PACK_INSUFFICIENT — 维修箱耗尽，游戏弹出"道具不足"弹窗，
                                                 调用方应停止继续修理后续舰船。
                RepairResult.TIMEOUT          — 超时或遇到未知弹窗，无法确认修复结果，
                                                 调用方可选择跳过该艘继续尝试。

        Pages:
            in: STORAGE_FLEET_CHOOSE
            out: STORAGE_FLEET_CHOOSE
        """
        self.repair_ship_select(button)
        return self.repair_pack_use_confirm(button)

    def storage_repair_cancel(self):
        """
        Pages:
            in: STORAGE_FLEET_CHOOSE
            out: STORAGE_CHECK
        """
        self.ui_click(STORAGE_REPAIR_CANCEL, STORAGE_CHECK, retry_wait=2, skip_first_screenshot=True)

    def _storage_coordinate_checkout(self, button, types=('OBSCURE',)):
        """
        Args:
            button (Button): Item
            types (tuple[str]):

        Pages:
            in: STORAGE_CHECK
            out: is_in_map, in an obscure zone, or STORAGE_FLEET_CHOOSE.
        """
        self.interval_clear([
            STORAGE_CHECK,
            STORAGE_COORDINATE_CHECKOUT
        ])
        self.popup_interval_clear()
        for _ in self.loop():
            if self.appear(STORAGE_CHECK, offset=(30, 30), interval=5):
                self.device.click(button)
                continue
            if self.appear_then_click(STORAGE_COORDINATE_CHECKOUT, offset=(30, 30), interval=5):
                self.interval_reset(STORAGE_CHECK)
                continue
            if self.handle_popup_confirm('STORAGE_CHECKOUT'):
                # Submarine popup
                continue

            # End
            if self.is_zone_pinned():
                break
            if types[0] == 'REPAIR_PACK' and self.appear(STORAGE_FLEET_CHOOSE, offset=(20, 20)):
                return

        self.zone_type_select(types)
        self.globe_enter(zone=self.name_to_zone(72))

    @staticmethod
    def _storage_item_to_template(item):
        """
        Args:
            item (str): 'OBSCURE', 'ABYSSAL' or 'REPAIR_PACK'.

        Returns:
            Template:
        """
        if item == 'OBSCURE':
            return TEMPLATE_STORAGE_OBSCURE
        elif item == 'ABYSSAL':
            return TEMPLATE_STORAGE_ABYSSAL
        elif item == 'REPAIR_PACK':
            return TEMPLATE_STORAGE_REPAIR_PACK
        else:
            raise ScriptError(f'Unknown storage item: {item}')

    def storage_checkout_item(self, item, skip_obscure_hazard_2=False, skip_first_screenshot=True):
        """
        Args:
            item (str): 'OBSCURE', 'ABYSSAL' or 'REPAIR_PACK'.
            skip_obscure_hazard_2: if skip hazard 2 obscure
            skip_first_screenshot:

        Returns:
            bool: If checkout

        Pages:
            in: STORAGE_CHECK
            out: is_in_map, in an obscure/abyssal zone if checkout.
                 is_in_map, in previous zone if no more obscure/abyssal coordinates.
                 STORAGE_FLEET_CHOOSE, for using repair packs.
        """
        logger.hr('仓库物品取出')
        if SCROLL_STORAGE.appear(main=self):
            if item == 'REPAIR_PACK':
                # repair packs always at the bottom page
                SCROLL_STORAGE.set_bottom(main=self, skip_first_screenshot=skip_first_screenshot)
            else:
                SCROLL_STORAGE.set_top(main=self, skip_first_screenshot=skip_first_screenshot)

        confirm_timer = Timer(0.6, count=2).start()
        for _ in self.loop():
            image = rgb2gray(self.device.image)
            items = self._storage_item_to_template(item).match_multi(image, similarity=0.75)
            logger.attr(f'仓库_{item}', len(items))

            if len(items):
                for button in items:
                    if skip_obscure_hazard_2:
                        crop_image = crop(image, area_offset(button.area, (-25, -35)), copy=False)
                        if TEMPLATE_STORAGE_OBSCURE_HAZARD_2.match(crop_image, similarity=0.92):
                            continue
                    self._storage_coordinate_checkout(button, types=(item,))
                    return True
            if confirm_timer.reached():
                logger.info(f'[大世界-仓库] 仓库中没有更多 {item} 物品')
                self.storage_quit()
                return False

    def storage_get_next_item(self, item, use_logger=True, skip_obscure_hazard_2=False):
        """
        Args:
            item (str): 'OBSCURE', 'ABYSSAL' or 'REPAIR_PACK'.
            use_logger: If use all loggers.
            skip_obscure_hazard_2: if skip hazard 2 obscure

        Returns:
            bool: If checkout

        Pages:
            in: in_map
            out: is_in_map, in an obscure/abyssal zone if checkout.
                 is_in_map, in previous zone if no more obscure/abyssal coordinates.
                 STORAGE_FLEET_CHOOSE, for using repair packs.
        """
        logger.hr('[大世界处理-存储] 获取下一个隐秘海域')
        self.storage_enter()
        if use_logger:
            self.storage_logger_use_all()

        result = self.storage_checkout_item(item, skip_obscure_hazard_2=skip_obscure_hazard_2)
        return result

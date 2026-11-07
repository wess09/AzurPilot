"""自动装备模块，提供舰船装备的快速更换功能。
通过 OCR 识别和模板匹配，在船坞界面自动完成装备筛选、选择和装备操作，
支持批量更换和按方案配装。"""

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from module.config.config import TaskEnd
from module.base.button import Button, ButtonGrid
from module.equipment.equipment import SWIPE_AREA, SWIPE_DISTANCE, SWIPE_RANDOM_RANGE
from module.ui.switch import Switch
from module.exception import ScriptError
from module.base.runtime_params import AUTO_EQUIP_AFTER_EQUIP_WAIT
from module.config.utils import read_run_param
from module.logger import logger
from module.retire.assets import SHIP_DETAIL_CHECK
from module.retire.dock import Dock
from module.ui.page import page_dock


AUTO_EQUIP_QUICK_CHANGE = Button(
    area=(1035, 86, 1128, 116),
    color=(90, 125, 185),
    button=(1035, 86, 1128, 116),
    name='AUTO_EQUIP_QUICK_CHANGE',
)

AUTO_EQUIP_QUICK_CHANGE_CHECK = Button(
    area=(1048, 90, 1119, 111),
    color=(239, 174, 117),
    button=(1048, 90, 1119, 111),
    name='AUTO_EQUIP_QUICK_CHANGE_CHECK',
)

AUTO_EQUIP_EQUIPPING_CLICK = Button(
    area=(1035, 245, 1127, 272),
    color=(117, 128, 161),
    button=(1035, 245, 1127, 272),
    name='AUTO_EQUIP_EQUIPPING_CLICK',
)

AUTO_EQUIP_EQUIPPING_ON = Button(
    area=(1035, 248, 1059, 268),
    color=(175, 182, 202),
    button=(1035, 245, 1127, 272),
    name='AUTO_EQUIP_EQUIPPING_ON',
)

AUTO_EQUIP_EQUIPPING_OFF = Button(
    area=(1035, 246, 1066, 270),
    color=(187, 187, 187),
    button=(1035, 245, 1127, 272),
    name='AUTO_EQUIP_EQUIPPING_OFF',
)

AUTO_EQUIP_EQUIPMENT_SLOT_ROW = Button(
    area=(695, 127, 1113, 200),
    color=(141, 133, 137),
    button=(695, 127, 1113, 200),
    name='AUTO_EQUIP_EQUIPMENT_SLOT_ROW',
)

AUTO_EQUIP_EQUIPMENT_SLOT_GRID = ButtonGrid(
    origin=(695, 127),
    delta=(86.25, 0),
    button_shape=(73, 73),
    grid_shape=(5, 1),
    name='AUTO_EQUIP_EQUIPMENT_SLOT',
)
AUTO_EQUIP_EQUIPMENT_SLOTS = AUTO_EQUIP_EQUIPMENT_SLOT_GRID.buttons

AUTO_EQUIP_WAREHOUSE_FIRST = Button(
    area=(704, 293, 788, 377),
    color=(196, 176, 123),
    button=(704, 293, 788, 377),
    name='AUTO_EQUIP_WAREHOUSE_FIRST',
)

AUTO_EQUIP_WAREHOUSE_SECOND = Button(
    area=(790, 293, 874, 377),
    color=(196, 176, 122),
    button=(790, 293, 874, 377),
    name='AUTO_EQUIP_WAREHOUSE_SECOND',
)

AUTO_EQUIP_WAREHOUSE_FIRST_DISABLED = Button(
    area=(713, 302, 779, 368),
    color=(63, 56, 42),
    button=(704, 293, 788, 377),
    name='AUTO_EQUIP_WAREHOUSE_FIRST_DISABLED',
)

AUTO_EQUIP_SWIPE = 'AUTO_EQUIP_SWIPE'
AUTO_EQUIP_EMPTY_SLOT_PLUS_TEMPLATE_FILE = Path(__file__).with_name('empty_slot_plus.png')
AUTO_EQUIP_EMPTY_SLOT_PLUS_SIMILARITY = 0.8
AUTO_EQUIP_NO_EQUIPMENT_TEMPLATE_FILE = Path(__file__).with_name('no_equipment.png')
AUTO_EQUIP_NO_EQUIPMENT_SIMILARITY = 0.85
AUTO_EQUIP_NO_EQUIPMENT_SEARCH_AREA = (695, 282, 1238, 622)
# 换装后等待时长走 WebUI「运行参数」页（RunParams.UiWait），
# 默认值集中在 module/base/runtime_params.py（界面等待域）。
AUTO_EQUIP_CLICK_RECORD_NAMES = (
    AUTO_EQUIP_QUICK_CHANGE.name,
    AUTO_EQUIP_EQUIPPING_CLICK.name,
    AUTO_EQUIP_WAREHOUSE_FIRST.name,
    AUTO_EQUIP_WAREHOUSE_SECOND.name,
    AUTO_EQUIP_SWIPE,
    *(slot.name for slot in AUTO_EQUIP_EQUIPMENT_SLOTS),
)


@lru_cache(maxsize=1)
def auto_equip_empty_slot_plus_template():
    """加载装备槽空位加号模板。

    Returns:
        np.ndarray: 加号灰度模板图像。

    Raises:
        ScriptError: 模板文件加载失败。
    """
    template = cv2.imread(str(AUTO_EQUIP_EMPTY_SLOT_PLUS_TEMPLATE_FILE), cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise ScriptError(f'Unable to load {AUTO_EQUIP_EMPTY_SLOT_PLUS_TEMPLATE_FILE}')
    return template


@lru_cache(maxsize=1)
def auto_equip_no_equipment_template():
    """加载无装备提示模板。

    Returns:
        np.ndarray: 无装备灰度模板图像。

    Raises:
        ScriptError: 模板文件加载失败。
    """
    template = cv2.imread(str(AUTO_EQUIP_NO_EQUIPMENT_TEMPLATE_FILE), cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise ScriptError(f'Unable to load {AUTO_EQUIP_NO_EQUIPMENT_TEMPLATE_FILE}')
    return template


auto_equip_equipping_filter = Switch('Auto_equip_equipping_filter')
auto_equip_equipping_filter.add_state(
    'on',
    check_button=AUTO_EQUIP_EQUIPPING_ON,
    click_button=AUTO_EQUIP_EQUIPPING_CLICK,
)
auto_equip_equipping_filter.add_state(
    'off',
    check_button=AUTO_EQUIP_EQUIPPING_OFF,
    click_button=AUTO_EQUIP_EQUIPPING_CLICK,
)


class AutoEquip(Dock):
    """自动装备任务处理器。

    在船坞详情界面自动为舰船装配空缺装备槽，支持批量遍历与槽位过滤。
    """

    def _should_stop(self):
        """检查是否收到外部停止信号。

        Returns:
            bool: 是否需要停止任务。
        """
        event = getattr(self.config, 'stop_event', None)
        return event is not None and event.is_set()

    def _quick_change_appear(self):
        """判断当前是否位于一键换装界面。

        Returns:
            bool: 是否检测到一键换装界面标志。
        """
        return self.appear(AUTO_EQUIP_QUICK_CHANGE_CHECK)

    def _open_quick_change(self):
        """打开一键换装界面。

        Pages:
            in: SHIP_DETAIL_CHECK
            out: AUTO_EQUIP_QUICK_CHANGE_CHECK

        Raises:
            ScriptError: 超时未能打开一键换装界面。
        """
        logger.info('打开一键换装')
        for _ in self.loop(timeout=10):
            if self._quick_change_appear():
                return

            if self.appear(SHIP_DETAIL_CHECK, offset=(30, 30), interval=2):
                self.device.click(AUTO_EQUIP_QUICK_CHANGE)
                continue
            if self.handle_popup_confirm('AUTO_EQUIP_QUICK_CHANGE'):
                continue
            if self.handle_game_tips():
                continue
        else:
            raise ScriptError('Unable to open quick equipment change')

    def _quick_equipping_set(self, enable=True):
        """设置一键换装界面的「已装备」筛选状态。

        Args:
            enable (bool): 是否启用已装备筛选。
        """
        target = 'on' if enable else 'off'
        current = auto_equip_equipping_filter.get(main=self)
        logger.attr('自动装备筛选', current)
        if current == target:
            return
        if current == 'unknown':
            logger.warning('无法确定一键换装筛选状态')
            return

        self.device.click(AUTO_EQUIP_EQUIPPING_CLICK)
        self.wait_until_stable(AUTO_EQUIP_EQUIPPING_CLICK)

    def _auto_equip_click_record_clear(self):
        """清理自动换装相关的点击记录。"""
        for name in AUTO_EQUIP_CLICK_RECORD_NAMES:
            self.device.click_record_remove(name)

    def _quick_change_next(self):
        """在一键换装界面滑动切换到下一艘舰船。"""
        logger.info('滑动到下一艘舰船')
        self._auto_equip_click_record_clear()
        self.device.swipe_vector(
            vector=(-SWIPE_DISTANCE, 0),
            box=SWIPE_AREA.area,
            random_range=SWIPE_RANDOM_RANGE,
            padding=0,
            duration=(0.1, 0.12),
            name=AUTO_EQUIP_SWIPE,
        )
        self._auto_equip_click_record_clear()
        self.wait_until_stable(SWIPE_AREA)

    @staticmethod
    def _warehouse_first_unavailable(image):
        """检测仓库首个装备槽位是否被禁用或不可用。

        Args:
            image (np.ndarray): 当前游戏截图。

        Returns:
            bool: 亮度偏低表示禁用不可用。
        """
        x1, y1, x2, y2 = AUTO_EQUIP_WAREHOUSE_FIRST_DISABLED.area
        crop = image[y1:y2, x1:x2, :3].astype(np.float32)
        luma = 0.299 * crop[:, :, 0] + 0.587 * crop[:, :, 1] + 0.114 * crop[:, :, 2]
        return bool(luma.mean() < 90)

    @staticmethod
    def _empty_slot_plus_score(image, slot):
        """计算指定装备槽位是否为空槽加号的匹配得分。

        Args:
            image (np.ndarray): 当前游戏截图。
            slot (Button): 装备槽位按钮。

        Returns:
            float: 模板匹配归一化相关系数得分。
        """
        x1, y1, x2, y2 = slot.area
        crop = image[y1:y2, x1:x2, :3]
        crop = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        result = cv2.matchTemplate(crop, auto_equip_empty_slot_plus_template(), cv2.TM_CCOEFF_NORMED)
        return float(result.max())

    def _enabled_equipment_slots(self):
        """获取当前配置启用的装备槽位列表。

        Returns:
            list[Button]: 启用的装备槽位按钮列表。
        """
        slots = []
        for index, slot in enumerate(AUTO_EQUIP_EQUIPMENT_SLOTS, start=1):
            if getattr(self.config, f'AutoEquip_EnableSlot{index}', True):
                slots.append(slot)

        logger.attr('启用的装备槽', [slot.name for slot in slots])
        return slots

    def _quick_empty_equipment_slots(self):
        """检测并返回当前舰船所有未穿戴装备的槽位。

        Returns:
            list[Button]: 匹配得分达到阈值的空槽位按钮列表。
        """
        empty_slots = []
        scores = []
        for slot in self._enabled_equipment_slots():
            score = self._empty_slot_plus_score(self.device.image, slot)
            scores.append(f'{slot.name}:{score:.3f}')
            if score >= AUTO_EQUIP_EMPTY_SLOT_PLUS_SIMILARITY:
                empty_slots.append(slot)

        logger.attr('空槽加号得分', scores)
        return empty_slots

    @staticmethod
    def _warehouse_no_equipment_score(image):
        """计算仓库区域无可用装备提示的模板匹配得分。

        Args:
            image (np.ndarray): 当前游戏截图。

        Returns:
            float: 模板匹配得分。
        """
        x1, y1, x2, y2 = AUTO_EQUIP_NO_EQUIPMENT_SEARCH_AREA
        crop = image[y1:y2, x1:x2, :3]
        crop = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        result = cv2.matchTemplate(crop, auto_equip_no_equipment_template(), cv2.TM_CCOEFF_NORMED)
        return float(result.max())

    def _warehouse_no_equipment(self):
        """判断仓库中是否有可供当前槽位选择的装备。

        Returns:
            bool: 为 True 表示仓库中无可用装备。
        """
        score = self._warehouse_no_equipment_score(self.device.image)
        logger.attr('无装备得分', f'{score:.3f}')
        return score >= AUTO_EQUIP_NO_EQUIPMENT_SIMILARITY

    def _quick_fill_slot_from_warehouse(self, slot):
        """从仓库选择装备填入指定槽位。

        Args:
            slot (Button): 目标装备槽位。

        Returns:
            bool: 填充成功返回 True，无可用装备返回 False。
        """
        self.device.click(slot)
        self.wait_until_stable(AUTO_EQUIP_WAREHOUSE_FIRST)
        self.device.screenshot()
        if self._warehouse_no_equipment():
            logger.info(f'[自动装备] {slot.name} 无可用装备')
            return False

        if self._warehouse_first_unavailable(self.device.image):
            logger.info(f'[自动装备] 从仓库第二件装备填充 {slot.name}')
            self.device.click(AUTO_EQUIP_WAREHOUSE_SECOND)
        else:
            logger.info(f'[自动装备] 从仓库第一件装备填充 {slot.name}')
            self.device.click(AUTO_EQUIP_WAREHOUSE_FIRST)
        self.device.sleep(read_run_param(
            self.config, 'UiWait_AutoEquipAfterEquipWait',
            AUTO_EQUIP_AFTER_EQUIP_WAIT, 1, 30))
        self.wait_until_stable(AUTO_EQUIP_EQUIPMENT_SLOT_ROW)
        return True

    def _fill_current_ship_equipment(self):
        """为当前舰船自动装配所有启用的空装备槽。"""
        logger.hr('自动换装当前舰船', level=2)
        self._auto_equip_click_record_clear()
        try:
            self._open_quick_change()
            self._quick_equipping_set(enable=False)
            self.equipment_change_logic()
        finally:
            self._auto_equip_click_record_clear()

    def equipment_change_logic(self):
        """遍历空装备槽并执行装配逻辑。

        Raises:
            TaskEnd: 收到停止信号时提前终止任务。
        """
        logger.info('填充空装备槽')
        filled = 0
        skipped = 0
        self.device.screenshot()
        empty_slots = self._quick_empty_equipment_slots()
        logger.attr('空装备槽', [slot.name for slot in empty_slots])

        for slot in empty_slots:
            if self._should_stop():
                raise TaskEnd('AutoEquip stopped')

            if self._quick_fill_slot_from_warehouse(slot):
                filled += 1
            else:
                skipped += 1

        logger.attr('已填充装备槽', filled)
        logger.attr('跳过的空槽', skipped)

    def _ship_limit(self):
        """读取配置中换装舰船数量上限。

        Returns:
            int: 舰船数量上限，0 表示持续运行直至手动停止。
        """
        value = getattr(self.config, 'AutoEquip_ShipLimit', 0)
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 0
        return max(value, 0)

    def run(self):
        """执行自动换装任务主循环。

        Pages:
            in: Any
            out: page_dock

        Raises:
            TaskEnd: 任务停止信号触发。
        """
        logger.hr('自动换装', level=1)
        limit = self._ship_limit()
        logger.attr('舰船上限', '手动停止' if limit == 0 else limit)
        if limit == 0:
            logger.warning('舰船上限为0，自动换装将持续到手动停止')

        self.ui_ensure(page_dock)
        if not self.dock_enter_first(non_npc=True):
            logger.info('无舰船可换装')
            return

        count = 0
        while 1:
            if self._should_stop():
                raise TaskEnd('AutoEquip stopped')

            count += 1
            logger.attr('舰船', count)
            self._fill_current_ship_equipment()

            if limit and count >= limit:
                logger.info('达到舰船上限')
                break

            self._quick_change_next()

import numpy as np

from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.base.utils import rgb2gray, lower_template_match_similarity
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.exception import ScriptError
from module.logger import logger
from module.ocr.ocr import Digit
from module.retire.assets import EQUIP_CONFIRM, EQUIP_CONFIRM_2
from module.shop.assets import AMOUNT_MINUS, AMOUNT_PLUS
from module.statistics.item import ItemGrid
from module.storage.assets import *
from module.storage.ui import StorageUI
from module.ui.assets import BACK_ARROW, STORAGE_CHECK
from module.ui.scroll import Scroll

MATERIAL_SCROLL = Scroll(METERIAL_SCROLL, color=(247, 211, 66))

EQUIPMENT_GRIDS = ButtonGrid(origin=(140, 88), delta=(159, 178), button_shape=(124, 124),
                             grid_shape=(7, 3), name='EQUIPMENT')
EQUIPMENT_ITEMS = ItemGrid(EQUIPMENT_GRIDS, templates={}, amount_area=(90, 98, 123, 123))
OCR_DISASSEMBLE_COUNT = Digit(DISASSEMBLE_COUNT_OCR, letter=(235, 235, 235))


class StorageFull(Exception):
    """仓库已满异常，当装备/材料仓库无剩余空间时抛出。"""
    pass


class StorageHandler(StorageUI):
    """仓库操作处理器，提供开箱、拆解装备等仓库管理功能。

    继承 StorageUI 获取仓库页面导航能力。
    """
    storage_has_boxes = True

    @staticmethod
    def _storage_box_template(rarity):
        """根据稀有度返回对应的装备箱模板。

        Args:
            rarity: 装备箱稀有度等级，1=T1, 2=T2, 3=T3, 4=T4。

        Returns:
            对应稀有度的 TEMPLATE_BOX_T* 模板对象。

        Raises:
            ScriptError: 传入未知的稀有度等级时抛出。
        """
        if rarity == 1:
            return TEMPLATE_BOX_T1
        if rarity == 2:
            return TEMPLATE_BOX_T2
        if rarity == 3:
            return TEMPLATE_BOX_T3
        if rarity == 4:
            return TEMPLATE_BOX_T4
        else:
            raise ScriptError(f'Unknown box template rarity: {rarity}')

    def _handle_use_box_amount(self, amount):
        """设置开箱数量。

        通过 OCR 读取当前数量，然后点击 +/- 按钮调整到目标值。
        如果箱子数量不足，实际设置值可能小于期望值。

        Args:
            amount: 期望设置的开箱数量。

        Returns:
            int: 实际设置的开箱数量，当箱子不足时可能小于期望值。

        Pages:
            in: SHOP_BUY_CONFIRM_AMOUNT
        """
        logger.info(f'Set box amount')

        ocr = Digit(BOX_AMOUNT_OCR, letter=(239, 239, 239), name='OCR_SHOP_AMOUNT')
        index_offset = (40, 50)

        # 等待 +/- 按钮出现
        timeout = Timer(1, count=3).start()
        for _ in self.loop():
            # +/- 按钮可能位置偏移，使用 OCR 偏移量匹配
            if self.appear(AMOUNT_MINUS, offset=index_offset) and self.appear(AMOUNT_PLUS, offset=index_offset):
                break
            if timeout.reached():
                logger.warning('Wait AMOUNT_MINUS AMOUNT_PLUS timeout')
                break

        # 等待 OCR 读取到合理数值
        current = 0
        timeout = Timer(1, count=3).start()
        for _ in self.loop():
            current = ocr.ocr(self.device.image)
            if 1 <= current <= amount + 10:
                break
            if timeout.reached():
                logger.warning('Wait box amount timeout')
                break

        # 通过多点击 +/- 按钮设置目标数量，类似 ui_ensure_index
        logger.info(f'Set box amount: {amount}')
        skip_first = True
        retry = Timer(1, count=2)
        click_count = 0
        for _ in self.loop():
            if skip_first:
                skip_first = False
            else:
                current = ocr.ocr(self.device.image)
            diff = amount - current
            if diff == 0:
                break
            if click_count >= 2:
                logger.warning(f'Box amount stuck at {current}, '
                               f'requested {amount} but only {current} available')
                break

            if retry.reached():
                button = AMOUNT_PLUS if diff > 0 else AMOUNT_MINUS
                self.device.multi_click(button, n=abs(diff), interval=(0.1, 0.2))
                click_count += 1
                retry.reset()

        logger.info(f'Box amount set to {current}')
        return current

    def _storage_use_one_box(self, button, amount=1):
        """使用一个装备箱。

        在材料页面点击指定箱子，确认使用，处理开箱结果和装备满仓弹窗。
        流程：点击箱子 -> 确认使用 -> 设置数量 -> 确认数量 -> 处理获得物品 -> 确认装备。

        Args:
            button: 要点击的装备箱 Button 对象。
            amount: 期望开箱数量，默认为 1。

        Returns:
            int: 实际使用的箱子数量，不完全精确。

        Raises:
            StorageFull: 装备仓库已满无法继续开箱时抛出。

        Pages:
            in: MATERIAL_CHECK
            out: MATERIAL_CHECK
        """
        logger.hr('Use one box')
        success = False
        used = 0
        self.interval_clear([
            MATERIAL_CHECK,
            BOX_USE,
            GET_ITEMS_1,
            GET_ITEMS_2,
            EQUIPMENT_FULL,
            BOX_AMOUNT_CONFIRM,
            EQUIP_CONFIRM,
            EQUIP_CONFIRM_2,
        ])

        for _ in self.loop():
            # 退出条件：已完成开箱且回到材料页面
            if success and self._storage_in_material() and not self.appear(EQUIP_CONFIRM_2, offset=(20, 20)):
                break

            # 开箱流程
            if self._storage_in_material(interval=5):
                self.device.click(button)
                continue
            if self.appear_then_click(BOX_USE, offset=(-330, -20, 20, 20), interval=5):
                self.interval_reset(MATERIAL_CHECK)
                continue
            if self.appear(GET_ITEMS_1, offset=(5, 5), interval=5):
                logger.info(f'{GET_ITEMS_1} -> {MATERIAL_ENTER}')
                self.device.click(MATERIAL_ENTER)
                self.interval_reset(MATERIAL_CHECK)
                continue
            if self.appear(GET_ITEMS_2, offset=(5, 5), interval=5):
                logger.info(f'{GET_ITEMS_2} -> {MATERIAL_ENTER}')
                self.device.click(MATERIAL_ENTER)
                self.interval_reset(MATERIAL_CHECK)
                continue
            # 使用 match_template_color 匹配 BOX_AMOUNT_CONFIRM
            # 开箱动画会遮盖确认按钮，需要模板颜色匹配
            if self.match_template_color(BOX_AMOUNT_CONFIRM, offset=(20, 20), interval=5):
                actual = self._handle_use_box_amount(amount)
                self.device.click(BOX_AMOUNT_CONFIRM)
                self.interval_reset(BOX_AMOUNT_CONFIRM)
                used = actual
                continue
            if self.appear_then_click(EQUIP_CONFIRM, offset=(20, 20), interval=5):
                self.interval_reset(MATERIAL_CHECK)
                continue
            if self.appear_then_click(EQUIP_CONFIRM_2, offset=(20, 20), interval=5):
                # GET_ITEMS_* 弹出较慢，需要重置其 interval
                self.interval_reset(MATERIAL_CHECK)
                self.interval_clear([GET_ITEMS_1, GET_ITEMS_2])
                # 流程：EQUIP_CONFIRM_2 -> GET_ITEMS -> _storage_in_material
                # 标记 EQUIP_CONFIRM_2 为最后一步
                success = True
                continue

            # 仓库已满处理
            if self.appear(EQUIPMENT_FULL, offset=(20, 20)):
                logger.info('Storage full')
                # 关闭弹窗后抛出异常
                self.ui_click(MATERIAL_ENTER, check_button=self._storage_in_material, appear_button=EQUIPMENT_FULL,
                              retry_wait=3, skip_first_screenshot=True)
                raise StorageFull

        logger.info(f'Used {used} box(es)')
        return used

    def _storage_use_box_in_page(self, rarity, amount, skip_first_screenshot=False):
        """在当前材料页面使用指定稀有度的装备箱。

        通过模板匹配在页面中查找指定稀有度的箱子并逐个使用，
        直到达到目标数量或页面中无更多箱子。

        Args:
            rarity: 装备箱稀有度等级，1=T1, 2=T2, 3=T3。
            amount: 期望使用的箱子数量。
            skip_first_screenshot: 是否跳过首次截图复用上一状态的截图。

        Returns:
            int: 实际使用的箱子数量，不完全精确。

        Pages:
            in: MATERIAL_CHECK
            out: MATERIAL_CHECK
        """
        used = 0
        timeout = Timer(1.5, count=3).start()
        while 1:
            logger.attr('Used', f'{used}/{amount}')
            if used >= amount:
                logger.info('Reached target amount, stop')
                break
            if timeout.reached():
                logger.info('No more boxes on this page, stop')
                break

            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            image = rgb2gray(self.device.image)
            sim, box_button = self._storage_box_template(rarity).match_result(image)
            if sim > lower_template_match_similarity(0.9):
                used += self._storage_use_one_box(box_button, amount)
                continue
            else:
                logger.info('No boxes found')
                continue

        return used

    def _storage_use_box_execute(self, rarity=1, amount=10):
        """执行开箱操作，支持翻页查找箱子。

        根据稀有度定位页面起始位置（T1 在底部，其他在顶部），
        逐页查找并使用箱子，直到达到目标数量或无更多箱子。

        Args:
            rarity: 装备箱稀有度等级，1=T1, 2=T2, 3=T3。
            amount: 最多使用的箱子数量。

        Returns:
            int: 实际使用的箱子数量，不完全精确。

        Raises:
            StorageFull: 装备仓库已满时抛出。

        Pages:
            in: page_storage, material, MATERIAL_CHECK
            out: page_storage, material, MATERIAL_CHECK
        """
        logger.hr('Use Box', level=2)
        used = 0

        if MATERIAL_SCROLL.appear(main=self):
            if rarity == 1:
                # T1 箱子始终在列表底部
                MATERIAL_SCROLL.set_bottom(main=self)
            else:
                MATERIAL_SCROLL.set_top(main=self)

            while 1:
                logger.hr('Use boxes in page')
                used += self._storage_use_box_in_page(rarity=rarity, amount=max(amount - used, 0))
                if used >= amount:
                    break
                if MATERIAL_SCROLL.at_bottom(main=self):
                    logger.info('Scroll bar reached end, stop')
                    break
                MATERIAL_SCROLL.next_page(main=self)
        else:
            logger.hr('Use boxes in page')
            used += self._storage_use_box_in_page(rarity=rarity, amount=amount)

        return used

    def _storage_disassemble_equipment_execute_once(self, amount=40):
        """执行一次装备拆解操作。

        在拆解页面中选取装备并确认拆解。最多选取 40 件装备。
        流程：选取装备 -> 确认拆解 -> 处理弹窗 -> 等待结果。

        Args:
            amount: 最多拆解的装备数量，上限为 40。

        Returns:
            int: 实际拆解的装备数量。

        Pages:
            in: DISASSEMBLE_CANCEL
            out: DISASSEMBLE_CANCEL
        """
        success = False
        amount = min(amount, 40)
        self.interval_clear([
            DISASSEMBLE_CONFIRM,
            DISASSEMBLE_POPUP_CONFIRM,
            GET_ITEMS_1,
            GET_ITEMS_2,
            DISASSEMBLE_CANCEL,
        ])
        logger.info(f'Disassemble once, expected amount: {amount}')

        for _ in self.loop():
            if self.appear(GET_ITEMS_1, offset=(5, 5), interval=3):
                logger.info(f'{GET_ITEMS_1} -> {DISASSEMBLE_CONFIRM}')
                self.device.click(DISASSEMBLE_CONFIRM)
                continue
            if self.appear(GET_ITEMS_2, offset=(5, 5), interval=3):
                logger.info(f'{GET_ITEMS_2} -> {DISASSEMBLE_CONFIRM}')
                self.device.click(DISASSEMBLE_CONFIRM)
                continue
            if self.handle_info_bar():
                continue
            if self.appear(DISASSEMBLE_CANCEL, offset=(20, 20)):
                break
        self.interval_clear([
            GET_ITEMS_1,
            GET_ITEMS_2,
        ])
        self.wait_until_stable(MATERIAL_STABLE_CHECK)

        items = EQUIPMENT_ITEMS.predict(self.device.image, name=False, amount=True)
        if not len(items):
            logger.warning('No items in storage to disassemble')
            return 0
        cumsum = np.cumsum([item.amount for item in items])
        for item, total in zip(items, cumsum):
            if item.amount <= 0:
                continue
            self.device.click(item)
            self.device.click_record.pop()
            if total >= amount:
                amount = total
                break
        amount = min(cumsum[-1], amount)

        # 等待装备被选中
        logger.info(f'Disassemble once, in_storage amount: {amount}')
        timeout = Timer(1, count=2).start()
        prev_disassemble = 0
        while 1:
            self.device.screenshot()
            disassembled = OCR_DISASSEMBLE_COUNT.ocr(self.device.image)
            if disassembled >= amount:
                logger.info('Disassemble amount reached expected amount')
                break
            if timeout.reached():
                logger.warning('Wait disassemble amount timeout')
                break
            if disassembled > prev_disassemble:
                prev_disassemble = disassembled
                timeout.reset()

        logger.info(f'Disassemble once, actual amount: {disassembled}')
        if disassembled <= 0:
            logger.warning('No items selected to disassemble')
            return 0

        skip_first_screenshot = True
        click_count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if click_count >= 3:
                # 可能是因为没有选中装备，
                # _storage_disassemble_equipment_execute() 会重新选取
                logger.warning('Failed to confirm disassemble after 3 trial')
                disassembled = 0
                break
            if success and self.appear(DISASSEMBLE_CANCEL, offset=(20, 20)):
                self.wait_until_stable(MATERIAL_STABLE_CHECK)
                break

            if self.appear_then_click(DISASSEMBLE_CONFIRM, offset=(20, 20), interval=5):
                click_count += 1
                continue
            if self.appear_then_click(DISASSEMBLE_POPUP_CONFIRM, offset=(-15, -5, 5, 70), interval=5):
                # 2025.05.20 起拆解不再弹出 GET_ITEMS 页面
                success = True
                continue
            if self.handle_popup_confirm('DISASSEMBLE'):
                continue
            if self.appear(GET_ITEMS_1, offset=(5, 5), interval=3):
                logger.info(f'{GET_ITEMS_1} -> {DISASSEMBLE_CONFIRM}')
                self.device.click(DISASSEMBLE_CONFIRM)
                success = True
                continue
            if self.appear(GET_ITEMS_2, offset=(5, 5), interval=3):
                logger.info(f'{GET_ITEMS_2} -> {DISASSEMBLE_CONFIRM}')
                self.device.click(DISASSEMBLE_CONFIRM)
                success = True
                continue

        return disassembled

    def _storage_disassemble_equipment_execute(self, rarity=1, amount=40):
        """执行装备拆解，支持翻页循环拆解直到达到目标数量。

        设置装备筛选条件后，逐页拆解装备直到达到目标数量或装备列表为空。

        Args:
            rarity: 装备稀有度筛选，1=普通, 2=稀有, 3=精锐, 4=超稀有, 5=最高稀有。
            amount: 期望拆解的装备数量，实际数量 >= 期望值。

        Returns:
            int: 实际拆解的装备数量。

        Pages:
            in: page_storage, equipment, DISASSEMBLE
            out: page_storage, equipment, DISASSEMBLE
        """
        disassembled = 0
        self.equipment_filter_set(rarity=rarity)
        if MATERIAL_SCROLL.appear(main=self):
            MATERIAL_SCROLL.set_top(main=self)

        while 1:
            logger.hr('Disassemble once')
            logger.attr('Disassembled', f'{disassembled}/{amount}')
            if self.appear(EQUIPMENT_EMPTY, offset=(20, 20)):
                logger.info('Equipment list empty, stop')
                break
            if disassembled >= amount:
                logger.info('Reached target amount, stop')
                break

            if amount - disassembled < 40:
                disassembled += self._storage_disassemble_equipment_execute_once(amount=amount - disassembled)
            else:
                disassembled += self._storage_disassemble_equipment_execute_once()

        self.equipment_filter_set()
        return disassembled

    def storage_disassemble_equipment(self, rarity=1, amount=15):
        """拆解指定数量的装备。

        优先拆解已有装备，不足时开箱获取更多装备后继续拆解。
        如果箱子用完或仓库已满无法继续则停止。

        Args:
            rarity: 装备稀有度筛选，1=普通, 2=稀有, 3=精锐, 4=超稀有。
            amount: 期望拆解的装备数量，实际数量 >= 期望值。

        Returns:
            int: 实际拆解的装备数量。

        Pages:
            in: Any
            out: page_storage, equipment, DISASSEMBLE
        """
        logger.hr('Disassemble Equipment', level=2)
        self.ui_goto_storage()
        # 装备中开关不影响拆解，无需设置；筛选确认会自动等待仓库稳定
        disassembled = 0
        while 1:
            logger.attr('Total_Disassemble', f'{disassembled}/{amount}')
            if disassembled >= amount:
                logger.info('Reached total target amount, stop')
                break

            self._storage_enter_material()
            try:
                boxes = self._storage_use_box_execute(rarity=rarity, amount=amount - disassembled)
                if boxes <= 0:
                    logger.warning('No more boxes to use, disassemble equipment end')
                    self.storage_has_boxes = False
                    break
                # 2025.05.20 起箱中装备会自动拆解
                disassembled += boxes
                # 开箱成功，重新检查总量
                continue
            except StorageFull:
                pass
            # 仓库已满，进入拆解流程
            self._storage_enter_disassemble()
            equip = self._storage_disassemble_equipment_execute(rarity=rarity, amount=amount)
            disassembled += equip
            if equip <= 0:
                logger.warning('StorageFull but unable to disassemble, '
                               'probably because storage is full of rare equipments or above, '
                               'disassemble equipment end')
                logger.warning('Please manually disassemble some equipments to free up storage')
                self.storage_has_boxes = False
                break

        return disassembled

    def storage_use_box(self, rarity=1, amount=40):
        """使用装备箱并处理仓库满仓。

        进入仓库材料页面使用箱子，当仓库满时自动拆解装备腾出空间后继续。
        如果箱子用完或仓库满且无法拆解则停止。

        Args:
            rarity: 装备箱稀有度等级，1=普通, 2=稀有, 3=精锐, 4=超稀有。
            amount: 最多使用的箱子数量。

        Returns:
            int: 实际使用的箱子数量。

        Pages:
            in: Any
            out: page_storage, material, MATERIAL_CHECK
        """
        logger.hr('Use boxes', level=2)
        self.ui_goto_storage()
        self._storage_enter_material()
        self._wait_until_storage_stable()

        used = 0
        while 1:
            self._storage_enter_disassemble()
            self._storage_disassemble_equipment_execute(rarity=rarity, amount=amount)

            logger.attr('Total_Used', f'{used}/{amount}')
            if used >= amount:
                logger.info('Reached total target amount, stop')
                break

            boxes = 0
            try:
                self._storage_enter_material()
                boxes = self._storage_use_box_execute(rarity=rarity, amount=amount - used)
                used += boxes
                if boxes <= 0:
                    logger.warning('No more boxes to use, use boxes end')
                    self.storage_has_boxes = False
                    break
            except StorageFull:
                if boxes <= 0:
                    logger.warning('Unable to use boxes because storage full, '
                                   'probably because storage is full of rare equipments or above, '
                                   'use boxes end')
                    logger.warning('Please manually disassemble some equipments to free up storage')
                    self.storage_has_boxes = False
                    break

        return used

    def handle_storage_full(self, rarity=1, amount=40):
        """处理装备仓库满仓弹窗。

        检测 EQUIPMENT_FULL 弹窗并自动拆解装备腾出空间。
        处理完成后返回到弹窗出现前的页面。

        Args:
            rarity: 拆解时使用的装备稀有度筛选，1=普通, 2=稀有, 3=精锐, 4=超稀有。
            amount: 期望拆解的装备数量，实际数量 >= 期望值。

        Returns:
            bool: 是否检测到并处理了满仓弹窗。

        Pages:
            in: 任意页面，当 EQUIPMENT_FULL 出现时自动处理
            out: 处理满仓弹窗前所在页面
        """
        if not self.appear(EQUIPMENT_FULL, offset=(30, 30), interval=2):
            return False

        # 检测到 EQUIPMENT_FULL 弹窗，进入拆解流程
        logger.info('handle_storage_full')
        self.ui_click(EQUIPMENT_FULL, check_button=DISASSEMBLE_CANCEL, skip_first_screenshot=True, retry_wait=3)
        disassembled = self._storage_disassemble_equipment_execute(rarity=rarity, amount=amount)
        if disassembled <= 0:
            logger.warning('Storage full but unable to disassemble any equipment')

        # 退出拆解页面，返回之前的页面
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(DISASSEMBLE_CANCEL, offset=(30, 30), interval=3):
                continue
            if self.appear(DISASSEMBLE, offset=(30, 30), interval=3):
                self.device.click(BACK_ARROW)
                continue

            # 已离开仓库页面
            if not self.appear(STORAGE_CHECK, offset=(30, 30)):
                break

        return True

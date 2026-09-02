# 此文件处理游戏中各种限时共斗（Raid）活动关卡。
# 负责自动识别活动类型、管理入场券消耗、处理不同难度的入场逻辑，并实现了专用的 Raid 战斗流程及 PT 获取记录。
"""
突袭（Raid）活动核心处理模块。

处理游戏中各种限时共斗活动关卡，包括：
- 突袭活动名称到资源前缀的映射（raid_name_shorten）
- 各难度入口按钮和 OCR 识别器的工厂函数（raid_entrance、raid_ocr、pt_ocr）
- 突袭战斗准备、入场、执行和结束的完整流程
- 入场券使用确认弹窗处理
- PT 积分 OCR 读取和停止条件判断

支持的突袭活动：ESSEX、SURUGA、BRISTOL、IRIS、ALBION、KUYBYSHEY、
GORIZIA、HUANCHANG、RPG、CHIENWU、CHANGWU、DARENWU。
"""
import cv2
import numpy as np

import module.config.server as server
from module.base.timer import Timer
from module.campaign.campaign_event import CampaignEvent
from module.combat.assets import *
from module.exception import ScriptError
from module.logger import logger
from module.map.map_operation import MapOperation
from module.ocr.ocr import Digit, DigitCounter
from module.raid.assets import *
from module.raid.combat import RaidCombat
from module.ui.page import page_raid, page_rpg_stage, page_campaign_menu
from module.log_res import LogRes


class RaidCounterPostMixin(DigitCounter):
    """
    突袭计数器后处理混入类。

    对 OCR 识别结果进行后处理修正，修复如 "915/"、"1515" 等
    OCR 误识别结果，将其还原为正确的 "X/15" 格式。
    用于 CHANGWU 等新突袭活动。
    """

    def after_process(self, result):
        # 修正如 "915/"、"1515" 这类 OCR 误识别结果
        result = result.strip('/')
        if result.isdigit() and len(result) > 2 and result.endswith('15'):
            result = f'{result[:-2]}/15'
        return result


class RaidCounter(DigitCounter):
    """
    突袭计数器 OCR 识别器。

    在预处理阶段对图像进行上下白色填充（padding），以提高
    OCR 对数字/分隔符的识别准确率。用于旧突袭活动（ESSEX、SURUGA、BRISTOL）。
    """

    def pre_process(self, image):
        image = super().pre_process(image)
        image = np.pad(image, ((2, 2), (0, 0)), mode='constant', constant_values=255)
        return image


class HuanChangCounter(Digit):
    """
    环昌突袭活动"春节骚动"的剩余次数显示为纵向排列，
    OCR 仅识别上半部分数字。
    """

    def ocr(self, image, direct_ocr=False):
        result = super().ocr(image, direct_ocr)
        return (result, 0, 15)


class HuanChangPtOcr(Digit):
    """
    环昌突袭活动 PT 积分 OCR 识别器。

    通过连通域分析过滤非数字区域，仅保留面积大于 60 的连通域作为有效数字，
    以处理环昌活动特殊背景干扰问题。
    """
    def pre_process(self, image):
        """
        预处理 PT 图像：灰度化、二值化、连通域分析，过滤掉非数字区域。

        Args:
            image (np.ndarray): 输入图像，形状 (height, width, channel)。

        Returns:
            np.ndarray: 处理后的二值图像，形状 (height, width)。
        """
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        image = cv2.threshold(image, 128, 255, cv2.THRESH_BINARY_INV)[1]
        count, cc = cv2.connectedComponents(image)
        # 计算连通域面积，大于 60 的视为数字
        # CN/JP 背景最右侧连通但 EN 不连通，因此需要同时排除 [0,-1] 和 [-1,-1]
        num_idx = [i for i in range(1, count + 1) if
                   i != cc[0, -1] and i != cc[-1, -1] and np.count_nonzero(cc == i) > 60]
        image = ~(np.isin(cc, num_idx) * 255)  # 数字为白色，需要反转
        return image.astype(np.uint8)


def raid_name_shorten(name):
    """
    将突袭活动名称转换为按钮资源名称前缀。

    Args:
        name (str): 突袭活动名称，如 raid_20200624、raid_20210708。

    Returns:
        str: 按钮资源名称前缀，如 ESSEX、SURUGA。
    """
    if name == 'raid_20200624':
        return 'ESSEX'
    elif name == 'raid_20210708':
        return 'SURUGA'
    elif name == 'raid_20220127':
        return 'BRISTOL'
    elif name == 'raid_20220630':
        return 'IRIS'
    elif name == "raid_20221027":
        return "ALBION"
    elif name == "raid_20230118":
        return "KUYBYSHEY"
    elif name == "raid_20230629":
        return "GORIZIA"
    elif name == "raid_20240130":
        return "HUANCHANG"
    elif name == "raid_20240328":
        return "RPG"
    elif name == 'raid_20250116':
        return 'CHIENWU'
    elif name == 'raid_20260212':
        return 'CHANGWU'
    elif name == 'raid_20260827':
        return 'BIGSHOT'
    else:
        raise ScriptError(f'Unknown raid name: {name}')


def raid_entrance(raid, mode):
    """
    根据突袭活动名称和难度，获取对应的入口按钮资源。

    Args:
        raid (str): 突袭活动名称，如 raid_20200624、raid_20210708。
        mode (str): 难度模式，easy、normal 或 hard。

    Returns:
        Button: 对应难度的入口按钮。
    """
    key = f'{raid_name_shorten(raid)}_RAID_{mode.upper()}'
    try:
        return globals()[key]
    except KeyError:
        raise ScriptError(f'Raid entrance asset not exists: {key}')


def raid_ocr(raid, mode):
    """
    根据突袭活动名称和难度，获取对应的 OCR 识别器实例。

    Args:
        raid (str): 突袭活动名称，如 raid_20200624、raid_20210708。
        mode (str): 难度模式，easy、normal、hard 或 ex。

    Returns:
        DigitCounter: 对应的 OCR 识别器（DigitCounter 或 Digit）。
    """
    raid = raid_name_shorten(raid)
    key = f'{raid}_OCR_REMAIN_{mode.upper()}'
    try:
        button = globals()[key]
    except KeyError:
        raise ScriptError(f'Raid entrance asset not exists: {key}')
    # 旧突袭活动使用 RaidCounter 以兼容旧 OCR 模型和资源
    # 新突袭活动使用 DigitCounter
    if raid == 'ESSEX':
        return RaidCounter(button, letter=(57, 52, 255), threshold=128)
    elif raid == 'SURUGA':
        return RaidCounter(button, letter=(49, 48, 49), threshold=128)
    elif raid == 'BRISTOL':
        return RaidCounter(button, letter=(214, 231, 219), threshold=128)
    elif raid == 'IRIS':
        # 该字体不在 azur_lane 模型中，因此使用通用 OCR 模型
        if server.server == 'en':
            # EN 服务器使用粗体
            return RaidCounter(button, letter=(148, 138, 123), threshold=80, lang='cnocr')
        if server.server == 'jp':
            return RaidCounter(button, letter=(148, 138, 123), threshold=128, lang='cnocr')
        else:
            return DigitCounter(button, letter=(148, 138, 123), threshold=128, lang='cnocr')
    elif raid == "ALBION":
        return DigitCounter(button, letter=(99, 73, 57), threshold=128)
    elif raid == 'KUYBYSHEY':
        if mode == 'ex':
            return Digit(button, letter=(189, 203, 214), threshold=128)
        else:
            return DigitCounter(button, letter=(231, 239, 247), threshold=128)
    elif raid == 'GORIZIA':
        if mode == 'ex':
            return Digit(button, letter=(198, 223, 140), threshold=128)
        else:
            return DigitCounter(button, letter=(82, 89, 66), threshold=128)
    elif raid == "HUANCHANG":
        if mode == 'ex':
            return Digit(button, letter=(255, 255, 255), threshold=180)
        else:
            # 纵向排列的计数
            return HuanChangCounter(button, letter=(255, 255, 255), threshold=80)
    elif raid == 'CHIENWU':
        if mode == 'ex':
            return Digit(button, letter=(247, 223, 222), threshold=128)
        else:
            return DigitCounter(button, letter=(0, 0, 0), threshold=128)
    elif raid == 'CHANGWU':
        if mode == 'ex':
            return Digit(button, letter=(255, 239, 215), threshold=128)
        else:
            return RaidCounterPostMixin(button, lang='cnocr', letter=(154, 148, 133), threshold=128)
    elif raid == 'BIGSHOT':
        if mode == 'ex':
            return Digit(button, letter=(198, 220, 136), threshold=128)
        else:
            return RaidCounterPostMixin(button, letter=(58, 60, 65), threshold=128)


def pt_ocr(raid):
    """
    根据突袭活动名称，获取对应的 PT 积分 OCR 识别器。

    Args:
        raid (str): 突袭活动名称，如 raid_20200624、raid_20210708。

    Returns:
        Digit: PT 积分 OCR 识别器，不支持则返回 None。
    """
    raid = raid_name_shorten(raid)
    key = f'{raid}_OCR_PT'
    try:
        button = globals()[key]
    except KeyError:
        return None
    if raid == 'IRIS':
        return Digit(button, letter=(181, 178, 165), threshold=128)
    elif raid == "ALBION":
        return Digit(button, letter=(23, 20, 9), threshold=128)
    elif raid == 'KUYBYSHEY':
        return Digit(button, letter=(16, 24, 33), threshold=64)
    elif raid == 'GORIZIA':
        return Digit(button, letter=(255, 255, 255), threshold=64)
    elif raid == "HUANCHANG":
        return HuanChangPtOcr(button, letter=(23, 20, 6), threshold=128)
    elif raid == 'CHIENWU':
        return Digit(button, letter=(255, 231, 231), threshold=128)
    elif raid == 'CHANGWU':
        return Digit(button, letter=(255, 239, 215), threshold=128)
    elif raid == 'BIGSHOT':
        return Digit(button, letter=(255, 247, 236), threshold=128)


class Raid(MapOperation, RaidCombat, CampaignEvent):
    """
    突袭活动核心处理器。

    继承 MapOperation、RaidCombat 和 CampaignEvent，提供突袭活动的
    完整战斗流程：入场、战斗准备、执行战斗、处理结束画面。

    主要职责：
    - 停止条件判断（油量、PT 积分、金币、任务均衡器）
    - 战斗准备画面处理（自动化设置、退役、情绪检查、入场券使用）
    - 突袭关卡入场导航
    - 突袭战斗执行（普通模式和 EX 模式）
    - PT 积分 OCR 读取和记录
    - RPG 类型突袭的特殊处理（滑动到最右侧关卡入口）

    Attributes:
        _raid_has_oil_icon: 当前突袭活动是否显示油量图标（property，默认 False）。
    """
    @property
    def _raid_has_oil_icon(self):
        """
        判断当前突袭活动是否在 UI 中显示油量图标。
        多数突袭活动移除了油量显示，见 https://github.com/LmeSzinc/AzurLaneAutoScript/issues/5214
        """
        return False

    def triggered_stop_condition(self, oil_check=False, pt_check=False, coin_check=False):
        """
        检查是否触发停止条件：油量、活动 PT、金币或任务均衡器。

        Returns:
            bool: 是否触发了停止条件。
        """
        # 油量限制
        if oil_check:
            if self.get_oil() < max(500, self.config.StopCondition_OilLimit):
                logger.hr('触发停止条件: 石油上限')
                self.config.task_delay(minute=(120, 240))
                return True
        # 活动积分限制
        if pt_check:
            if self.event_pt_limit_triggered():
                logger.hr('触发停止条件: 活动PT上限')
                return True
        # 金币限制
        if coin_check and self.coin_limit_triggered():
            logger.hr('触发停止条件: 物资上限')
            return True
        # 任务均衡器
        if coin_check:
            if self.config.TaskBalancer_Enable and self.triggered_task_balancer():
                logger.hr('触发停止条件: 物资上限')
                self.handle_task_balancer()
                return True

        return False

    def combat_preparation(self, balance_hp=False, emotion_reduce=False, auto='combat_auto', fleet_index=1):
        """
        处理突袭战斗准备画面，包括自动化设置、退役、情绪检查和入场券使用。

        Args:
            balance_hp (bool): 是否进行血量均衡。
            emotion_reduce (bool): 是否减少情绪值。
            auto (str): 自动战斗模式。
            fleet_index (int): 舰队索引。
        """
        logger.info('战斗准备')

        # 无需在此等待情绪恢复，已在 raid_execute_once() 中处理

        checked = False
        for _ in self.loop():
            if self.appear(BATTLE_PREPARATION, offset=(30, 20)):
                if self.handle_combat_automation_set(auto=auto == 'combat_auto'):
                    continue
                if not checked and self._raid_has_oil_icon:
                    checked = True
                    if self.triggered_stop_condition(oil_check=True, coin_check=True):
                        self.config.task_stop()
            if self.handle_raid_ticket_use():
                continue
            if self.handle_retirement():
                continue
            if self.handle_combat_low_emotion():
                continue
            if self.appear_then_click(BATTLE_PREPARATION, offset=(30, 20), interval=2):
                continue
            if self.handle_combat_automation_confirm():
                continue
            if self.handle_story_skip():
                continue

            # 结束条件：战斗开始执行
            pause = self.is_combat_executing()
            if pause:
                logger.attr('战斗UI', pause)
                if emotion_reduce:
                    self.emotion.reduce(fleet_index)
                break

    def handle_raid_ticket_use(self):
        """
        处理突袭入场券使用确认弹窗，根据配置决定使用或取消。

        Returns:
            bool: 是否点击了按钮。
        """
        if self.appear(TICKET_USE_CONFIRM, offset=(30, 30), interval=1):
            if self.config.Raid_UseTicket:
                self.device.click(TICKET_USE_CONFIRM)
            else:
                self.device.click(TICKET_USE_CANCEL)
            return True

        return False

    def raid_enter(self, mode, raid, skip_first_screenshot=True):
        """
        进入指定突袭关卡，从突袭页面导航到战斗准备画面。

        Args:
            mode (str): 难度模式，easy、normal 或 hard。
            raid (str): 突袭活动名称。
            skip_first_screenshot (bool): 是否跳过首次截图。

        Pages:
            in: page_raid
            out: BATTLE_PREPARATION
        """
        entrance = raid_entrance(raid=raid, mode=mode)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(entrance, offset=(10, 10), interval=5):
                # 入口出现时检查 PT 积分限制
                if self.triggered_stop_condition(pt_check=True):
                    self.config.task_stop()
                self.device.click(entrance)
                continue
            if self.appear_then_click(RAID_FLEET_PREPARATION, offset=(20, 20), interval=5):
                continue

            # 结束条件：战斗画面出现
            if self.combat_appear():
                break

    def raid_expected_end(self):
        """
        判断突袭战斗是否已结束。

        通过检测 RAID_REWARDS 奖励弹窗或返回到突袭页面来确认战斗结束。
        RPG 类型突袭检测 page_rpg_stage，其他类型检测 RAID_CHECK。

        Returns:
            bool: 战斗是否已结束。
        """
        if self.appear_then_click(RAID_REWARDS, offset=(30, 30), interval=3):
            return False
        if self.is_raid_rpg():
            return self.appear(page_rpg_stage.check_button, offset=(30, 30))
        else:
            return self.ui_page_appear(page_raid, offset=(30, 30))

    def raid_execute_once(self, mode, raid):
        """
        执行一次突袭战斗，从进入关卡到战斗结束。

        Args:
            mode (str): 难度模式。
            raid (str): 突袭活动名称。

        Pages:
            in: page_raid
            out: page_raid
        """
        logger.hr('突袭执行')
        self.config.override(
            Campaign_Name=f'{raid}_{mode}',
            Campaign_UseAutoSearch=False,
            Fleet_FleetOrder='fleet1_all_fleet2_standby'
        )

        if mode == 'ex':
            backup = self.config.temporary(
                Submarine_Fleet=1,
                Submarine_Mode='every_combat'
            )

        self.emotion.check_reduce(1)

        self.raid_enter(mode=mode, raid=raid)
        self.combat(balance_hp=False, expected_end=self.raid_expected_end)

        if mode == 'ex':
            backup.recover()

        logger.hr('突袭结束')

    def raid_execute_once_with_oil_check(self, mode, raid):
        """
        执行一次突袭战斗，在进入战斗前检查油量。
        用于 raid_20240328 等需要提前获取油量以避免 UI 问题的突袭活动。

        Args:
            mode (str): 难度模式。
            raid (str): 突袭活动名称。

        Pages:
            in: page_raid
            out: page_raid
        """
        logger.hr('突袭执行')
        self.config.override(
            Campaign_Name=f'{raid}_{mode}',
            Campaign_UseAutoSearch=False,
            Fleet_FleetOrder='fleet1_all_fleet2_standby'
        )

        if mode == 'ex':
            backup = self.config.temporary(
                Submarine_Fleet=1,
                Submarine_Mode='every_combat'
            )

        self.emotion.check_reduce(1)

        if self.is_raid_rpg():
            logger.info('RPG突袭: 进入战斗前获取石油')
            self.ui_ensure(page_campaign_menu)
            CampaignEvent.get_oil(self, skip_first_screenshot=True, update=False)
            self.ui_ensure(page_rpg_stage)
            self.raid_rpg_swipe()

        self.raid_enter(mode=mode, raid=raid)
        self.combat(balance_hp=False, expected_end=self.raid_expected_end)

        if mode == 'ex':
            backup.recover()

        logger.hr('突袭结束')

    def get_event_pt(self):
        """
        通过 OCR 获取当前突袭活动的 PT 积分。

        Returns:
            int: 突袭 PT 积分，不支持的活动返回 0。

        Pages:
            in: page_raid
        """
        skip_first_screenshot = True
        timeout = Timer(1.5, count=5).start()
        ocr = pt_ocr(self.config.Campaign_Event)
        if ocr is not None:
            # 70000 可能是默认初始值，等待 OCR 读取到真实值
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                pt = ocr.ocr(self.device.image)
                if timeout.reached():
                    logger.warning('等待PT超时，假设已达到')
                    LogRes(self.config).Pt = pt
                    return pt
                if pt in [70000, 70001]:
                    continue
                else:
                    LogRes(self.config).Pt = pt
                    return pt
        else:
            logger.info(f'[突袭-PT] 突袭 {self.config.Campaign_Event} 不支持PT OCR，跳过')
            return 0

    def is_raid_rpg(self):
        """
        判断当前突袭活动是否为 RPG 类型。

        RPG 类型突袭（raid_20240328）具有不同的 UI 布局和入口逻辑，
        需要特殊处理（如滑动操作、不同的页面检测等）。

        Returns:
            bool: 是否为 RPG 类型突袭。
        """
        return self.config.Campaign_Event == 'raid_20240328'

    def raid_rpg_swipe(self, skip_first_screenshot=True):
        """
        在 RPG 类型突袭中滑动到最右侧关卡入口。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。
        """
        interval = Timer(1)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件：已滑动到最右侧
            if self.appear(RPG_RAID_EASY, offset=(10, 10)):
                logger.info('RPG突袭已在最右')
                break

            if self.handle_story_skip():
                continue
            if self.handle_get_items():
                continue
            if interval.reached():
                self.device.swipe_vector((-900, 0), box=(0, 130, 1280, 440))
                interval.reset()
                continue

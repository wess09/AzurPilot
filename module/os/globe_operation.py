"""全球地图操作模块。

管理大世界全球地图视图中的操作，包括：
- 海域类型检测（危险区、安全区、隐秘海域、深渊海域、要塞、档案）
- 海域选择和进入
- 固定海域（Pinned Zone）的导航
- 行动力管理
- 自动搜索奖励处理

海域类型：
- DANGEROUS: 危险海域（未清理）
- SAFE: 安全海域（已清理）
- OBSCURE: 隐秘海域（特殊条件进入）
- ABYSSAL: 深渊海域（强力敌人）
- STRONGHOLD: 塞壬要塞
- ARCHIVE: 档案海域

继承自 ActionPointHandler，提供行动力管理能力。
"""

import time
import module.base.utils as _base_utils
from module.base.timer import Timer
from module.base.utils import *
from module.logger import logger
from module.config.utils import get_os_next_reset
from module.ocr.ocr import Digit
from module.os.assets import *
from module.os.tasks.smart_explore import SMART_EXPLORE_TASK_MIN_ZONES, _smart_explore_pending
from module.os_handler.action_point import ActionPointHandler
from module.os_handler.assets import AUTO_SEARCH_REWARD
from module.os_handler.port import PORT_CHECK
from module.ui.assets import BACK_ARROW

# 海域类型按钮列表
ZONE_TYPES = [ZONE_DANGEROUS, ZONE_SAFE, ZONE_OBSCURE, ZONE_ABYSSAL, ZONE_STRONGHOLD, ZONE_ARCHIVE]
# 海域选择按钮列表（与 ZONE_TYPES 一一对应）
ZONE_SELECT = [SELECT_DANGEROUS, SELECT_SAFE, SELECT_OBSCURE, SELECT_ABYSSAL, SELECT_STRONGHOLD, SELECT_ARCHIVE]
# 固定海域检测的资源列表
ASSETS_PINNED_ZONE = ZONE_TYPES + [ZONE_ENTRANCE, ZONE_SWITCH, ZONE_PINNED]

# Under a certain scene, the similarity are as follows:
# 3840*2160 resolution, set to 0.65:
# ZONE_DANGEROUS  0.711 -- wanted
# ZONE_SAFE       0.405
# ZONE_OBSCURE    0.424
# ZONE_ABYSSAL    0.414
# ZONE_STRONGHOLD 0.154
# ZONE_ARCHIVE    0.426

# 2560*1440 resolution, set to 0.72:
# ZONE_DANGEROUS  0.799 -- wanted
# ZONE_SAFE       0.456
# ZONE_OBSCURE    0.474
# ZONE_ABYSSAL    0.443
# ZONE_STRONGHOLD 0.153
# ZONE_ARCHIVE    0.494

# 1920*1080 resolution, set to 0.70:
# ZONE_DANGEROUS  0.772 -- wanted
# ZONE_SAFE       0.423
# ZONE_OBSCURE    0.469
# ZONE_ABYSSAL    0.437
# ZONE_STRONGHOLD 0.168
# ZONE_ARCHIVE    0.462

# Native 720p resolution use default 0.75
# ZONE_DANGEROUS  0.975 -- wanted
# ZONE_SAFE       0.549
# ZONE_OBSCURE    0.569
# ZONE_ABYSSAL    0.491
# ZONE_STRONGHOLD 0.195
# ZONE_ARCHIVE    0.581
_ZONE_PINNED_SIMILARITY_THRESHOLDS = {
    (1920, 1080): 0.70,
    (2560, 1440): 0.72,
    (3840, 2160): 0.65,
}
_ZONE_PINNED_SIMILARITY_DEFAULT = 0.75


class OSExploreError(Exception):
    pass


class OSZoneLockedError(OSExploreError):
    """已识别到周边海域未压制的锁定标志。"""


class RewardUncollectedError(Exception):
    pass


class GlobeOperation(ActionPointHandler):
    """全球地图操作类。

    提供大世界全球地图界面的各种交互能力，包括海域固定、海域类型切换、
    海域进出和行动力消耗处理。
    """
    _zone_unpin_interval = Timer(0.5)

    def record_globe_suppressed_zones(self):
        """在正常全球地图截图中确认压制统计；达标后本月不再识别。"""
        if not _smart_explore_pending(self.config):
            return
        image = self.device.image
        previous = getattr(self, '_suppressed_zones_candidate', None)
        if previous is not None and previous[2] is image:
            return
        count = Digit((1184, 411, 1244, 438), letter=(255, 207, 66), threshold=128,
                      name='OS_SUPPRESSION_COUNT').ocr(image)
        reset = get_os_next_reset().isoformat()
        if not SMART_EXPLORE_TASK_MIN_ZONES <= count <= 72:
            self._suppressed_zones_candidate = None
            return
        if previous is not None and previous[:2] == (reset, count):
            self.config.cross_set('OpsiScheduling.Storage.Storage.SuppressedZones', dict(reset=reset, count=count))
            self._suppressed_zones_candidate = None
        else:
            self._suppressed_zones_candidate = (reset, count, image)

    def is_in_globe(self):
        """检查当前是否处于大世界全球地图界面。

        Returns:
            bool: 处于全球地图返回 True，否则返回 False。
        """
        return self.appear(GLOBE_GOTO_MAP, offset=(20, 20), similarity=0.75)

    def get_zone_pinned(self):
        """获取当前固定的海域按钮。

        Returns:
            Button | None: 当前固定的海域按钮，无则返回 None。
        """
        similarity = _ZONE_PINNED_SIMILARITY_THRESHOLDS.get(
            _base_utils.TEMPLATE_MATCH_NON_NATIVE_720P_RESOLUTION,
            _ZONE_PINNED_SIMILARITY_DEFAULT,
        )
        for zone in ZONE_TYPES:
            if self.appear(zone, offset=(20, 20), similarity=similarity):
                for button in ASSETS_PINNED_ZONE:
                    button.load_offset(zone)

                return zone

        return None

    def is_zone_pinned(self):
        """检查是否有海域被固定显示。

        Returns:
            bool: 是否有海域被固定显示。
        """
        return self.get_zone_pinned() is not None

    @staticmethod
    def pinned_to_name(button):
        """将海域固定按钮转换为海域类型名称字符串。

        Args:
            button (Button): 海域类型按钮。

        Returns:
            str: 海域类型名称，如 DANGEROUS、SAFE、OBSCURE、ABYSSAL、STRONGHOLD、ARCHIVE。
        """
        return button.name.split('_')[1]

    def get_zone_pinned_name(self):
        """获取当前固定海域的类型名称。

        Returns:
            str: 海域类型名称（DANGEROUS、SAFE、OBSCURE、ABYSSAL、STRONGHOLD、ARCHIVE），无固定海域时返回空字符串。
        """
        pinned = self.get_zone_pinned()
        if pinned is not None:
            return self.pinned_to_name(pinned)
        else:
            return ''

    def handle_zone_pinned(self):
        """关闭固定海域信息弹窗。

        Returns:
            bool: 是否处理了弹窗。
        """
        if not self._zone_unpin_interval.reached():
            return False

        if self.is_zone_pinned():
            # 点击无法关闭固定海域，必须执行滑动
            self.device.swipe_vector(
                (50, -50), box=area_pad(ZONE_PINNED.area, pad=-80), random_range=(-10, -10, 10, 10),
                padding=0, name='PINNED_DISABLE')
            self._zone_unpin_interval.reset()
            return True

        return False

    def ensure_no_zone_pinned(self):
        """确保当前没有海域处于固定选中状态。"""
        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop():
            if self.handle_zone_pinned():
                confirm_timer.reset()
            else:
                if confirm_timer.reached():
                    break

    def zone_has_switch(self):
        """
        检测当前海域是否有类型切换按钮。

        切换按钮由 4 个方块组成，其中一个为白色且持续旋转。
        2021.07.15 ZONE_SWITCH 缩小并新增"Change Zone"文字，改为检测该文字。

        Returns:
            bool: 当前海域是否有类型切换按钮。
        """
        # image = self.image_crop(ZONE_SWITCH)
        # center = np.array(image.size) / 2
        # count = 0
        # for corner in area2corner((0, 0, *image.size)):
        #     area = (min(corner[0], center[0]), min(corner[1], center[1]),
        #             max(corner[0], center[0]), max(corner[1], center[1]))
        #     area = area_pad(area, pad=2)
        #     color = np.mean(get_color(image, area))
        #     if color > 235:
        #         count += 1
        #
        # if count == 1:
        #     return True
        # elif count == 0:
        #     return False
        # else:
        #     logger.warning(f'Unexpected zone switch, white block: {count}')

        return self.appear(ZONE_SWITCH, offset=(5, 5))

    _zone_select_offset = (20, 200)
    _zone_select_similarity = 0.75

    def get_zone_select(self):
        """
        Returns:
            list[Button]: 当前可见的海域类型选择按钮列表。
        """
        # 降低阈值到 0.75
        # 不确定原因，但有时字体不同会导致匹配困难
        return [select for select in ZONE_SELECT if
                self.appear(select, offset=self._zone_select_offset, similarity=self._zone_select_similarity)]

    def is_in_zone_select(self):
        """
        Returns:
            bool: 是否处于海域类型选择界面。
        """
        return len(self.get_zone_select()) > 0

    def ensure_zone_select_expanded(self):
        """
        Returns:
            list[Button]: 展开后的海域类型选择按钮列表。
        """
        record = 0
        for _ in range(5):
            selection = self.get_zone_select()
            if len(selection) == record and record > 0:
                return selection

            record = len(selection)
            self.device.screenshot()

        logger.warning('[大世界-操作] 无法确保区域选择已展开，假设已展开')
        return self.get_zone_select()

    def zone_select_enter(self):
        """进入海域类型选择界面。

        Pages:
            in: is_zone_pinned
            out: is_in_zone_select
        """
        self.ui_click(ZONE_SWITCH, appear_button=self.is_zone_pinned, check_button=self.is_in_zone_select,
                      skip_first_screenshot=True)
        # 点击太快碧蓝反应不过来
        time.sleep(0.015)

    def zone_select_execute(self, button):
        """执行选择指定海域类型操作。

        Args:
            button (Button): 要选择的海域类型按钮，为 SELECT_* 按钮之一。

        Pages:
            in: is_in_zone_select
            out: is_zone_pinned
        """
        logger.info(f'区域选择: {button}')
        for _ in self.loop():
            # End
            if self.is_zone_pinned():
                break
            if self.appear_then_click(
                    button, offset=self._zone_select_offset, similarity=self._zone_select_similarity, interval=5):
                continue

    def zone_type_select(self, types=('SAFE', 'DANGEROUS')):
        """选择指定的海域类型。

        Args:
            types (tuple[str, ...] | list[str] | str): 海域类型名称或其列表。
                可用类型：DANGEROUS、SAFE、OBSCURE、ABYSSAL、STRONGHOLD、ARCHIVE。
                按列表顺序优先尝试选择，不可用时尝试下一个。
                若无匹配项则不执行操作。

        Returns:
            bool: 是否选择成功。

        Pages:
            in: is_zone_pinned
            out: is_zone_pinned
        """
        if not self.zone_has_switch():
            logger.info('区域无类型可选，跳过')
            return True

        if isinstance(types, str):
            types = [types]
        # 在修改前记录请求的类型，用于日志
        requested_type = types[0] if types else None

        def get_button(selection_):
            for typ in types:
                typ = 'SELECT_' + typ
                for sele in selection_:
                    if typ == sele.name:
                        return sele
            return None

        pinned = self.get_zone_pinned_name()
        if pinned in types:
            logger.info(f'已选择于 {pinned}')
            return True

        for _ in range(3):
            self.zone_select_enter()
            selection = self.ensure_zone_select_expanded()
            logger.attr('海域选择', selection)

            button = get_button(selection)
            if button is None:
                # 获取所有可用的区域类型（不含SELECT_前缀）
                available_types = [getattr(sel, 'name', str(sel)).replace('SELECT_', '') for sel in selection]
                logger.warning(
                    f'[大世界-操作] 海域类型 {requested_type} 未在选择列表中, '
                    f'可用类型: {available_types}, '
                    f'回退到默认 (SAFE > DANGEROUS)'
                )
                # 回退到安全的默认优先级，而不是选择列表中的第一个
                # 这样在有深渊海域时不会错误地进入深渊而是选择安全海域
                types = ('SAFE', 'DANGEROUS')
                button = get_button(selection)
                if button is None:
                    logger.warning('[大世界-操作] 无区域类型可选')
                    return False

            self.zone_select_execute(button)
            if self.pinned_to_name(button) == self.get_zone_pinned_name():
                return True

        logger.warning('[大世界-操作] 尝试3次后仍无法选择区域类型')
        return False

    def zone_has_safe(self):
        """检查并选择海域类型：优先选择 SAFE，否则选择 DANGEROUS。

        Returns:
            bool: 是否存在 SAFE 类型。

        Pages:
            in: is_zone_pinned
            out: is_zone_pinned
        """
        if self.get_zone_pinned_name() == 'SAFE':
            return True
        elif self.zone_has_switch():
            self.zone_select_enter()
            flag = SELECT_SAFE in self.ensure_zone_select_expanded()
            button = SELECT_SAFE if flag else SELECT_DANGEROUS
            self.zone_select_execute(button)
            return flag
        else:
            # 没有切换按钮，已在 DANGEROUS 类型
            return False

    def os_globe_goto_map(self, skip_first_screenshot=True):
        """从全球地图进入海域地图。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            bool: 成功进入海域地图返回 True。

        Pages:
            in: is_in_globe
            out: is_in_map
        """
        # 处理意外进入港口的情况
        for _ in self.loop():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_in_map():
                time.sleep(1)
                break

            if self.appear(PORT_CHECK, offset=(20, 20), interval=3):
                logger.info('误入港口，退出')
                self.device.click(BACK_ARROW)
                self.interval_reset(GLOBE_GOTO_MAP)
                continue
            if self.appear_then_click(GLOBE_GOTO_MAP, offset=(20, 20), interval=3):
                continue

        return True

    def os_map_goto_globe(self, unpin=True):
        """从海域地图返回全球地图。

        Args:
            unpin (bool): 是否取消海域固定信息。默认 True。

        Raises:
            RewardUncollectedError: 有未收集的探索奖励阻止退出时抛出。

        Pages:
            in: is_in_map
            out: is_in_globe
        """
        click_count = 0
        for _ in self.loop():
            # End
            if self.is_in_globe():
                self.record_globe_suppressed_zones()
                break

            if self.appear_then_click(MAP_GOTO_GLOBE, offset=(200, 5), interval=5):
                # 仅用于初始化 MAP_GOTO_GLOBE_FOG 的间隔计时器
                self.appear(MAP_GOTO_GLOBE_FOG, interval=5)
                self.interval_reset(MAP_GOTO_GLOBE_FOG)
                click_count += 1
                if click_count >= 5:
                    # 当海域存在探索奖励时，游戏不会允许你离开。
                    logger.warning('[大世界-操作] 无法前往全球地图, 可能有未收集的海域探索奖励阻止退出')
                    raise RewardUncollectedError
                continue
            if self.appear_then_click(MAP_GOTO_GLOBE_FOG, interval=5):
                # 仅在要塞中遇到；即使地图中有未领取的探索奖励，游戏也不会阻止退出
                self.interval_reset(MAP_GOTO_GLOBE)
                continue
            if self.handle_map_event():
                continue
            # 意外进入港口
            if self.appear(PORT_CHECK, offset=(20, 20), interval=5):
                logger.info(f'页面切换: {PORT_CHECK} -> {BACK_ARROW}')
                self.device.click(BACK_ARROW)
                continue
            # 弹窗：AUTO_SEARCH_REWARD 出现较慢
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=5):
                continue
            # 弹窗：离开当前海域将终止指挥喵搜索。
            # 弹窗：离开当前海域将撤回潜艇。
            # 搜索奖励将在进入其他海域后显示。
            if self.handle_popup_confirm('GOTO_GLOBE'):
                continue

        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop():
            if self.is_in_globe():
                self.record_globe_suppressed_zones()
            if unpin:
                if self.handle_zone_pinned():
                    confirm_timer.reset()
                else:
                    if self.is_in_globe() and confirm_timer.reached():
                        break
            else:
                if self.is_zone_pinned():
                    break

    def globe_enter(self, zone):
        """从全球地图进入指定海域。

        Args:
            zone (Zone): 要进入的海域。

        Raises:
            OSExploreError: 海域被锁定时抛出。

        Pages:
            in: is_zone_pinned
            out: is_in_map
        """
        click_timer = Timer(10)
        click_count = 0
        pinned = None
        for _ in self.loop():
            if pinned is None:
                pinned = self.get_zone_pinned_name()

            # End
            if self.is_in_map():
                if click_count > 0:
                    time.sleep(1)
                break

            if self.is_zone_pinned():
                if self.appear(ZONE_LOCKED, offset=(20, 20)):
                    logger.warning(f'[大世界-操作] 海域 {zone} 已锁定, 相邻海域可能未被探索过')
                    raise OSZoneLockedError(f'周边海域未压制: {zone}')
                if click_count > 5:
                    logger.warning(f'[大世界-操作] 无法进入海域 {zone}, 相邻海域可能未被探索过')
                    raise OSExploreError
                if click_timer.reached():
                    # 点太快会进不去 浪费时间
                    time.sleep(0.2)
                    self.device.click(ZONE_ENTRANCE)
                    click_count += 1
                    click_timer.reset()
                    continue
            if self.handle_action_point(zone=zone, pinned=pinned):
                click_timer.clear()
                continue
            if self.handle_map_event():
                continue
            if self.handle_popup_confirm('GLOBE_ENTER'):
                continue
            # 游戏 bug：上一个已清理海域的 AUTO_SEARCH_REWARD 弹窗
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                continue

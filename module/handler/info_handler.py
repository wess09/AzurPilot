"""信息栏和弹窗处理器。

处理游戏中各种信息提示和弹窗对话框，是所有处理器的基础组件。

信息栏（Info Bar）：
    屏幕顶部的通知条，包含委托完成、敌人搜索等提示。
    通过检测信息栏的出现和消失来同步自动化流程。

弹窗处理：
    - 确认/取消对话框（如退役确认、战斗确认）
    - 活动公告弹窗
    - 紧急委托通知
    - 大舰队相关弹窗

预处理函数 info_letter_preprocess()：
    调整信息栏文字图像的对比度，用于模板匹配识别信息栏内容。
"""

from scipy import signal

from module.base.base import ModuleBase
from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import *
from module.combat.assets import BATTLE_PREPARATION
from module.exception import CampaignEnd, GameNotRunningError, GameTooManyClickError, ScriptEnd
from module.handler.assets import *
from module.logger import logger
from module.os_handler.assets import CLICK_SAFE_AREA as OS_CLICK_SAFE_AREA
from module.ui.assets import BACK_ARROW
from module.ui_white.assets import POPUP_CANCEL_WHITE, POPUP_CONFIRM_WHITE, POPUP_SINGLE_WHITE


def info_letter_preprocess(image):
    """对信息栏文字图像进行预处理，调整对比度。

    Args:
        image (np.ndarray): 输入图像。

    Returns:
        np.ndarray: 处理后的 uint8 图像。
    """
    image = image.astype(float)
    image = (image - 64) / 0.75
    image[image > 255] = 255
    image[image < 0] = 0
    image = image.astype('uint8')
    return image


class InfoHandler(ModuleBase):
    """信息栏和弹窗处理器基类。

    提供游戏中各类 UI 弹窗的统一检测和处理接口。
    所有需要处理弹窗的处理器都应继承此类。

    主要功能：
    - 信息栏检测和处理（info_bar_count, handle_info_bar）
    - 弹窗确认/取消（handle_popup_confirm, handle_popup_cancel）
    - 紧急委托处理（handle_urgent_commission）
    - 剧情跳过（handle_story_skip）
    - 大舰队弹窗处理（handle_guild_popup_cancel）
    - 投票弹窗处理（handle_vote_popup）
    """

    def info_bar_count(self):
        """通过顶部蓝色线条检测信息栏数量。

        Returns:
            int: 检测到的信息栏数量。
        """
        image = self.image_crop(INFO_BAR_AREA, copy=False)
        line = cv2.reduce(image, 1, cv2.REDUCE_AVG)
        line = color_similarity_2d(line, color=(107, 158, 255))[:, 0]

        parameters = {
            'height': 235,
            'prominence': 50,
            # 蓝色线条间距约为 56 像素
            'distance': 50,
        }
        peaks, _ = signal.find_peaks(line, **parameters)
        return len(peaks)

    def wait_until_info_bar_disappear(self):
        """持续截图等待信息栏完全消失。"""
        while 1:
            self.device.screenshot()
            if not self.info_bar_count():
                break

    def handle_info_bar(self):
        """检测并等待信息栏消失。

        Returns:
            bool: 是否检测到并等待了信息栏。
        """
        if self.info_bar_count():
            self.wait_until_info_bar_disappear()
            return True
        else:
            return False

    def ensure_no_info_bar(self, timeout=0.6, skip_first_screenshot=True):
        """确保屏幕上没有残留的信息栏。

        Args:
            timeout (int | float): 等待超时时间（秒）。
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 是否处理了信息栏。
        """
        timeout = Timer(timeout).start()
        handled = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_info_bar():
                handled = True

            # 结束条件
            if timeout.reached():
                break

        return handled

    _popup_offset = (3, 30)

    def handle_popup_confirm(self, name='', offset=None, interval=2):
        """处理确认弹窗，点击确认按钮。

        Args:
            name (str): 弹窗名称后缀，用于日志记录。默认为空字符串。
            offset (tuple | None): 匹配偏移量，为 None 时使用默认偏移量。
            interval (int | float): 点击间隔（秒）。

        Returns:
            bool: 是否成功点击确认按钮。
        """
        if offset is None:
            offset = self._popup_offset
        if self.appear(POPUP_CANCEL, offset=offset) \
                and self.appear(POPUP_CONFIRM, offset=offset, interval=interval):
            POPUP_CONFIRM.name = POPUP_CONFIRM.name + '_' + name
            self.device.click(POPUP_CONFIRM)
            POPUP_CONFIRM.name = POPUP_CONFIRM.name[:-len(name) - 1]
            return True
        if self.appear(POPUP_CONFIRM_WHITE, offset=offset, interval=interval):
            POPUP_CONFIRM_WHITE.name = POPUP_CONFIRM_WHITE.name + '_' + name
            self.device.click(POPUP_CONFIRM_WHITE)
            POPUP_CONFIRM_WHITE.name = POPUP_CONFIRM_WHITE.name[:-len(name) - 1]
            return True
        return False

    def handle_popup_cancel(self, name='', offset=None, interval=2):
        """处理取消弹窗，点击取消按钮。

        Args:
            name (str): 弹窗名称后缀，用于日志记录。默认为空字符串。
            offset (tuple | None): 匹配偏移量，为 None 时使用默认偏移量。
            interval (int | float): 点击间隔（秒）。

        Returns:
            bool: 是否成功点击取消按钮。
        """
        if offset is None:
            offset = self._popup_offset
        if self.appear(POPUP_CONFIRM, offset=offset) \
                and self.appear(POPUP_CANCEL, offset=offset, interval=interval):
            POPUP_CANCEL.name = POPUP_CANCEL.name + '_' + name
            self.device.click(POPUP_CANCEL)
            POPUP_CANCEL.name = POPUP_CANCEL.name[:-len(name) - 1]
            return True
        if self.appear(POPUP_CANCEL_WHITE, offset=offset, interval=interval):
            POPUP_CANCEL_WHITE.name = POPUP_CANCEL_WHITE.name + '_' + name
            self.device.click(POPUP_CANCEL_WHITE)
            POPUP_CANCEL_WHITE.name = POPUP_CANCEL_WHITE.name[:-len(name) - 1]
            return True
        return False

    def handle_popup_single(self, name='', offset=None, interval=2):
        """处理单按钮弹窗（如领取任务等）。

        Args:
            name (str): 按钮名称后缀，用于日志记录。默认为空字符串。
            offset (tuple | None): 匹配偏移量。
            interval (int | float): 点击间隔（秒）。

        Returns:
            bool: 是否成功点击按钮。
        """
        if offset is None:
            offset = self._popup_offset
        if self.appear(GET_MISSION, offset=offset, interval=interval):
            prev_name = GET_MISSION.name
            GET_MISSION.name = POPUP_CONFIRM.name + '_' + name
            self.device.click(GET_MISSION)
            GET_MISSION.name = prev_name
            return True

        return False

    def handle_popup_single_white(self, interval=2):
        """处理白色单按钮弹窗。

        Args:
            interval (int | float): 点击间隔（秒）。

        Returns:
            bool: 是否成功点击按钮。
        """
        if self.appear_then_click(POPUP_SINGLE_WHITE, offset=(20, 20), interval=interval):
            return True
        return False

    def popup_interval_clear(self):
        """清除常用弹窗按钮的点击冷却间隔。"""
        self.interval_clear([
            POPUP_CANCEL, POPUP_CONFIRM,
            POPUP_CANCEL_WHITE, POPUP_CONFIRM_WHITE,
        ])

    _hot_fix_check_wait = Timer(6)

    def handle_urgent_commission(self, drop=None):
        """处理紧急委托弹窗。

        Args:
            drop (DropImage | None): 掉落图像记录对象，可为 None。

        Returns:
            bool: 是否检测到并处理了紧急委托弹窗。

        Raises:
            GameNotRunningError: 检测到服务器热更新导致游戏进程退出时抛出。
        """
        appear = self.appear(GET_MISSION, offset=True, interval=2)
        if appear:
            logger.info('[处理器-委托] 收到紧急委托')
            if drop:
                self.handle_info_bar()
                drop.add(self.device.image)
            self.device.click(GET_MISSION)
            self._hot_fix_check_wait.reset()

        # 在点击确认按钮后 3~6 秒内检查游戏客户端是否存活
        # 热更新可能会导致游戏进程被杀死
        if self._hot_fix_check_wait.reached():
            self._hot_fix_check_wait.clear()
        if self._hot_fix_check_wait.started() and 3 <= self._hot_fix_check_wait.current_time() <= 6:
            if not self.device.app_is_running():
                logger.error('[处理器-热更新] 检测到游戏服务器热更新，游戏进程已退出')
                raise GameNotRunningError
            # 使用模板匹配（不含颜色匹配），因为维护公告弹窗颜色不同
            if self.appear(LOGIN_CHECK, offset=(30, 30)):
                logger.warning('[处理器-热更新] 账号已登出，'
                               '可能是因为服务器维护或另一个登录将账号踢下线')
            self._hot_fix_check_wait.clear()

        return appear

    def handle_combat_low_emotion(self):
        """
        处理低情绪出击警告弹窗（红脸弹窗）。

        - ignore 模式（含 calculate_ignore）：点击确认继续出击
        - calculate 模式（不含 ignore）：正常不应出现红脸弹窗（已预检），
          若出现则视为异常，取消弹窗退出关卡、心情清零、延时任务

        作战档案出击后的「消耗档案密钥」弹窗同样由 POPUP_CANCEL /
        POPUP_CONFIRM 这两个通用按钮组成，仅凭按钮判定会把出击被数据密钥
        弹窗拦住误判成红脸弹窗（取消弹窗、清零心情、延后任务），
        因此先交给 handle_use_data_key() 处理。

        Returns:
            bool: 是否处理了弹窗。calculate 模式下若触发保底会抛出 ScriptEnd。

        Raises:
            ScriptEnd: calculate 模式下出现红脸弹窗时，心情清零并延时后抛出。
        """
        # 作战档案强制启用数据密钥，此时的双按钮弹窗优先按数据密钥弹窗处理
        if self.handle_use_data_key():
            return True

        # calculate 模式保底：正常不应出现红脸弹窗
        # 若出现则可能是ALAS计算错误或用户手动操作，需异常处理
        if self.emotion.is_calculate and not self.emotion.is_ignore:
            if self.handle_popup_cancel('IGNORE_LOW_EMOTION'):
                logger.warning('[心情-保底] 计算模式下出现红脸弹窗，'
                               '可能是ALAS计算错误或用户手动操作')
                logger.hr('心情异常保底')
                # 退出关卡（弹窗已取消，阻止战斗）
                # 捕获 withdraw() 抛出的 CampaignEnd，确保后续心情清零和延时被执行
                try:
                    self._emotion_emergency_exit()
                except CampaignEnd:
                    logger.info('[心情-保底] 撤退完成，已回到关卡页面')
                # 从0建立有效的保守恢复起点，任务重载后仍可自动恢复。
                self.emotion.emergency_reset()
                # 按下次完整出击预留心情；没有地图战斗次数的任务至少预留一场。
                battle = max(1, getattr(self, '_map_battle', 1))
                recovered, _ = self.emotion._check_reduce(battle)
                self.config.task_delay(target=recovered)
                raise ScriptEnd('[心情-保底] 计算模式红脸弹窗，心情清零并延时')

        if not self.emotion.is_ignore:
            return False

        result = self.handle_popup_confirm('IGNORE_LOW_EMOTION')
        if result:
            # 避免误点 AUTO_SEARCH_MAP_OPTION_OFF
            self.interval_reset(AUTO_SEARCH_MAP_OPTION_OFF)
        return result

    def _emotion_emergency_exit(self):
        """
        红脸弹窗保底退出关卡。

        取消弹窗后，依次处理战斗准备界面、自动搜索菜单、地图界面，
        直到回到关卡选择页面或超时。用于 calculate 模式下出现红脸弹窗的
        异常保底流程，确保游戏回到关卡选择页面后再延时任务。

        Pages:
            in: 红脸弹窗已取消，可能在战斗准备/地图/自动搜索菜单
            out: is_in_stage() 或超时
        """
        timeout = Timer(30, count=60).start()
        while 1:
            self.device.screenshot()

            if timeout.reached():
                logger.warning('[心情-保底] 退出关卡超时')
                break

            if self.handle_popup_cancel('IGNORE_LOW_EMOTION'):
                continue
            if self.handle_story_skip():
                continue
            # 战斗准备界面：点击返回
            if self.appear(BATTLE_PREPARATION, offset=(20, 20), interval=2):
                self.device.click(BACK_ARROW)
                continue
            # 自动搜索菜单：退出
            if self.handle_auto_search_exit():
                continue
            # 已回到关卡页面
            if self.is_in_stage():
                break
            # 在地图中：撤退（withdraw 在 MapOperation 中，部分子类可能没有）
            if self.is_in_map() and hasattr(self, 'withdraw'):
                self.withdraw()
                break

    def use_data_key_notified_enabled(self):
        """
        判断「今日不再提示」复选框是否已勾选。

        Returns:
            bool: 复选框变绿（已勾选）返回 True。
        """
        return self.image_color_count(
            USE_DATA_KEY_NOTIFIED, color=(140, 207, 66), threshold=75, count=10)

    def use_data_key_appear(self):
        """
        判断当前画面是否为作战档案的数据密钥确认弹窗。

        弹窗内容「进入所选关卡需要消耗档案密钥x5，是否进入？」是逐元素渲染
        且整行居中的：刚弹出时文字可能还没画出来，数量位数变化又会让黄色
        文字左右移动，位置写死的 USE_DATA_KEY 模板可能匹配不到。因此再用
        固定位置的「今日不再提示」复选框兜底——该复选框只在这个弹窗上出现，
        未勾选是标题栏右侧的深色方块，勾选后是绿色方块。

        Returns:
            bool: 是数据密钥确认弹窗返回 True。
        """
        if self.appear(USE_DATA_KEY, offset=(20, 20)):
            return True
        if self.image_color_count(USE_DATA_KEY_NOTIFIED, color=(34, 49, 75), threshold=40, count=100):
            return True
        if self.use_data_key_notified_enabled():
            return True

        return False

    def handle_use_data_key(self):
        """
        处理作战档案的数据密钥确认弹窗：勾选「今日不再提示」后确认。

        勾选后当天不再弹出，省掉每次出击的确认。弹窗刚出现时内容可能还没
        渲染完，此时不能直接放弃——调用方（含红脸弹窗判定）只看
        POPUP_CANCEL / POPUP_CONFIRM 这两个通用按钮，放弃就会被当成别的弹窗
        处理。所以这里等弹窗渲染完成再判断，勾选失败也不影响确认弹窗。

        Pages:
            in: 作战档案出击后的数据密钥确认弹窗
            out: 弹窗已确认

        Returns:
            bool: 是否处理了数据密钥弹窗。
        """
        if not self.config.USE_DATA_KEY:
            return False

        if not self.appear(POPUP_CONFIRM, offset=self._popup_offset) \
                and not self.appear(POPUP_CANCEL, offset=self._popup_offset, interval=2):
            return False

        # 等待弹窗渲染完成；等待期间弹窗消失说明不是数据密钥弹窗，交回上层
        if not self.use_data_key_appear():
            for _ in self.loop(timeout=2):
                if self.use_data_key_appear():
                    break
                if not self.appear(POPUP_CONFIRM, offset=self._popup_offset):
                    return False
            else:
                return False

        # 启用 USE_DATA_KEY_NOTIFIED
        # 定时器不启动，首次判断立即点击，之后每 2 秒重试一次，最多重试 6 秒
        interval = Timer(2, count=2)
        for _ in self.loop(timeout=Timer(6, count=20)):
            if self.use_data_key_notified_enabled():
                break
            if interval.reached() and self.use_data_key_appear():
                self.device.click(USE_DATA_KEY_NOTIFIED)
                interval.reset()
                continue
        else:
            logger.warning('[作战档案] 「今日不再提示」未勾选成功，直接确认弹窗')

        result = self.handle_popup_confirm('USE_DATA_KEY')
        if result:
            self.config.USE_DATA_KEY = False  # 成功后重置，因为任务可能在恢复前被停止
        return result

    def handle_vote_popup(self):
        """关闭投票弹窗（投票弹窗已于 2023 年移除）。

        Returns:
            bool: 始终返回 False。
        """
        # 投票弹窗已于 2023 年移除
        # return self.appear_then_click(VOTE_CANCEL, offset=(20, 20), interval=2)
        return False

    def handle_get_skin(self):
        """处理获取皮肤弹窗。

        Returns:
            bool: 是否处理了皮肤弹窗。
        """
        return self.appear_then_click(GET_SKIN, offset=(20, 20), interval=2)

    def handle_get_items_ship(self, drop=None):
        """处理获得舰船时的道具弹窗。

        Args:
            drop (DropImage | None): 掉落记录对象。默认为 None。

        Returns:
            bool: 是否检测并点击了弹窗。
        """
        if self.appear(GET_ITEMS_SHIP_1, offset=5, interval=2):
            if drop:
                drop.handle_add(self)
            self.device.click(GET_ITEMS_SHIP_1)
            return True

        return False

    def handle_guild_popup_confirm(self):
        """处理大舰队确认弹窗。

        Returns:
            bool: 是否点击了确认。
        """
        if self.appear(GUILD_POPUP_CANCEL, offset=self._popup_offset) \
                and self.appear(GUILD_POPUP_CONFIRM, offset=self._popup_offset, interval=2):
            self.device.click(GUILD_POPUP_CONFIRM)
            return True

        return False

    def handle_guild_popup_cancel(self):
        """处理大舰队取消弹窗。

        Returns:
            bool: 是否点击了取消。
        """
        if self.appear(GUILD_POPUP_CONFIRM, offset=self._popup_offset) \
                and self.appear(GUILD_POPUP_CANCEL, offset=self._popup_offset, interval=2):
            self.device.click(GUILD_POPUP_CANCEL)
            return True

        return False

    def handle_mission_popup_go(self):
        """处理任务前往弹窗。

        Returns:
            bool: 是否点击了前往。
        """
        if self.appear(MISSION_POPUP_ACK, offset=self._popup_offset) \
                and self.appear(MISSION_POPUP_GO, offset=self._popup_offset, interval=2):
            self.device.click(MISSION_POPUP_GO)
            return True

        return False

    def handle_mission_popup_ack(self):
        """处理任务已知晓弹窗。

        Returns:
            bool: 是否点击了已知晓。
        """
        if self.appear(MISSION_POPUP_GO, offset=self._popup_offset) \
                and self.appear(MISSION_POPUP_ACK, offset=self._popup_offset, interval=2):
            self.device.click(MISSION_POPUP_ACK)
            return True

        return False

    story_popup_timeout = Timer(10, count=20)
    map_has_clear_mode = False  # 会在 fast_forward.py 中被覆盖
    map_is_threat_safe = False

    _story_confirm = Timer(0.5, count=1)
    _story_option_timer = Timer(2)
    _story_option_record = 0
    _story_option_confirm = Timer(0.3, count=0)
    # 剧情选项连续点击数。选项点击不计入点击记录（见 story_skip），
    # 由这个计数兜底检测剧情卡在选项画面不动的情况。
    _story_option_click = 0
    _story_option_click_limit = 12

    def _story_option_buttons(self):
        """检测剧情选项按钮（旧版样式）。

        Returns:
            list[Button]: 从上到下排列的剧情选项按钮列表，未找到则返回空列表。
        """
        # 选项检测区域，至少需要包含 3 个选项
        story_option_area = (730, 188, 1140, 480)
        # 选项左侧部分的背景颜色
        story_option_color = (99, 121, 156)
        image = color_similarity_2d(self.image_crop(story_option_area, copy=False), color=story_option_color) > 225
        x_count = np.where(np.sum(image, axis=0) > 40)[0]
        if not len(x_count):
            return []
        x_min, x_max = np.min(x_count), np.max(x_count)

        parameters = {
            # 选项尺寸约为 300~320px x 50~52px
            'height': 280,
            'width': 45,
            'distance': 50,
            # 选择峰值宽度测量的相对高度（占突出度的百分比）
            # 1.0 在最低等高线处计算，0.5 在突出度一半处计算，必须 >= 0
            'rel_height': 5,
        }
        y_count = np.sum(image, axis=1)
        peaks, properties = signal.find_peaks(y_count, **parameters)
        buttons = []
        total = len(peaks)
        if not total:
            return []
        for n, bases in enumerate(zip(properties['left_bases'], properties['right_bases'])):
            area = (x_min, bases[0], x_max, bases[1])
            area = area_pad(area_offset(area, offset=story_option_area[:2]), pad=5)
            buttons.append(
                Button(area=area, color=story_option_color, button=area, name=f'STORY_OPTION_{n + 1}_OF_{total}'))

        return buttons

    def _story_option_buttons_2(self):
        """检测剧情选项按钮（新版大白色选项样式）。

        Returns:
            list[Button]: 从上到下排列的剧情选项按钮列表，未找到则返回空列表。
        """
        # 选项检测区域，至少需要包含 3 个选项
        story_option_area = (330, 135, 980, 555)
        story_detect_area = (330, 135, 355, 555)
        story_option_color = (247, 247, 247)

        image = color_similarity_2d(self.image_crop(story_detect_area, copy=False), color=story_option_color)
        cv2.morphologyEx(image, cv2.MORPH_CLOSE, kernel=np.ones((5, 5), dtype=np.uint8), dst=image)
        line = cv2.reduce(image, 1, cv2.REDUCE_AVG).flatten()
        line[line < 200] = 0
        line[line >= 200] = 255

        parameters = {
            # 选项尺寸约为 300~320px x 50~52px
            'height': 200,
            'width': 40,
            'distance': 40,
            # 选择峰值宽度测量的相对高度（占突出度的百分比）
            # 1.0 在最低等高线处计算，0.5 在突出度一半处计算，必须 >= 0
            # rel_height 约为 240 / 48
            'rel_height': 4,
        }
        peaks, properties = signal.find_peaks(line, **parameters)
        buttons = []
        total = len(peaks)
        if not total:
            return []
        for n, bases in enumerate(zip(properties['left_bases'], properties['right_bases'])):
            area = (
                story_option_area[0], story_option_area[1] + bases[0],
                story_option_area[2], story_option_area[1] + bases[1],
            )
            area = area_pad(area, pad=5)
            buttons.append(
                Button(area=area, color=story_option_color, button=area, name=f'STORY_OPTION_{n + 1}_OF_{total}'))

        buttons = sorted(buttons, key=lambda button: button.button[1])
        return buttons

    def _story_option_buttons_3(self):
        """检测剧情选项按钮（右侧白色选项样式）。

        例如大世界主线的适应性选择界面（[适应性·攻击]提升 /
        [适应性·耐久]提升 / [适应性·效能]提升 / 不做选择），
        选项纵向排列在画面右侧，点击右上角跳过无效，必须选择一项。

        Returns:
            list[Button]: 从上到下排列的剧情选项按钮列表，未找到则返回空列表。
        """
        # 选项检测区域，至少需要包含 2 个选项
        # 右侧雷达在 x=1080 以后，检测区域避开雷达
        story_option_area = (760, 150, 1010, 470)
        story_option_color = (247, 247, 247)
        image = color_similarity_2d(self.image_crop(story_option_area, copy=False), color=story_option_color) > 225

        # 选项约为 150px x 47px，白色底上文字使行白色计数降到约一半
        # 沿 y 平滑填平文字凹陷，窗口小于选项间距(约28px)不会误合并相邻选项
        parameters = {
            'height': 60,
            'width': 25,
            'distance': 60,
        }
        y_count = np.convolve(np.sum(image, axis=1), np.ones(15), mode='same')
        peaks, properties = signal.find_peaks(y_count, **parameters)
        buttons = []
        total = len(peaks)
        if not total:
            return []
        for n, bases in enumerate(zip(properties['left_bases'], properties['right_bases'])):
            y0, y1 = int(bases[0]), int(bases[1])
            x_count = np.where(np.sum(image[y0:y1, :], axis=0) > 5)[0]
            if not len(x_count):
                continue
            x_min, x_max = np.min(x_count), np.max(x_count)
            area = (x_min, y0, x_max, y1)
            area = area_pad(area_offset(area, offset=story_option_area[:2]), pad=5)
            buttons.append(
                Button(area=area, color=story_option_color, button=area, name=f'STORY_OPTION_{n + 1}_OF_{total}'))
        return buttons

    def _is_story_black(self):
        """检测当前画面是否为黑屏剧情文字界面。

        Returns:
            bool: 是否为黑底剧情画面。
        """
        color = get_color(self.device.image, area=STORY_LETTER_BLACK.area)
        if color_similar(color, STORY_LETTER_BLACK.color, threshold=10):
            return True
        if color_similar(color, (0, 0, 0), threshold=10):
            return True

        return False

    def _identify_siren_device_option(self, options):
        """根据选项序列识别塞壬装置。

        侵蚀一地图的装置剧情：
        - 塞壬探测装置：5 个选项（探测敌人/探测资源/离开），按 Siren_Mode 选择；
        - 塞壬信息收集装置 / 探测装置产物柱子：3 个选项，点中间选项即完成。

        3 选项剧情并不都是塞壬装置：深渊 / 隐秘 / 要塞 / 跨月 用 STORY_OPTION=0
        指定点第一项（解除封锁的强制确认，中间项是「查阅作战说明」），
        因此显式指定了 STORY_OPTION 时按配置选择，只有自动选择（-2）才按柱子处理。

        Args:
            options (list[Button]): 检测到的剧情选项按钮列表。

        Returns:
            Button | None: 需要点击的按钮，若识别为非塞壬装置剧情则返回 None。
        """
        if len(options) == 5:
            task = self.config.task.command
            if task not in ('OpsiHazard1Leveling', 'OpsiMeowfficerFarming'):
                task = 'OpsiHazard1Leveling'

            siren_research_enabled = self.config.cross_get(
                keys=f'{task}.OpsiSirenBug.SirenResearch_Enable',
                default=False
            )

            if not siren_research_enabled:
                logger.info('[Handler] [Story] 塞壬研究装置未启用，选择离开')
                self.siren_device_mode = None
                return options[-1]

            siren_mode = self.config.cross_get(
                keys=f'{task}.OpsiSirenBug.Siren_Mode',
                default='resource'
            )

            if siren_mode == 'enemy':
                logger.info('[Handler] [Story] 选择反复尝试探测隐藏的敌人')
                self.siren_device_mode = 'enemy'
                return options[2]
            else:
                logger.info('[Handler] [Story] 选择反复尝试探测隐藏的资源')
                self.siren_device_mode = 'resource'
                return options[3]

        elif len(options) == 3:
            # 3 选项剧情的正确选项随海域而变，不能一律点中间项：
            # - 深渊 / 隐秘 / 要塞 / 跨月 用 STORY_OPTION=0 指定点第一项，
            #   例如深渊解除封锁的强制确认，中间项是「查阅作战说明」；
            # - 大世界其余任务为 STORY_OPTION=-2（自动选择），3 选项时
            #   即塞壬信息收集装置 / 探测装置产物柱子的「提交物品」。
            story_option = self.config.STORY_OPTION
            if 0 <= story_option < len(options):
                logger.info(f'[Handler] [Story] 3 选项剧情，按 STORY_OPTION 选择第 {story_option + 1} 项')
                return options[story_option]
            # 未显式指定选项，按塞壬信息收集装置 / 柱子处理
            logger.info('[Handler] [Story] 塞壬信息收集装置/柱子，点中间选项完成')
            self.siren_device_mode = 'collected'
            return options[1]

        return None

    def story_skip(self, drop=None, *, click_interval=2, prefer_skip=False):
        """跳过剧情对话。

        2023.09.14 剧情选项变更为中间大白色选项样式，
        通过 STORY_SKIP_3 检测但点击原始 STORY_SKIP。

        剧情选项按钮名按「第几个/共几个」生成（如 STORY_OPTION_2_OF_3），
        不同剧情段会共用同一个名字，连续处理多个装置时会被防连点机制
        （两个按钮各 ≥6 次）误判为卡死，因此剧情点击后清空点击记录，
        改由 _story_option_click 计数检测剧情停在选项画面不动的情况。

        Args:
            drop (DropImage | None): 掉落记录对象。默认为 None。
            click_interval (float): 剧情操作的最小重试间隔，默认 2 秒。
            prefer_skip (bool): 无选项对话优先点击右上角跳过，不修改全局剧情配置。

        Returns:
            bool: 是否进行了剧情跳过或选项操作。

        Raises:
            GameTooManyClickError: 连续点击剧情选项达到上限仍未推进时抛出。
        """
        if self.story_popup_timeout.started() and not self.story_popup_timeout.reached():
            if self.handle_popup_confirm('STORY_SKIP', interval=click_interval):
                # 提交确认弹窗的按钮名（POPUP_CONFIRM_STORY_SKIP）同样在不同剧情段
                # 复用，与选项一起清掉点击记录，避免被防连点机制误判为卡死
                self.device.click_record_clear()
                self._story_option_click = 0
                self.story_popup_timeout = Timer(10)
                self.interval_reset(STORY_SKIP_3, interval=click_interval if click_interval < 2 else 3)
                self.interval_reset(STORY_LETTERS_ONLY, interval=click_interval if click_interval < 2 else 3)
                return True
        if self._is_story_black():
            if self.appear_then_click(STORY_LETTERS_ONLY, offset=(20, 20), interval=click_interval):
                self._story_option_click = 0
                self.story_popup_timeout.reset()
                return True
        if (click_interval < 2 or self._story_option_timer.reached()) \
                and self.appear(STORY_SKIP_3, offset=(20, 20), interval=0):
            options = self._story_option_buttons_2()
            if not options:
                # 大世界主线适应性选择界面：选项在右侧纵向排列，
                # 点击右上角跳过无效，必须选择一项
                options = self._story_option_buttons_3()
            options_count = len(options)
            logger.attr('剧情选项数量', options_count)
            if options_count:
                logger.attr('剧情选项按钮', [option.button for option in options])
            if not options_count:
                self._story_option_record = 0
                self._story_option_confirm.reset()
            elif options_count == self._story_option_record:
                if self._story_option_confirm.reached() and self._story_option_timer.reached():
                    select = self._identify_siren_device_option(options)

                    is_siren_device = select is not None
                    if is_siren_device:
                        # 识别到塞壬装置则锁定确认，避免后续非装置剧情段把状态覆盖回 False
                        self.is_siren_device_confirmed = True

                    if not is_siren_device:
                        try:
                            select = options[self.config.STORY_OPTION]
                        except IndexError:
                            select = options[0]
                    
                    self.device.click(select)
                    # 选项按钮名按「第几个/共几个」生成，不同剧情段共用同一个名字，
                    # 装置 / 柱子较多的海域会被防连点机制误判为「两个按钮交替点击」
                    # 而报 GameTooManyClickError。因此剧情点击后清空点击记录，
                    # 卡死检测改由连续点击数兜底：剧情一直停在选项画面才会报错。
                    self.device.click_record_clear()
                    self._story_option_click += 1
                    if self._story_option_click >= self._story_option_click_limit:
                        self._story_option_click = 0
                        raise GameTooManyClickError(
                            f'[处理器-剧情] 连续点击剧情选项 {self._story_option_click_limit} 次仍未推进，剧情可能卡住')
                    self._story_option_timer.reset()
                    self.story_popup_timeout.reset()
                    self.interval_reset(STORY_SKIP_3, interval=click_interval if click_interval < 2 else 3)
                    self.interval_reset(STORY_LETTERS_ONLY, interval=click_interval if click_interval < 2 else 3)
                    if click_interval < 2:
                        self._story_confirm.reset()
                    self._story_option_record = 0
                    self._story_option_confirm.reset()
                    return True
            else:
                self._story_option_record = options_count
                self._story_option_confirm.reset()
            if click_interval < 2 and options_count:
                # 选项仍在确认稳定时不点空白区，下一张截图继续选择。
                return False
        story_confirmed = click_interval < 2 \
            and self.appear(STORY_SKIP_3, offset=(20, 20)) and self._story_confirm.reached()
        if self.appear(STORY_SKIP_3, offset=(20, 20), interval=click_interval):
            # 确认是剧情画面
            # 当剧情播放速度为"非常快"时，AzurPilot 可能点击了跳过但剧情已消失
            # 此点击会打断自动搜索
            self.interval_reset([STORY_SKIP_3])
            if story_confirmed or (click_interval >= 2 and self._story_confirm.reached()):
                if drop:
                    drop.handle_add(self, before=2)
                if prefer_skip or self.config.STORY_ALLOW_SKIP:
                    logger.info(f'{STORY_SKIP_3} -> {STORY_SKIP}')
                    self.device.click(STORY_SKIP)
                else:
                    logger.info(f'{STORY_SKIP_3} -> {OS_CLICK_SAFE_AREA}')
                    self.device.click(OS_CLICK_SAFE_AREA)
                self._story_confirm.reset()
                self.story_popup_timeout.reset()
                return True
            else:
                self.interval_clear(STORY_SKIP_3)
        else:
            # 快速推进时，点击冷却不代表剧情消失，不能把画面确认也重置。
            if click_interval >= 2 or not self.appear(STORY_SKIP_3, offset=(20, 20)):
                self._story_option_click = 0
                self._story_confirm.reset()
        if self.appear_then_click(STORY_CLOSE, offset=(10, 10), interval=click_interval):
            self._story_option_click = 0
            self.story_popup_timeout.reset()
            return True

        return False

    def story_skip_interval_clear(self):
        """清除剧情跳过相关按钮的点击间隔。"""
        self.interval_clear(STORY_SKIP_3)
        self.interval_clear(STORY_LETTERS_ONLY)

    def handle_story_skip(self, drop=None):
        """处理剧情跳过。

        通关后重打活动仍可能有剧情，通关模式下通常无剧情，
        但 B3/D3 在威胁等级变为安全前仍有剧情，威胁安全后不再有剧情。

        Args:
            drop (DropImage | None): 掉落记录对象。默认为 None。

        Returns:
            bool: 是否进行了剧情跳过操作。
        """
        # 通关后重打活动仍可能有剧情
        # 通关模式下通常无剧情
        # 但 B3/D3 在威胁等级变为安全前仍有剧情
        # 威胁安全后不再有剧情
        if self.map_is_threat_safe and self.config.Campaign_Event != 'event_20201012_cn':
            return False

        return self.story_skip(drop=drop)

    def ensure_no_story(self, skip_first_screenshot=True):
        """持续检测并确保当前没有剧情。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。
        """
        logger.info('[处理器-剧情] 确保没有剧情')
        story_timer = Timer(3, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.story_skip():
                story_timer.reset()

            if story_timer.reached():
                break

    def handle_map_after_combat_story(self):
        """处理战后地图剧情。

        Returns:
            bool: 是否进行了剧情处理。
        """
        if not self.config.MAP_HAS_MAP_STORY:
            return False

        self.ensure_no_story()
        return True

    def handle_game_tips(self):
        """处理游戏提示弹窗。

        Returns:
            bool: 是否处理了游戏提示。
        """
        if self.appear(GAME_TIPS, offset=(20, 20), interval=2) and self.image_color_count(
                GAME_TIPS.button, color=(40, 40, 40), threshold=15, count=50):
            self.device.click(GAME_TIPS)
            return True
        if self.appear(GAME_TIPS3, offset=(20, 20), interval=2) and self.image_color_count(
                GAME_TIPS3.button, color=(40, 40, 40), threshold=15, count=50):
            self.device.click(GAME_TIPS)
            return True
        if self.appear(GAME_TIPS4, offset=(20, 20), interval=2) and self.image_color_count(
                GAME_TIPS4.button, color=(40, 40, 40), threshold=15, count=50):
            self.device.click(GAME_TIPS)
            return True

        return False

    def manjuu_count(self):
        """通过模板匹配检测小黄鸡数量。

        Returns:
            int: 检测到的小黄鸡数量。
        """
        image = self.image_crop(MANJUU_AREA, copy=False)
        # 默认阈值 0.85 对小黄鸡不适用，因为其面部会被拉伸和压缩
        # 导致模板无法匹配，使用 0.8 来匹配变形后的面部
        buttons = TEMPLATE_MANJUU.match_multi(image, similarity=0.8, name='INFO_MANJUU')
        return len(buttons)

    def wait_until_manjuu_disappear(self):
        """等待小黄鸡加载动画消失。"""
        # 模板对象没有可读名称，这里手动添加字符串用于卡死检测记录
        self.device.stuck_record_add('TEMPLATE_MANJUU')
        timer = Timer(1.5, count=3).start()
        while 1:
            self.device.screenshot()
            if self.manjuu_count():
                timer.reset()
            else:
                if timer.reached():
                    logger.info('[处理器-加载] 小黄鸡已消失')
                    break

    def handle_manjuu(self):
        """处理小黄鸡加载动画。

        Returns:
            bool: 是否检测到并处理了小黄鸡加载。
        """
        count = self.manjuu_count()
        if count > 2:
            logger.info(f'[处理器-加载] 小黄鸡数量: {count}，等待小黄鸡消失')
            self.wait_until_manjuu_disappear()
            return True
        else:
            return False

from scipy import signal

from module.base.base import ModuleBase
from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import *
from module.exception import GameNotRunningError
from module.handler.assets import *
from module.logger import logger
from module.os_handler.assets import CLICK_SAFE_AREA as OS_CLICK_SAFE_AREA
from module.ui_white.assets import POPUP_CANCEL_WHITE, POPUP_CONFIRM_WHITE, POPUP_SINGLE_WHITE


def info_letter_preprocess(image):
    """
    对信息栏文字图像进行预处理，调整对比度。

    Args:
        image: 输入图像。

    Returns:
        处理后的 uint8 图像。
    """
    image = image.astype(float)
    image = (image - 64) / 0.75
    image[image > 255] = 255
    image[image < 0] = 0
    image = image.astype('uint8')
    return image


class InfoHandler(ModuleBase):
    """
    处理游戏中各类弹窗和消息的基类。
    """
    """
    信息栏
    """

    def info_bar_count(self):
        """
        通过顶部蓝色线条检测信息栏数量。

        Returns:
            检测到的信息栏数量。
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
        while 1:
            self.device.screenshot()
            if not self.info_bar_count():
                break

    def handle_info_bar(self):
        if self.info_bar_count():
            self.wait_until_info_bar_disappear()
            return True
        else:
            return False

    def ensure_no_info_bar(self, timeout=0.6, skip_first_screenshot=True):
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

    """
    弹窗信息
    """
    _popup_offset = (3, 30)

    def handle_popup_confirm(self, name='', offset=None, interval=2):
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
            self.device.click(POPUP_CONFIRM_WHITE)
            POPUP_CANCEL_WHITE.name = POPUP_CANCEL_WHITE.name[:-len(name) - 1]
            return True
        return False

    def handle_popup_single(self, name='', offset=None, interval=2):
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
        if self.appear_then_click(POPUP_SINGLE_WHITE, offset=(20, 20), interval=interval):
            return True
        return False

    def popup_interval_clear(self):
        self.interval_clear([
            POPUP_CANCEL, POPUP_CONFIRM,
            POPUP_CANCEL_WHITE, POPUP_CONFIRM_WHITE,
        ])

    _hot_fix_check_wait = Timer(6)

    def handle_urgent_commission(self, drop=None):
        """
        处理紧急委托弹窗。

        Args:
            drop: 掉落图像记录对象，可为 None。

        Returns:
            是否检测到并处理了紧急委托弹窗。
        """
        appear = self.appear(GET_MISSION, offset=True, interval=2)
        if appear:
            logger.info('Get urgent commission')
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
                logger.error('Detected hot fixes from game server, game died')
                raise GameNotRunningError
            # 使用模板匹配（不含颜色匹配），因为维护公告弹窗颜色不同
            if self.appear(LOGIN_CHECK, offset=(30, 30)):
                logger.warning('Account logged out, '
                               'probably because account kicked by server maintenance or another log in')
            self._hot_fix_check_wait.clear()

        return appear

    def handle_combat_low_emotion(self):
        if not self.emotion.is_ignore:
            return False

        result = self.handle_popup_confirm('IGNORE_LOW_EMOTION')
        if result:
            # 避免误点 AUTO_SEARCH_MAP_OPTION_OFF
            self.interval_reset(AUTO_SEARCH_MAP_OPTION_OFF)
        return result

    def handle_use_data_key(self):
        if not self.config.USE_DATA_KEY:
            return False

        if not self.appear(POPUP_CONFIRM, offset=self._popup_offset) \
                and not self.appear(POPUP_CANCEL, offset=self._popup_offset, interval=2):
            return False

        if self.appear(USE_DATA_KEY, offset=(20, 20)):
            # enable USE_DATA_KEY_NOTIFIED
            for _ in self.loop():
                enabled = self.image_color_count(
                    USE_DATA_KEY_NOTIFIED, color=(140, 207, 66), threshold=180, count=10)
                if enabled:
                    break
                if self.appear(USE_DATA_KEY, offset=(20, 20), interval=5):
                    self.device.click(USE_DATA_KEY_NOTIFIED)
                    continue

            self.config.USE_DATA_KEY = False  # 成功后重置，因为任务可能在恢复前被停止
            return self.handle_popup_confirm('USE_DATA_KEY')

        return False

    def handle_vote_popup(self):
        """
        关闭投票弹窗。

        Returns:
            是否处理了投票弹窗。
        """
        # 投票弹窗已于 2023 年移除
        # return self.appear_then_click(VOTE_CANCEL, offset=(20, 20), interval=2)
        return False

    def handle_get_skin(self):
        """
        处理获取皮肤弹窗。

        Returns:
            是否处理了皮肤弹窗。
        """
        return self.appear_then_click(GET_SKIN, offset=(20, 20), interval=2)

    """
    大舰队弹窗
    """

    def handle_guild_popup_confirm(self):
        if self.appear(GUILD_POPUP_CANCEL, offset=self._popup_offset) \
                and self.appear(GUILD_POPUP_CONFIRM, offset=self._popup_offset, interval=2):
            self.device.click(GUILD_POPUP_CONFIRM)
            return True

        return False

    def handle_guild_popup_cancel(self):
        if self.appear(GUILD_POPUP_CONFIRM, offset=self._popup_offset) \
                and self.appear(GUILD_POPUP_CANCEL, offset=self._popup_offset, interval=2):
            self.device.click(GUILD_POPUP_CANCEL)
            return True

        return False

    """
    任务弹窗
    """

    def handle_mission_popup_go(self):
        if self.appear(MISSION_POPUP_ACK, offset=self._popup_offset) \
                and self.appear(MISSION_POPUP_GO, offset=self._popup_offset, interval=2):
            self.device.click(MISSION_POPUP_GO)
            return True

        return False

    def handle_mission_popup_ack(self):
        if self.appear(MISSION_POPUP_GO, offset=self._popup_offset) \
                and self.appear(MISSION_POPUP_ACK, offset=self._popup_offset, interval=2):
            self.device.click(MISSION_POPUP_ACK)
            return True

        return False

    """
    剧情
    """
    story_popup_timeout = Timer(10, count=20)
    map_has_clear_mode = False  # 会在 fast_forward.py 中被覆盖
    map_is_threat_safe = False

    _story_confirm = Timer(0.5, count=1)
    _story_option_timer = Timer(2)
    _story_option_record = 0
    _story_option_confirm = Timer(0.3, count=0)

    def _story_option_buttons(self):
        """
        检测剧情选项按钮（旧版样式）。

        Returns:
            从上到下排列的剧情选项按钮列表，未找到则返回空列表。
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
        """
        检测剧情选项按钮（新版大白色选项样式）。

        Returns:
            从上到下排列的剧情选项按钮列表，未找到则返回空列表。
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

    def _is_story_black(self):
        color = get_color(self.device.image, area=STORY_LETTER_BLACK.area)
        if color_similar(color, STORY_LETTER_BLACK.color, threshold=10):
            return True
        if color_similar(color, (0, 0, 0), threshold=10):
            return True

        return False

    def _identify_siren_device_option(self, options):
        """
        根据固定的 5 选项序列识别塞壬研究装置选项。

        Args:
            options: 检测到的剧情选项按钮列表。

        Returns:
            需要点击的按钮，若非塞壬研究装置则返回 None。
        """
        if len(options) != 5:
            return None

        task = self.config.task.command
        if task not in ('OpsiHazard1Leveling', 'OpsiMeowfficerFarming'):
            task = 'OpsiHazard1Leveling'

        siren_research_enabled = self.config.cross_get(
            keys=f'{task}.OpsiSirenBug.SirenResearch_Enable',
            default=False
        )

        if not siren_research_enabled:
            logger.info('[Story] 塞壬研究装置未启用，选择离开')
            self.siren_device_mode = None
            return options[-1]

        siren_mode = self.config.cross_get(
            keys=f'{task}.OpsiSirenBug.Siren_Mode',
            default='resource'
        )

        if siren_mode == 'enemy':
            logger.info('[Story] 选择反复尝试探测隐藏的敌人')
            self.siren_device_mode = 'enemy'
            return options[2]
        else:
            logger.info('[Story] 选择反复尝试探测隐藏的资源')
            self.siren_device_mode = 'resource'
            return options[3]

    def story_skip(self, drop=None):
        """
        跳过剧情对话。

        2023.09.14 剧情选项变更为中间大白色选项样式，
        通过 STORY_SKIP_3 检测但点击原始 STORY_SKIP。
        """
        if self.story_popup_timeout.started() and not self.story_popup_timeout.reached():
            if self.handle_popup_confirm('STORY_SKIP'):
                self.story_popup_timeout = Timer(10)
                self.interval_reset(STORY_SKIP_3)
                self.interval_reset(STORY_LETTERS_ONLY)
                return True
        if self._is_story_black():
            if self.appear_then_click(STORY_LETTERS_ONLY, offset=(20, 20), interval=2):
                self.story_popup_timeout.reset()
                return True
        if self._story_option_timer.reached() and self.appear(STORY_SKIP_3, offset=(20, 20), interval=0):
            options = self._story_option_buttons_2()
            options_count = len(options)
            logger.attr('Story_options', options_count)
            if options_count:
                logger.attr('Story_option_buttons', [option.button for option in options])
            if not options_count:
                self._story_option_record = 0
                self._story_option_confirm.reset()
            elif options_count == self._story_option_record:
                if self._story_option_confirm.reached():
                    select = self._identify_siren_device_option(options)
                    
                    is_siren_device = select is not None
                    self.is_siren_device_confirmed = is_siren_device
                    
                    if not is_siren_device:
                        try:
                            select = options[self.config.STORY_OPTION]
                        except IndexError:
                            select = options[0]
                    
                    self.device.click(select)
                    self._story_option_timer.reset()
                    self.story_popup_timeout.reset()
                    self.interval_reset(STORY_SKIP_3)
                    self.interval_reset(STORY_LETTERS_ONLY)
                    self._story_option_record = 0
                    self._story_option_confirm.reset()
                    return True
            else:
                self._story_option_record = options_count
                self._story_option_confirm.reset()
        if self.appear(STORY_SKIP_3, offset=(20, 20), interval=2):
            # 确认是剧情画面
            # 当剧情播放速度为"非常快"时，AzurPilot 可能点击了跳过但剧情已消失
            # 此点击会打断自动搜索
            self.interval_reset([STORY_SKIP_3])
            if self._story_confirm.reached():
                if drop:
                    drop.handle_add(self, before=2)
                if self.config.STORY_ALLOW_SKIP:
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
            self._story_confirm.reset()
        if self.appear_then_click(STORY_CLOSE, offset=(10, 10), interval=2):
            self.story_popup_timeout.reset()
            return True

        return False

    def story_skip_interval_clear(self):
        self.interval_clear(STORY_SKIP_3)
        self.interval_clear(STORY_LETTERS_ONLY)

    def handle_story_skip(self, drop=None):
        # 通关后重打活动仍可能有剧情
        # 通关模式下通常无剧情
        # 但 B3/D3 在威胁等级变为安全前仍有剧情
        # 威胁安全后不再有剧情
        if self.map_is_threat_safe and self.config.Campaign_Event != 'event_20201012_cn':
            return False

        return self.story_skip(drop=drop)

    def ensure_no_story(self, skip_first_screenshot=True):
        logger.info('Ensure no story')
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
        if not self.config.MAP_HAS_MAP_STORY:
            return False

        self.ensure_no_story()

    """
    游戏提示
    """

    def handle_game_tips(self):
        """
        处理游戏提示弹窗。

        Returns:
            是否处理了游戏提示。
        """
        if self.appear(GAME_TIPS, offset=(20, 20), interval=2) and self.image_color_count(
                GAME_TIPS.button, color=(40, 40, 40), threshold=240, count=50):
            self.device.click(GAME_TIPS)
            return True
        if self.appear(GAME_TIPS3, offset=(20, 20), interval=2) and self.image_color_count(
                GAME_TIPS3.button, color=(40, 40, 40), threshold=240, count=50):
            self.device.click(GAME_TIPS)
            return True
        if self.appear(GAME_TIPS4, offset=(20, 20), interval=2) and self.image_color_count(
                GAME_TIPS4.button, color=(40, 40, 40), threshold=240, count=50):
            self.device.click(GAME_TIPS)
            return True

        return False

    """
    小黄鸡加载动画
    """

    def manjuu_count(self):
        """
        通过模板匹配检测小黄鸡数量。

        Returns:
            检测到的小黄鸡数量。
        """
        image = self.image_crop(MANJUU_AREA, copy=False)
        # 默认阈值 0.85 对小黄鸡不适用，因为其面部会被拉伸和压缩
        # 导致模板无法匹配，使用 0.8 来匹配变形后的面部
        buttons = TEMPLATE_MANJUU.match_multi(image, similarity=0.8, name='INFO_MANJUU')
        return len(buttons)

    def wait_until_manjuu_disappear(self):
        """
        等待小黄鸡加载动画消失。
        """
        # 模板对象没有可读名称，这里手动添加字符串用于卡死检测记录
        self.device.stuck_record_add('TEMPLATE_MANJUU')
        timer = Timer(1.5, count=3).start()
        while 1:
            self.device.screenshot()
            if self.manjuu_count():
                timer.reset()
            else:
                if timer.reached():
                    logger.info(f'Manjuu disappeared')
                    break
    
    def handle_manjuu(self):
        """
        处理小黄鸡加载动画。

        Returns:
            是否检测到并处理了小黄鸡加载。
        """
        count = self.manjuu_count()
        if count > 2:
            logger.info(f'Manjuu count: {count}, waiting for manjuu to disappear')
            self.wait_until_manjuu_disappear()
            return True
        else:
            return False

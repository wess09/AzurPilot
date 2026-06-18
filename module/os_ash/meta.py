import re
from enum import Enum

import module.config.server as server
from module.base.timer import Timer
from module.combat.combat import BATTLE_PREPARATION
from module.logger import logger
from module.meta_reward.meta_reward import MetaReward
from module.ocr.ocr import Digit, DigitCounter
from module.os_ash.ash import AshCombat
from module.os_ash.assets import *
from module.os_handler.map_event import MapEventHandler
from module.ui.assets import BACK_ARROW
from module.ui.page import page_reward
from module.ui.ui import UI


class MetaState(Enum):
    """META 页面状态枚举。"""
    INIT = 'no meta begin'
    ATTACKING = 'a meta under attack'
    COMPLETE = 'reward to be collected'
    UNDEFINED = 'a undefined page'


OCR_BEACON_TIER = Digit(BEACON_TIER, name='OCR_ASH_TIER')
if server.server != 'jp':
    OCR_META_DAMAGE = Digit(META_DAMAGE, name='OCR_META_DAMAGE')
else:
    OCR_META_DAMAGE = Digit(META_DAMAGE, letter=(201, 201, 201), name='OCR_META_DAMAGE')


class MetaDigitCounter(DigitCounter):
    """META 数字计数器，修正 OCR 常见识别错误。"""

    def after_process(self, result):
        """
        后处理 OCR 结果，修正常见误识别。

        处理逻辑：
        - "00/200" -> "100/200"（首位 0 被识别为数字 0）
        - "23" -> "2/3"（斜杠丢失，仅当首位为 0-3 时修正）
        - "1/40/1400" -> "140/1400"（多余的斜杠）
        """
        result = super().after_process(result)

        # "00/200" -> "100/200"
        if result.startswith('00/'):
            result = '100/' + result[3:]

        # "23" -> "2/3"
        if re.match(r'^[0123]3$', result):
            result = f'{result[0]}/{result[1]}'

        # "1/40/1400" -> "140/1400"
        for suffix in ['/1400', '/200']:
            if result.endswith(suffix):
                point = result[:-len(suffix)]
                point = point.replace('/', '')
                result = point + suffix

        return result


class Meta(UI, MapEventHandler):
    """META 战斗基础模块，处理地图事件和 OCR 识别。"""

    def digit_ocr_point_and_check(self, button: Button, check_number: int):
        """
        OCR 读取按钮上的数字，判断是否达到阈值。

        Args:
            button: 要识别的按钮区域。
            check_number: 判断阈值。

        Returns:
            bool: 识别值是否 >= 阈值。
        """
        point_ocr = MetaDigitCounter(button, letter=(235, 235, 235), threshold=160, name='POINT_OCR')
        point, _, _ = point_ocr.ocr(self.device.image)
        if point >= check_number:
            return True
        return False

    def handle_map_event(self, drop=None):
        """
        处理 META 地图中的各种事件弹窗。

        处理自动攻击完成确认、误入帮助页面、误入战斗准备页面等情况。

        Args:
            drop: 掉落图像处理器。

        Returns:
            bool: 是否采取了行动。
        """
        if super().handle_map_event(drop):
            return True
        if self.appear_then_click(META_AUTO_CONFIRM, offset=(20, 20), interval=2):
            logger.info('Find auto attack complete')
            return True
        if self.appear(HELP_CONFIRM, offset=(30, 30), interval=2):
            logger.info('Accidentally click HELP_ENTER')
            self.device.click(BACK_ARROW)
            return True
        if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
            logger.info('Wrong click into battle preparation page')
            self.device.click(BACK_ARROW)
            return True
        if self.handle_popup_cancel('META'):
            return True
        if self.appear_then_click(META_ENTRANCE, offset=(20, 300), interval=2):
            return True
        return False


def _server_support():
    """当前服务器是否支持信标和 OneHitMode。"""
    return server.server in ['cn', 'en', 'jp', 'tw']


def _server_support_dossier_auto_attack():
    """当前服务器是否支持档案自动攻击。"""
    return server.server in ['cn', 'en']


class OpsiAshBeacon(Meta):
    """余烬信标主任务，处理 META 攻击、奖励领取和任务调度。"""
    _meta_receive = []
    _meta_category = "undefined"

    def _attack_meta(self, skip_first_screenshot=True):
        """
        处理 META 攻击的完整流程。

        根据页面状态分发：INIT 时选择信标或档案，ATTACKING 时执行攻击，
        COMPLETE 时领取奖励。

        Pages:
            in: in_meta
            out: in_meta
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_map_event():
                continue
            state = self._get_state()
            logger.info('Meta state:' + state.name)
            if MetaState.UNDEFINED == state:
                continue
            if MetaState.INIT == state:
                if self._begin_meta():
                    continue
                else:
                    # 正常结束
                    break
            if MetaState.ATTACKING == state:
                # Exit beacon pages when in dossier-only mode
                if self.config.OpsiAshBeacon_AttackMode == 'current_dossier_only' \
                        and self.appear(BEACON_LIST, offset=(20, 20)):
                    self.appear_then_click(ASH_QUIT, offset=(10, 10), interval=2)
                    continue
                if not self._pre_attack():
                    continue
                if self._satisfy_attack_condition():
                    self._make_an_attack()
                    continue
            if MetaState.COMPLETE == state:
                if self.appear(BEACON_LIST, offset=(20, 20)):
                    self._meta_category = "beacon"
                elif self.appear(DOSSIER_LIST, offset=(20, 20)):
                    self._meta_category = "dossier"
                self._handle_ash_beacon_reward()
                if not self._meta_category in self._meta_receive:
                    self._meta_receive.append(self._meta_category)
                # 击杀 META 后检查其他任务是否需要切换
                self.config.check_task_switch()
                continue

    def _make_an_attack(self):
        """
        执行一次 META 战斗。

        战斗期间处理误入战斗准备页面和帮助页面的异常情况，
        战斗结束后确认回到 META 页面。

        Pages:
            in: in_meta, ASH_START
            out: in_meta, ASH_START or BEACON_REWARD
        """
        logger.hr('Begin meta combat', level=2)

        def expected_end():
            # 误入战斗准备页面，点击返回
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                logger.info('Wrong click into battle preparation page')
                self.device.click(BACK_ARROW)
                return False
            # 误入帮助确认页面，点击帮助入口返回
            if self.appear(HELP_CONFIRM, offset=(30, 30), interval=3):
                logger.info('Wrong click into HELP_CONFIRM')
                self.device.click(HELP_ENTER)
                return False
            # 已回到 META 页面，战斗结束
            if self._in_meta_page():
                logger.info('Meta combat finished and in correct page.')
                return True

            return False

        # 执行战斗
        combat = AshCombat(config=self.config, device=self.device)
        combat.combat(expected_end=expected_end, save_get_items=False, emotion_reduce=False)

    def _handle_ash_beacon_reward(self, skip_first_screenshot=True):
        """
        领取 META 击杀奖励。

        点击奖励按钮直到奖励界面消失，回到 META 页面。

        Pages:
            in: in_meta, BEACON_REWARD
            out: in_meta
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件：奖励按钮消失且回到 META 页面
            if not self.appear(BEACON_REWARD, offset=(30, 30)):
                if self._in_meta_page():
                    break

            # 点击领取奖励
            if self.appear_then_click(BEACON_REWARD, offset=(30, 30), interval=2):
                logger.info('Reap meta rewards')
                continue
            # 处理随机事件
            if self.handle_map_event():
                continue
            # 误回到主页面时，点击奖励入口返回
            if self.ui_main_appear_then_click(page_reward, interval=2):
                continue
            if self.appear(META_ENTRANCE, offset=(20, 300), interval=2):
                continue

    def _satisfy_attack_condition(self):
        """
        检查当前 META 是否满足攻击条件。

        信标模式下：开启 OneHitMode 且已造成伤害时，不再攻击。
        档案模式下：META 正在自动攻击时，不再手动攻击。

        Returns:
            bool: 是否满足攻击条件（始终返回 True，不满足时通过 task_stop 提前终止）。
        """
        if self.appear(BEACON_LIST, offset=(20, 20)):
            # 开启 OneHitMode 且已对当前 META 造成伤害
            if _server_support() and self.config.OpsiAshBeacon_OneHitMode:
                damage = self._get_meta_damage()
                if damage > 0:
                    logger.info('Enable OneHitMode and meta damage is ' + str(damage) + ', check after 30 minutes')
                    self.config.task_delay(minute=30)
                    self.config.task_stop()
        if self.appear(DOSSIER_LIST, offset=(20, 20)):
            # META 正在自动攻击中
            if self.appear(META_AUTO_ATTACKING, offset=(20, 20)):
                logger.info('This meta is auto attacking, check after 15 minutes')
                self.config.task_delay(minute=15)
                self.config.task_stop()
        return True

    def _get_meta_damage(self):
        """
        获取当前 META 已造成的伤害值。

        Returns:
            int: OCR 识别的伤害数值。
        """
        self._ensure_meta_inner_page_damage()
        return OCR_META_DAMAGE.ocr(self.device.image)

    def _ensure_meta_inner_page_damage(self, skip_first_screenshot=True):
        """
        切换 META 内部页面到伤害标签页。

        如果当前在详情页，则点击切换到伤害页。

        Pages:
            in: in_meta, ASH_START
            out: in_meta, META_INNER_PAGE_DAMAGE, ASH_START
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.match_template_color(META_INNER_PAGE_DAMAGE, offset=(20, 20)):
                logger.info('Already in meta damage page')
                break
            if self.match_template_color(META_INNER_PAGE_NOT_DAMAGE, offset=(20, 20)):
                logger.info('In meta details page, should switch to damage page')
                self.appear_then_click(META_INNER_PAGE_NOT_DAMAGE, offset=(20, 20), interval=2)
                continue

    def _pre_attack(self):
        """
        攻击前的准备工作。

        信标模式下：根据配置请求协助。
        档案模式下：cn/en 服务器支持自动攻击，其他服务器暂不处理。

        Returns:
            bool: 是否准备就绪。
        """
        # 信标页面
        if self.appear(BEACON_LIST, offset=(20, 20)):
            if self.config.OpsiAshBeacon_OneHitMode or self.config.OpsiAshBeacon_RequestAssist:
                if not self._ask_for_help():
                    return False
            return True
        # 档案页面
        if self.appear(DOSSIER_LIST, offset=(20, 20)):
            # 支持自动攻击且未在自动攻击中
            if _server_support_dossier_auto_attack() and self.config.OpsiAshBeacon_DossierAutoAttackMode \
                    and self.appear(META_AUTO_ATTACK_START, offset=(5, 5)):
                return self._dossier_auto_attack()
            return True
        return False

    def _ask_for_help(self):
        """
        请求协助，从好友、大舰队和世界频道发起求助。

        依次点击三个求助按钮，然后确认。

        Returns:
            bool: 是否成功发起协助。如果 META 在请求协助后刚好完成则返回 False。

        Pages:
            in: is_in_meta
            out: is_in_meta
        """
        # 进入帮助页面
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件：帮助确认页面出现
            if self.appear(HELP_CONFIRM, offset=(20, 20)):
                break
            # 点击帮助入口
            if self.appear_then_click(HELP_ENTER, offset=(20, 20), interval=3):
                continue
            # 误入战斗准备页面，点击返回
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                self.device.click(BACK_ARROW)
                continue

        # 依次点击三个求助按钮，无需确认选中状态
        self.device.click(HELP_3)
        self.device.sleep((0.1, 0.3))
        self.device.click(HELP_2)
        self.device.sleep((0.1, 0.3))
        self.device.click(HELP_1)

        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件：帮助确认页面消失
            # 有时帮助弹窗没有黑色模糊背景，HELP_CONFIRM 和 HELP_ENTER 同时出现
            if not self.appear(HELP_CONFIRM, offset=(30, 30)):
                if self.appear(HELP_ENTER, offset=(30, 30)):
                    return True
                # META 刚好在请求协助后完成
                if self.appear(BEACON_REWARD, offset=(30, 30)):
                    logger.info('META finished just after calling assist, ignore meta assist')
                    return False
            # 点击确认
            if self.appear_then_click(HELP_CONFIRM, offset=(30, 30), interval=3):
                continue

    def _dossier_auto_attack(self):
        """
        启动档案自动攻击。

        点击自动攻击开始按钮并确认，直到出现自动攻击中的标记。

        Returns:
            bool: 是否成功开启自动攻击。

        Pages:
            in: is_in_meta & not auto attacking
            out: is_in_meta
        """
        timeout = Timer(10, count=20).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件：自动攻击中
            if self.appear(META_AUTO_ATTACKING, offset=(5, 5)):
                return True
            if timeout.reached():
                logger.warning('Run _dossier_auto_attack timeout, probably because META_AUTO_ATTACK_START was missing')
                return False
            # 已被他人击杀
            if self.appear(BEACON_REWARD, offset=(30, 30)):
                return False

            # 点击自动攻击确认和开始按钮
            if self.appear_then_click(META_AUTO_ATTACK_CONFIRM, offset=(5, 5), interval=3):
                continue
            if self.appear_then_click(META_AUTO_ATTACK_START, offset=(5, 5), interval=3):
                continue
            # 误入战斗准备页面，点击返回
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                self.device.click(BACK_ARROW)
                continue

    def _begin_meta(self):
        """
        无论当前在哪个 META 页面，选择或开始一个 META 战斗。

        META 主页面下：选择信标或档案入口进入。
        信标/档案页面下：开始新的 META 战斗，或返回主页面。

        Returns:
            bool: 是否需要继续循环。
        """
        
        attack_mode = self.config.OpsiAshBeacon_AttackMode
        # META 主页面
        if self.appear(ASH_SHOWDOWN, offset=(30, 30), interval=2):
            # 信标入口
            if attack_mode != 'current_dossier_only':
                if self._check_beacon_point():
                    self.device.click(META_MAIN_BEACON_ENTRANCE)
                    logger.info('Select beacon entrance into')
                    return True
            # 档案入口

            if _server_support() \
                    and attack_mode != 'current' \
                    and self._check_dossier_point():
                if self.appear_then_click(META_MAIN_DOSSIER_ENTRANCE, offset=(20, 20), interval=2):
                    logger.info('Select dossier entrance into')
                    return True
                else:
                    logger.info('None dossier has been selected')
            return False
        # 信标页面
        elif self.appear(BEACON_LIST, offset=(20, 20), interval=2):
            if attack_mode == 'current_dossier_only':
                self.appear_then_click(ASH_QUIT, offset=(10, 10), interval=2)
                return True
            if self._check_beacon_point():
                self.device.click(META_BEGIN_ENTRANCE)
                logger.info('Begin a beacon')
            return True
        # 档案页面
        elif _server_support() \
                and self.appear(DOSSIER_LIST, offset=(20, 20), interval=2):
            if attack_mode != 'current' \
                    and self._check_dossier_point():
                if self.appear_then_click(META_BEGIN_ENTRANCE, offset=(20, 20), interval=2):
                    logger.info('Begin a dossier')
                    return True
                else:
                    logger.info('None dossier has been selected')
            self.appear_then_click(ASH_QUIT, offset=(10, 10), interval=2)
            return True
        # 未知页面
        else:
            return True

    def _check_beacon_point(self) -> bool:
        """
        检查信标积分是否 >= 100。

        Returns:
            bool: 积分是否满足开启条件。
        """
        if self.appear(META_BEACON_FLAG, offset=(180, 20)):
            META_BEACON_DATA.load_offset(META_BEACON_FLAG)
            return self.digit_ocr_point_and_check(META_BEACON_DATA.button, 100)
        return False

    def _check_dossier_point(self) -> bool:
        """
        检查档案积分是否 >= 100。

        Returns:
            bool: 积分是否满足开启条件。
        """
        if self.appear(META_DOSSIER_FLAG, offset=(180, 20)):
            META_DOSSIER_DATA.load_offset(META_DOSSIER_FLAG)
            return self.digit_ocr_point_and_check(META_DOSSIER_DATA.button, 100)
        return False

    def _get_state(self):
        """
        判断当前 META 页面状态。

        Returns:
            MetaState: 当前页面状态枚举值。
        """
        # 未知页面
        if not self._in_meta_page():
            return MetaState.UNDEFINED
        # 信标或档案页面
        elif self.appear(BEACON_LIST, offset=(20, 20)) \
                or self.appear(DOSSIER_LIST, offset=(20, 20)):
            if self.appear(HELP_ENTER, offset=(30, 30)):
                return MetaState.ATTACKING
            elif self.appear(BEACON_REWARD, offset=(20, 20)):
                return MetaState.COMPLETE
            return MetaState.INIT
        elif self.appear(ASH_SHOWDOWN, offset=(30, 30)):
            return MetaState.INIT
        return MetaState.UNDEFINED

    def _in_meta_page(self):
        """判断当前是否在 META 相关页面（主页面、信标或档案）。"""
        return self.appear(ASH_SHOWDOWN, offset=(30, 30)) \
               or self.appear(BEACON_LIST, offset=(20, 20)) \
               or self.appear(DOSSIER_LIST, offset=(20, 20))

    def _ensure_meta_page(self, skip_first_screenshot=True):
        """
        确保当前在 META 页面，不在则通过点击入口进入。

        Pages:
            in: page_reward
            out: in_meta
        """
        logger.info('Ensure beacon attack page')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._in_meta_page():
                logger.info('In meta page')
                return True
            if self.handle_map_event():
                continue
            if self.appear_then_click(META_ENTRANCE, offset=(20, 300), interval=2):
                continue

    def ensure_dossier_page(self, skip_first_screenshot=True):
        """
        确保当前在档案页面。

        先导航到奖励页面，再进入 META 页面，最后切换到档案标签。

        Pages:
            in: page_reward
            out: in_meta, DOSSIER_LIST
        """
        self.ui_ensure(page_reward)
        self._ensure_meta_page()
        logger.info('Ensure dossier meta page')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(DOSSIER_LIST, offset=(20, 20)):
                logger.info('In dossier page')
                return True
            if self.handle_map_event():
                continue
            if self.appear(ASH_SHOWDOWN, offset=(30, 30)):
                self.device.click(META_MAIN_DOSSIER_ENTRANCE)
                continue

    def _begin_beacon(self):
        """开始信标攻击流程，确保进入 META 页面后执行攻击。"""
        logger.hr('Meta Beacon Attack')
        if not _server_support():
            logger.info("Server not support dossier beacon and OneHitMode, please contact the developer.")
        self._ensure_meta_page()
        self._attack_meta()

    def run(self):
        """执行信标攻击任务主流程：进入 META 页面、攻击、领取奖励、延迟到下次服务器更新。"""
        self.ui_ensure(page_reward)
        self._begin_beacon()

        with self.config.multi_set():
            for meta in self._meta_receive:
                MetaReward(self.config, self.device).run(category=meta)
            self._meta_receive = []
            self.config.task_delay(server_update=True)


class AshBeaconAssist(Meta):
    """余烬信标协助任务，处理他人的信标求助。"""

    def _attack_meta(self, skip_first_screenshot=True):
        """
        协助攻击 META 信标。

        在信标列表中查找可用的信标，检查剩余协助次数后发起攻击。

        Returns:
            bool: 是否找到了可攻击的信标。

        Pages:
            in: page_reward
            out: page_reward
        """
        timeout = Timer(3, count=9).start()
        appeared = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not appeared and timeout.reached():
                logger.info('No meta beacon found, delay task OpsiAshAssist')
                break

            if self.handle_map_event():
                continue
            if self.appear(ASH_START, offset=(20, 20)):
                appeared = True
                remain_times = self.digit_ocr_point_and_check(BEACON_REMAIN, 1)
                if remain_times:
                    self._ensure_meta_level()
                    self._make_an_attack()
                else:
                    logger.info('No enough assist times, complete')
                    break

        return appeared

    def _make_an_attack(self):
        """
        执行一次 META 协助战斗。

        战斗结束后确认回到协助页面，处理误入战斗准备和主页的异常情况。

        Pages:
            in: in_meta_assist
            out: in_meta_assist
        """
        logger.hr('Begin meta assist combat', level=2)

        def expected_end():
            # 误入战斗准备页面，点击返回
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                logger.info('Wrong click into battle preparation page')
                self.device.click(BACK_ARROW)
                return False
            # 协助后被重定向到自己的未完成信标，切换回信标列表
            if self.appear_then_click(BEACON_LIST, offset=(-20, -5, 300, 5), interval=2):
                return False
            # 回到 META 主页面，点击信标入口
            if self.appear(ASH_SHOWDOWN, offset=(30, 30), interval=2):
                logger.info('Meta combat finished at ASH_SHOWDOWN.')
                self.device.click(META_MAIN_BEACON_ENTRANCE)
            # 已回到协助页面
            if self._in_meta_assist_page():
                logger.info('Meta combat finished and in correct page.')
                return True

            return False

        # 执行战斗
        combat = AshCombat(config=self.config, device=self.device)
        combat.combat(expected_end=expected_end, save_get_items=False, emotion_reduce=False)

    def _ensure_meta_level(self):
        """
        选择满足等级要求的 META 信标。

        等待信标等级数字显示后，通过 OCR 读取等级，
        不满足则翻页查找，最多尝试 5 次。
        """
        # 等待 BEACON_TIER 显示——进入信标列表时等级数字不会立即出现
        tier = self.config.OpsiAshAssist_Tier
        logger.info('Begin find a level ' + str(tier) + ' meta')
        for n in range(10):
            if self.image_color_count(BEACON_TIER, color=(0, 0, 0), threshold=221, count=50):
                break

            self.device.screenshot()
            if n >= 9:
                logger.warning('Waiting for beacon tier timeout')
        # 选择信标
        current = -1
        for _ in range(5):
            current = OCR_BEACON_TIER.ocr(self.device.image)
            if current >= tier:
                break
            else:
                self.device.click(BEACON_NEXT)
                self.device.sleep((0.3, 0.5))
                self.device.screenshot()
        if current < tier:
            logger.info(f'Tier {tier} beacon not found after 5 trial, use current beacon')
        logger.info('Find a beacon in level:' + str(current))

    def _in_meta_assist_page(self):
        """判断当前是否在信标协助页面。"""
        return self.appear(BEACON_MY, offset=(20, 20))

    def _ensure_meta_assist_page(self, skip_first_screenshot=True):
        """
        确保当前在信标协助页面。

        从 META 入口进入，处理各种中间页面跳转。

        Pages:
            in: page_reward or in_meta
            out: in_meta_assist
        """
        logger.info('Ensure beacon assist page')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._in_meta_assist_page():
                logger.info('In beacon assist page')
                return True
            if self.handle_map_event():
                continue
            if self.appear_then_click(META_ENTRANCE, offset=(20, 300), interval=2):
                continue
            if self.appear(ASH_SHOWDOWN, offset=(20, 20), interval=2):
                self.device.click(META_MAIN_BEACON_ENTRANCE)
                logger.info('In meta page main')
                continue
            if self.appear_then_click(BEACON_LIST, offset=(300, 20), interval=2):
                continue
            if self.appear_then_click(DOSSIER_LIST, offset=(20, 20), interval=2):
                logger.info('In meta page dossier')
                continue

    def _begin_meta_assist(self):
        """开始信标协助流程，确保进入协助页面后执行攻击。"""
        logger.hr('Meta Beacon Assist')
        self._ensure_meta_assist_page()
        return self._attack_meta(skip_first_screenshot=False)

    def run(self):
        """
        执行信标协助任务主流程。

        成功协助后领取奖励并延迟到下次服务器更新；
        未找到可协助的信标则延迟 10-20 分钟后重试。
        """
        self.ui_ensure(page_reward)

        if self._begin_meta_assist():
            MetaReward(self.config, self.device).run()
            self.config.task_delay(server_update=True)
        else:
            self.config.task_delay(minute=(10, 20))

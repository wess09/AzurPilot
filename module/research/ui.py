"""
科研系统 UI 操作基类。

本模块提供科研系统的底层 UI 操作，包括：
- 页面检测：判断当前是否在科研主页或队列页面
- 页面稳定性等待：等待科研卡片动画完成
- 队列页面的进入和退出导航
- 奖励物品的获取和掉落记录
- 科研项目状态检测：通过模板匹配识别 waiting/running/detail 状态
- 科研详情页的退出和取消操作

本模块作为 ResearchSelector、ResearchQueue 和 RewardResearch
的共同基类，提供统一的 UI 操作接口。

术语对照：
    科研队列(Research Queue): 科研页面中可容纳 5 个排队项目的区域
    详情页(Detail): 点击科研项目后展开的详细信息页面
    获取物品界面(Get Items): 领取科研奖励后弹出的物品展示界面
"""
from module.base.timer import Timer
from module.base.utils import crop, rgb2gray
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3, GET_ITEMS_3_CHECK
from module.logger import logger
from module.research.assets import *
from module.research.project import RESEARCH_STATUS
from module.research.series import RESEARCH_SCALING
from module.ui.assets import BACK_ARROW, RESEARCH_CHECK
from module.ui.ui import UI


class ResearchUI(UI):
    """
    科研系统 UI 操作基类，提供科研页面的底层交互方法。

    所有科研相关的 UI 操作（页面检测、稳定性等待、队列导航、
    奖励领取、状态检测等）封装在此类中，供上层模块组合使用。

    继承自 UI 基类，获得页面导航和通用 UI 操作能力。
    """
    def is_in_research(self, interval=0):
        """
        检测当前是否在科研主页（项目列表页面）。

        Args:
            interval (int): 按钮检测的时间间隔，0 表示每次都检测。

        Returns:
            bool: 是否在科研主页。
        """
        return self.appear(RESEARCH_CHECK, offset=(20, 20), interval=interval)

    def is_in_queue(self, interval=0):
        """
        检测当前是否在科研队列页面。

        Args:
            interval (int): 按钮检测的时间间隔，0 表示每次都检测。

        Returns:
            bool: 是否在科研队列页面。
        """
        return self.appear(QUEUE_CHECK, offset=(20, 20), interval=interval)

    def ensure_research_stable(self):
        """
        等待科研项目列表页面的动画稳定。

        确保科研卡片的切换/加载动画完成后才进行后续操作，
        避免因动画未完成导致的误检测。
        """
        self.wait_until_stable(STABLE_CHECKER)

    def ensure_research_center_stable(self):
        """
        等待科研项目列表中心区域的动画稳定。

        与 ensure_research_stable 类似，但使用中心区域的检测器，
        适用于从队列页面返回等场景。
        """
        self.wait_until_stable(STABLE_CHECKER_CENTER)

    def queue_enter(self, skip_first_screenshot=True):
        """进入科研队列界面。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Pages:
            in: is_in_research
            out: is_in_queue
        """
        self.ui_click(RESEARCH_GOTO_QUEUE, check_button=self.is_in_queue, appear_button=self.is_in_research,
                      retry_wait=1, skip_first_screenshot=skip_first_screenshot)

    def queue_quit(self):
        """退出科研队列界面，返回科研主界面。

        Pages:
            in: is_in_queue
            out: is_in_research 且画面稳定
        """
        logger.info('[科研-队列] 退出队列')
        for _ in self.loop():
            if self.is_research_stabled():
                break
            if self.is_in_queue(interval=3):
                self.device.click(BACK_ARROW)
                continue
            # 处理可能延迟弹出的获得道具弹窗
            if self.appear(GET_ITEMS_1, offset=(20, 20), interval=3):
                logger.info(f'[科研-队列] {GET_ITEMS_1} -> {GET_ITEMS_RESEARCH_SAVE}')
                self.device.click(GET_ITEMS_RESEARCH_SAVE)
                continue
            if self.appear(GET_ITEMS_2, offset=(20, 20), interval=3):
                logger.info(f'[科研-队列] {GET_ITEMS_1} -> {GET_ITEMS_RESEARCH_SAVE}')
                self.device.click(GET_ITEMS_RESEARCH_SAVE)
                continue

        self.ensure_research_center_stable()

    def get_items(self):
        """检测并返回当前出现的获得物资/道具弹窗按钮。

        Returns:
            Button | None: 匹配到的获得道具按钮；未出现时返回 None。
        """
        if self.appear(GET_ITEMS_3, offset=(5, 5)):
            if self.image_color_count(GET_ITEMS_3_CHECK, color=(255, 255, 255), threshold=30, count=100):
                return GET_ITEMS_3
            else:
                return GET_ITEMS_2
        # On EN, the title of 2-row GET_ITEMS is 7px lower than GET_ITEMS_3,
        # which is out of the offset above, so check GET_ITEMS_2 directly
        if self.appear(GET_ITEMS_2, offset=(5, 5)):
            return GET_ITEMS_2
        if self.appear(GET_ITEMS_1, offset=(5, 5)):
            return GET_ITEMS_1
        return None

    def drop_record(self, drop):
        """记录科研完成后的掉落截图。

        针对不同类型的获得道具弹窗进行截图，大弹窗（GET_ITEMS_3）还会滑动以截取完整掉落。

        Args:
            drop (DropRecord): 掉落记录统计对象。
        """
        if not drop:
            return
        start = drop.count
        button = self.get_items()
        if button == GET_ITEMS_1 or button == GET_ITEMS_2:
            self.device.sleep(0.5)
            self.device.screenshot()
            drop.add(self.device.image)
        elif button == GET_ITEMS_3:
            self.device.sleep(1.5)
            self.device.screenshot()
            drop.add(self.device.image)

            self.device.swipe_vector((0, 250), box=ITEMS_3_SWIPE.area, random_range=(-10, -10, 10, 10),
                                     padding=0)
            self.device.sleep(2)
            self.device.screenshot()
            drop.add(self.device.image)

        if hasattr(drop, 'finish_research_reward'):
            drop.finish_research_reward(start)

    def get_research_status(self, image):
        """检测科研主页 5 个槽位的当前项目状态。

        Args:
            image (np.ndarray): 游戏画面截图。

        Returns:
            list[str]: 包含 5 个槽位状态的字符串列表（'waiting' / 'running' / 'detail' / 'unknown'）。
        """
        out = []
        for index, status, scaling in zip(range(5), RESEARCH_STATUS, RESEARCH_SCALING):
            info = status.crop((0, -40, 200, 0))
            piece = rgb2gray(crop(image, info.area, copy=False))
            if TEMPLATE_WAITING.match(piece, scaling=scaling, similarity=0.75):
                out.append('waiting')
            elif TEMPLATE_RUNNING.match(piece, scaling=scaling, similarity=0.75):
                out.append('running')
            elif TEMPLATE_DETAIL.match(piece, scaling=scaling, similarity=0.75):
                out.append('detail')
            else:
                out.append('unknown')

        logger.info(f'[科研-状态] 科研状态: {out}')
        return out

    def is_research_stabled(self):
        """
        检测科研主页是否已稳定（无动画进行中）。

        通过检测是否存在 'detail' 状态的项目来判断页面是否已加载完成。

        Returns:
            bool: 科研主页是否已稳定。
        """
        return self.is_in_research() and 'detail' in self.get_research_status(self.device.image)

    def research_detail_quit(self, skip_first_screenshot=True):
        """
        从科研详情页退回科研主页。

        点击详情页的退出按钮，等待回到稳定的项目列表页面。
        不取消正在进行的科研项目。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。
        """
        logger.info('[科研-详情] 退出科研详情')
        click_timer = Timer(10)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_research_stabled():
                break

            if self.appear(RESEARCH_UNAVAILABLE, offset=(20, 20)) \
                    or self.appear(RESEARCH_START, offset=(20, 20)) \
                    or self.appear(RESEARCH_STOP, offset=(20, 20)):
                if click_timer.reached():
                    self.device.click(RESEARCH_DETAIL_QUIT)
                    click_timer.reset()

    def research_detail_cancel(self, skip_first_screenshot=True):
        """
        取消正在进行的科研项目并退回科研主页。

        点击停止按钮取消当前项目，确认弹窗后等待回到稳定的项目列表页面。
        与 research_detail_quit 不同，此方法会取消正在运行的科研。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。
        """
        logger.info('[科研-详情] 取消科研项目')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_research_stabled():
                break

            if self.appear_then_click(RESEARCH_STOP, offset=(20, 20), interval=5):
                continue
            if self.handle_popup_confirm('RESEARCH_CANCEL'):
                continue
            if self.appear(RESEARCH_START, offset=(20, 20), interval=5):
                self.device.click(RESEARCH_DETAIL_QUIT)
                continue

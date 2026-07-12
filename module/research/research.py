from datetime import timedelta

import numpy as np

from module.base.timer import Timer
from module.base.utils import rgb2gray
from module.config.time_source import now as current_time
from module.exception import GameTooManyClickError
from module.logger import logger
from module.ocr.ocr import Duration
from module.research.assets import *
from module.research.project import get_research_finished
from module.research.rqueue import ResearchQueue
from module.research.selector import RESEARCH_ENTRANCE, ResearchSelector
from module.storage.storage import StorageHandler
from module.ui.assets import RESEARCH_CHECK
from module.ui.page import page_research

OCR_DURATION = Duration(RESEARCH_LAB_DURATION_REMAIN, letter=(255, 255, 255), threshold=64,
                        name='RESEARCH_LAB_DURATION_REMAIN')


class RewardResearch(ResearchSelector, ResearchQueue, StorageHandler):
    _research_project_offset = 0
    _research_finished_index = 2
    research_project_started = None  # ResearchProject 对象
    enforce = False
    end_time = None

    def research_has_finished(self):
        """
        已完成的科研项目应自动聚焦到中央位置，但有时由于未知的游戏 bug 未能实现。

        Returns:
            bool: 是否有已完成的科研项目
        """
        index = get_research_finished(self.device.image)
        if index is not None:
            logger.attr('Research_finished', index)
            self._research_finished_index = index
            return True
        else:
            return False

    def research_reset(self, drop=None, skip_first_screenshot=True):
        """
        Args:
            drop (DropImage):
            skip_first_screenshot (bool):

        Returns:
            bool: 重置是否成功
        """
        if not self.appear(RESET_AVAILABLE, threshold=10):
            logger.info('Research reset unavailable')
            return False

        logger.info('Research reset')
        drop.add(self.device.image)
        executed = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(RESET_AVAILABLE, interval=10, threshold=10):
                continue
            if self.handle_popup_confirm('RESEARCH_RESET'):
                executed = True
                continue

            # 结束条件
            if executed and self.is_in_research():
                self.ensure_no_info_bar(timeout=3)  # 刷新成功
                self.ensure_research_stable()
                break

        self._research_project_offset = 0
        return True

    def research_enforce(self, drop=None, add_queue=True):
        """
        Args:
            drop (DropImage):
            add_queue (bool): 是否加入队列。
                第 6 个项目无法加入队列，因此需要此开关。
        """
        if not self.enforce:
            logger.info('Enforce choosing research project')
            self.enforce = True
            return self.research_select(self.research_sort_filter(self.enforce),
                                        drop=drop, add_queue=add_queue)
        return True

    def research_select(self, priority, drop=None, add_queue=True):
        """
        Args:
            priority (list): ResearchProject 对象和预设字符串的列表，
                如 [object, object, object, 'reset']
            drop (DropImage):
            add_queue (bool): 是否加入队列。
                第 6 个项目无法加入队列，因此需要此开关。

        Returns:
            bool: 如果已重置则返回 False
        """
        if not len(priority):
            logger.info('No research project satisfies current filter')
            return self.research_enforce(drop=drop, add_queue=add_queue)
        for project in priority:
            # 优先级示例：['reset', 'shortest']
            if project == 'reset':
                if self.research_reset(drop=drop):
                    return False
                else:
                    continue

            if isinstance(project, str):
                # 优先级示例：['shortest']
                if project == 'shortest':
                    self.research_select(self.research_sort_shortest(self.enforce),
                                         drop=drop, add_queue=add_queue)
                elif project == 'cheapest':
                    self.research_select(self.research_sort_cheapest(self.enforce),
                                         drop=drop, add_queue=add_queue)
                else:
                    logger.warning(f'Unknown select method: {project}')
                return True
            elif project.genre.upper() in ['C', 'T'] and not self.enforce:
                return self.research_enforce(drop=drop, add_queue=add_queue)
            else:
                # 优先级示例：[ResearchProject, ResearchProject,]
                ret = self.research_project_start_with_requirements(project, add_queue=add_queue)
                if ret:
                    return True
                elif ret is not None and self.config.Research_RemainingCommissions > 0:
                    logger.info('Delay research due to genre T research')
                    return True
                elif ret is not None and self.research_delay_check():
                    logger.info('Delay research when resources not enough and queue not empty')
                    return True
                else:
                    continue

        logger.info('No research project started')
        return self.research_enforce(drop=drop, add_queue=add_queue)

    def research_delay_check(self):
        """
        检查是否允许延迟科研。

        Returns:
            bool: 是否允许延迟科研
        """
        if self.config.Research_AllowDelay:
            slot = self.get_queue_slot()
            if slot < 4:
                return True
            if slot == 4:
                if self.end_time <= current_time():
                    return True
                elif self.end_time + timedelta(minutes=-10) > current_time():
                    return True

        return False

    def research_project_start(self, project, add_queue=True, skip_first_screenshot=True):
        """
        启动指定项目并将其加入科研队列。

        Args:
            project (ResearchProject, int): 项目对象或项目索引（0 到 4）。
            add_queue (bool): 是否加入队列。
                第 6 个项目无法加入队列，因此需要此开关。
            skip_first_screenshot:

        Returns:
            bool: 启动是否成功。
            None: 要启动的项目不在已知项目列表中。

        Pages:
            in: is_in_research
            out: is_in_research
        """
        logger.hr('Research project start')
        logger.info(f'Research project: {project}')
        if isinstance(project, int):
            index = project
        elif project in self.projects:
            index = self.projects.index(project)
        else:
            logger.warning(f'The project to start: {project} is not in known projects')
            return None
        logger.info(f'Research project: {index}')
        self.interval_clear([RESEARCH_START])
        self.popup_interval_clear()
        available = False
        click_timer = Timer(10)
        click_count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            max_rgb = np.max(rgb2gray(self.image_crop(RESEARCH_UNAVAILABLE, copy=False)))

            # 此处不使用 interval，RESEARCH_CHECK 已在 5 秒前出现过
            if click_timer.reached() and self.is_in_research():
                i = (index - self._research_project_offset) % 5
                logger.info(f'Project offset: {self._research_project_offset}, project {index} is at {i}')
                self.device.click(RESEARCH_ENTRANCE[i])
                self.ensure_research_stable()
                click_count += 1
                click_timer.reset()
                continue
            if max_rgb > 235 and self.appear_then_click(RESEARCH_START, offset=(5, 20), interval=10):
                available = True
                continue
            if self.handle_popup_confirm('RESEARCH_START'):
                continue

            # 结束条件
            if click_count >= 3:
                logger.error('Unable to start a research project after 3 trail, '
                             'probably because there is a research running but requirements not satisfied, '
                             'or a research finished')
                raise GameTooManyClickError
            if self.appear(RESEARCH_STOP, offset=(20, 20)):
                # RESEARCH_STOP 是半透明按钮，颜色会随背景变化
                if add_queue:
                    if not self.research_queue_add():
                        self.research_project_started = None
                        self._research_project_offset = (index - 2) % 5
                        return False
                else:
                    self.research_detail_quit()
                # self.ensure_no_info_bar(timeout=3)  # 科研已启动
                self.research_project_started = project
                self._research_project_offset = (index - 2) % 5
                return True
            if not available and max_rgb <= 235 \
                    and self.appear(RESEARCH_UNAVAILABLE, offset=(5, 20)):
                logger.info('Not enough resources to start this project')
                self.research_detail_quit()
                self.research_project_started = None
                self._research_project_offset = (index - 2) % 5
                return False

    def research_project_start_with_requirements(self, project, add_queue=True):
        """
        启动指定项目并将其加入科研队列，同时处理项目所需的前提条件。

        Args:
            project (ResearchProject, int): 项目对象或项目索引（0 到 4）。
            add_queue (bool): 是否加入队列。
                第 6 个项目无法加入队列，因此需要此开关。

        Returns:
            bool: 启动是否成功。
            None: 要启动的项目不在已知项目列表中。

        Pages:
            in: is_in_research
            out: is_in_research
        """
        # 项目索引，直接调用
        if isinstance(project, int):
            return self.research_project_start(project, add_queue=add_queue)
        elif project.genre == 'E' and project.equipment_amount > 0:
            logger.info(f'Going to start an E series research: {project} '
                        f'and disassemble {project.equipment_amount} equipment')
            # 启动项目
            self.research_project_start(project, add_queue=False)
            # 拆解装备
            self.storage_disassemble_equipment(amount=project.equipment_amount)
            # 返回科研界面
            self.ui_ensure(page_research)
            self.research_project_list_init()
            # 加入队列
            result = self.research_project_start(project, add_queue=add_queue)
            if result is None:
                logger.error('Research project is missing after disassemble equipment')
            return result
        elif project.genre == 'T':
            logger.info(f'Going to start a T series research: {project}')
            self.research_project_start(project, add_queue=False)
            self.config.Research_RemainingCommissions = project.commission_amount
            self.research_project_started = None
            return False
        else:
            # 普通项目
            return self.research_project_start(project, add_queue=add_queue)

    def research_receive(self, skip_first_screenshot=True):
        """
        Args:
            skip_first_screenshot:

        Pages:
            in: page_research, stable, with project finished.
            out: page_research

        Returns:
            bool: 成功领取奖励返回 True。
                  项目条件未满足返回 False。
        """
        logger.hr('Research receive', level=3)
        with self.stat.new(
                genre='research', method=self.config.DropRecord_ResearchRecord
        ) as record:
            # 截取项目列表
            record.add(self.device.image)

            # 点击已完成项目，进入 GET_ITEMS_*
            confirm_timer = Timer(1.5, count=5)
            record_button = None
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                if self.appear(RESEARCH_CHECK, offset=(20, 20), interval=10):
                    if self.research_has_finished():
                        self.device.click(RESEARCH_ENTRANCE[self._research_finished_index])

                if self.appear(RESEARCH_STOP, offset=(20, 20)):
                    logger.info('The research time is up, but requirements are not satisfied')
                    self.research_project_started = None
                    self.research_detail_quit()
                    return False
                # 误入其他项目
                if self.appear(RESEARCH_START, offset=(20, 20), interval=5):
                    self.device.click(RESEARCH_DETAIL_QUIT)
                    continue

                appear_button = self.get_items()
                if appear_button is not None:
                    if appear_button == record_button:
                        if confirm_timer.reached():
                            break
                    else:
                        logger.info(f'{appear_button} appeared')
                        record_button = appear_button
                        confirm_timer.reset()

            # 截取奖励物品
            self.drop_record(drop=record)

        # 关闭 GET_ITEMS_*，返回项目列表
        self.ui_click(appear_button=self.get_items, click_button=GET_ITEMS_RESEARCH_SAVE,
                      check_button=self.is_in_research, skip_first_screenshot=True)
        return True

    def queue_receive(self, skip_first_screenshot=True):
        """
        Args:
            skip_first_screenshot:

        Pages:
            in: is_in_queue
            out: is_in_queue

        Returns:
            int: 领取奖励的科研项目数量
        """
        logger.hr('Queue receive', level=1)
        total = 0
        with self.stat.new(
                genre='research', method=self.config.DropRecord_ResearchRecord
        ) as drop:
            # 截取项目列表
            drop.add(self.device.image)

            end_confirm = Timer(1, count=3)
            item_confirm = Timer(1.5, count=5)
            item_interval = Timer(0.2, count=0)
            record_button = None
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                # 结束条件
                # 不使用偏移量，仅使用颜色检测
                if self.is_in_queue() and not self.appear(QUEUE_CLAIM_REWARD, offset=None):
                    if end_confirm.reached():
                        break
                else:
                    end_confirm.reset()

                # 获取物品
                if drop:
                    # 记录物品掉落
                    appear_button = self.get_items()
                    if appear_button is not None:
                        if appear_button == record_button:
                            if item_confirm.reached():
                                # 记录掉落并关闭获取物品界面
                                self.drop_record(drop=drop)
                                self.device.click(GET_ITEMS_RESEARCH_SAVE)
                                item_confirm.reset()
                                record_button = None
                                total += 1
                                continue
                        else:
                            logger.info(f'{appear_button} appeared')
                            record_button = appear_button
                            item_confirm.reset()
                    else:
                        item_confirm.reset()
                        record_button = None
                else:
                    # 不保存掉落，直接点击
                    if item_interval.reached():
                        appear_button = self.get_items()
                        if appear_button is not None:
                            self.device.click(GET_ITEMS_RESEARCH_SAVE)
                            item_interval.reset()
                            total += 1
                            continue

                # 领取奖励
                if self.appear_then_click(QUEUE_CLAIM_REWARD, offset=None, interval=5):
                    continue

            if total <= 0:
                drop.clear()

        logger.info(f'Received rewards from {total} projects')
        return total

    def queue_quit(self, *args, **kwargs):
        super().queue_quit(*args, **kwargs)
        self._research_project_offset = 0

    def research_project_list_init(self, from_queue=False):
        """
        处理进入科研列表：重置偏移量并检测项目。

        Args:
            from_queue (bool): 是否从科研队列切换而来，
                此时已调用过 ensure_research_center_stable()
        """
        self._research_project_offset = 0
        # 处理信息栏，多截一张图以等待 info_bar 残留消退
        if self.handle_info_bar():
            self.device.screenshot()
        if not from_queue:
            self.ensure_research_center_stable()
        self.research_detect()

    def research_queue_append(self, drop=None, add_queue=True):
        """
        Args:
            drop (DropImage):
            add_queue (bool): 是否加入队列。
                第 6 个项目无法加入队列，因此需要此开关。

        Returns:
            bool: 是否成功启动项目
        """
        self.research_project_started = None
        project_record = None
        for _ in range(2):
            logger.hr('Research select', level=2)
            self.research_project_list_init(from_queue=True)
            project_record = self.device.image
            priority = self.research_sort_filter()
            result = self.research_select(priority, drop=drop, add_queue=add_queue)
            if result:
                break

        if self.research_project_started is not None:
            if project_record is not None:
                drop.add(project_record)
            return True
        else:
            return False

    def research_fill_queue(self):
        """
        持续选择科研项目直到队列填满。

        Returns:
            int: 加入队列的科研项目数量

        Pages:
            in: is_in_research
        """
        logger.hr('Research fill queue', level=1)
        total = 0
        with self.stat.new(
                genre='research', method=self.config.DropRecord_ResearchRecord
        ) as drop:
            for _ in range(5):
                if self.get_queue_slot() > 0:
                    success = self.research_queue_append(drop=drop)
                    if success:
                        total += 1
                    else:
                        logger.info(f'Unable to start a project, stop filling queue, queue added: {total}')
                        return total
                else:
                    break

            # 运行第 6 个项目
            status = self.get_research_status(self.device.image)
            if 'waiting' not in status:
                logger.info('Select the 6th research')
                self.research_queue_append(drop=drop, add_queue=False)
            else:
                logger.info('6th research already waiting')

            logger.info(f'Research queue full filled, queue added: {total}')
            return total

    def receive_6th_research(self, skip_first_screenshot=True):
        """
        Returns:
            bool: 是否成功
        """
        logger.hr('Receive 6th research', level=2)

        # 等待动画
        timeout = Timer(2, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('receive_6th_research wait timeout')
                break

            status = self.get_research_status(self.device.image)
            # 项目卡片尚未完全加载
            if 'unknown' in status:
                continue
            # 进入科研界面时，`waiting`（排队中）项目出现在第 2 位，然后移动到第 3 位
            # 从队列领取奖励后返回科研界面时，`waiting` 项目出现在第 4 位，然后移动到第 3 位
            # `waiting`（排队中）项目默认应在第 3 个位置
            if 'waiting' in status:
                if status.index('waiting') == 2:
                    break
                else:
                    continue
            # 没有第 6 个科研项目
            if sum([s == 'detail' for s in status]) == 5:
                break

        # 检查是否已完成
        if self.research_has_finished():
            logger.info(f'6th research finished at: {self._research_finished_index}')
            success = self.research_receive()
            if not success:
                return False
        else:
            logger.info('No research has finished')

        # 检查是否处于等待或运行状态
        status = self.get_research_status(self.device.image)
        if 'waiting' in status:
            if self.get_queue_slot() > 0:
                self.research_project_start(status.index('waiting'))
            else:
                logger.info('Queue full, stop appending waiting research')
        if 'running' in status:
            if self.get_queue_slot() > 0:
                self.research_project_start(status.index('running'))
            else:
                logger.info('Queue full, stop appending running research')

        return True

    def handle_pending_t_research(self):
        if self.config.Research_RemainingCommissions <= -1:
            return True
        if self.config.Research_RemainingCommissions > 0:
            return False

        slot = self.get_queue_slot()
        add_queue = slot > 0
        if not self.research_project_start(2, add_queue=add_queue):
            logger.warning('Failed to start pending T research')
            return False

        if add_queue:
            self.config.Research_RemainingCommissions = -1
            return True

        logger.info('T research is running outside the full queue')
        return False

    def run(self):
        """
        Pages:
            in: Any page
            out: page_research, with research project information, but it's still page_research.
                    or page_main
        """
        self.ui_ensure(page_research)

        # 检查队列
        self.queue_enter()
        self.queue_receive()
        self.end_time = self.get_research_ended()
        self.queue_quit()

        # 处理挂起的T类科研
        if self.handle_pending_t_research():
            # 检查第 6 个项目（在队列之外）
            self.receive_6th_research()
            # 填充队列
            self.research_fill_queue()

        slot = self.get_queue_slot()
        # 调度
        if slot == 5:
            # 队列为空，无法启动任何科研
            self.config.task_delay(server_update=True)
            return
        elif self.end_time <= current_time():
            # 获取新启动项目的剩余时间
            self.queue_enter()
            self.end_time = self.get_research_ended()
            self.queue_quit()
        if slot == 4:
            # 队列即将为空，因资源不足放弃科研，提前 10 分钟以避免科研闲置
            self.end_time = self.end_time + timedelta(minutes=-10)
        self.config.task_delay(target=self.end_time)

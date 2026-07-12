import re
from functools import partial

from module.base.decorator import Config
from module.base.filter import Filter
from module.base.timer import Timer
from module.config.config_generated import GeneratedConfig
from module.logger import logger
from module.research.assets import *
from module.research.preset import *
from module.research.project import research_detect, research_jp_detect
from module.research.ui import ResearchUI

RESEARCH_ENTRANCE = [ENTRANCE_1, ENTRANCE_2, ENTRANCE_3, ENTRANCE_4, ENTRANCE_5]
FILTER_REGEX = re.compile('(s[123456789])?'
                          '-?'
                          '(neptune|monarch|ibuki|izumo|roon|saintlouis'
                          '|seattle|georgia|kitakaze|azuma|friedrich'
                          '|gascogne|champagne|cheshire|drake|mainz|odin'
                          '|anchorage|hakuryu|agir|august|marcopolo'
                          '|plymouth|rupprecht|harbin|chkalov|brest'
                          '|kearsarge|hindenburg|shimanto|schultz|flandre'
                          '|napoli|nakhimov|halford|bayard|daisen'
                          '|goudenleeuw|mecklenburg|dmitri|kansas|vittorio'
                          '|valparaiso|maximmelmann|duncan|takahashi|orage)?'
                          '(dr|pry)?'
                          '([bcdeghqt])?'
                          '-?'
                          '(\d{3})?'
                          '(\d.\d|\d\d?)?')
FILTER_ATTR = ('series', 'ship', 'ship_rarity', 'genre', 'number', 'duration')
FILTER_PRESET = ('shortest', 'cheapest', 'reset')
FILTER = Filter(FILTER_REGEX, FILTER_ATTR, FILTER_PRESET)


class ResearchSelector(ResearchUI):
    # 当前科研项目列表
    projects: list
    # 来自 StorageHandler
    storage_has_boxes = True

    def research_cube_preserve_triggered(self):
        try:
            threshold = int(getattr(self.config, 'Research_CubePreserve', 0) or 0)
        except (TypeError, ValueError):
            threshold = 0
        try:
            current = int(getattr(self.config, 'Cube_Value', 0) or 0)
        except (TypeError, ValueError):
            current = 0
        triggered = threshold > 0 and current <= threshold
        logger.info(f'Research cube preserve: current={current}, threshold={threshold}, triggered={triggered}')
        return triggered

    def research_goto_detail(self, index, skip_first_screenshot=True):
        logger.info(f'Research goto detail (project {index})')
        click_timer = Timer(10)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # DETAIL_NEXT 在科研详情页未完全加载时也会出现
            if not self.appear(DETAIL_NEXT, offset=(20, 20)):
                if click_timer.reached():
                    self.device.click(RESEARCH_ENTRANCE[index])
                    click_timer.reset()
            else:
                # 检查 RESEARCH_COST_CHECKER 以确保科研详情页已完全加载
                self.wait_until_appear(RESEARCH_COST_CHECKER, offset=(20, 20), skip_first_screenshot=True)
                break

    def _research_jp_detect(self, skip_first_screenshot=True):
        """
        包装 research_jp_detect()，增加错误处理。

        Args:
            skip_first_screenshot:

        Returns:
            ResearchProjectJp
        """
        timeout = Timer(2, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.info_bar_count():
                logger.info('Handle info_bar')
                timeout.reset()
                continue

            project = research_jp_detect(self.device.image)
            if project.duration == '0':
                logger.warning(f'Invalid research duration: {project}')
                continue
            else:
                return project

    @Config.when(SERVER='jp')
    def research_detect(self):
        """
        实际上此处不需要截图。'image' 是一个空参数。
        添加此参数仅是为了确保所有 "research_detect" 具有相同的参数签名。
        """
        projects = []
        proj_sorted = []

        for _ in range(5):
            self.device.click_record_clear()
            """
            每次进入第 4 个（中右侧）入口时，
            所有科研项目会从右向左移动 1 个位置。
            """
            self.research_goto_detail(3)
            """
            'image' 是上述的空参数。
            我们需要的是当前屏幕 'self.device.image'。
            """
            project = self._research_jp_detect()
            logger.attr('Project', project)
            projects.append(project)
            self.research_detail_quit()
        """
        page_research 应与之前保持一致。
        由于我们首先进入了第 4 个入口，
        从左到右的索引为 (2, 3, 4, 0, 1)。
        """
        for pos in range(5):
            proj_sorted.append(projects[(pos + 2) % 5])

        self.projects = proj_sorted

    @Config.when(SERVER=None)
    def research_detect(self):
        timeout = Timer(5, count=5).start()
        while 1:
            projects = research_detect(self.device.image)

            if timeout.reached():
                logger.warning('Failed to OCR research name after 3 trial, assume correct')
                break

            if sum([p.valid for p in projects]) < 5:
                # 最左侧的科研系列被战令信息遮挡，参见 #1037
                logger.info('Invalid project detected')
                logger.info('Probably because of battle pass info or too fast screenshot')
                # 罕见情况，少量 sleep 可以接受
                self.device.sleep(1)
                self.device.screenshot()
                continue
            else:
                break

        self.projects = projects

    def research_sort_filter(self, enforce=False):
        """
        Returns:
            list: ResearchProject 对象和预设字符串的列表，
                如 [object, object, object, 'reset']
        """
        # 加载过滤器字符串
        preset = self.config.Research_PresetFilter
        cube_preserve = self.research_cube_preserve_triggered()
        if preset == 'custom':
            string = self.config.Research_CustomFilter
            if enforce:
                string = string + ' > ' + DICT_FILTER_PRESET[GeneratedConfig.Research_PresetFilter]
        else:
            if not cube_preserve \
                    and (self.config.Research_UseCube == 'always_use' or enforce) \
                    and f'{preset}_cube' in DICT_FILTER_PRESET:
                preset = f'{preset}_cube'
            if preset not in DICT_FILTER_PRESET:
                logger.warning(f'Preset not found: {preset}, use default preset')
                preset = GeneratedConfig.Research_PresetFilter
            string = DICT_FILTER_PRESET[preset]

        logger.attr('Research preset', preset)
        logger.info('Use cube: {} Use coin: {} Use part: {}'.format(
            self.config.Research_UseCube,
            self.config.Research_UseCoin,
            self.config.Research_UsePart))
        logger.attr('Allow delay', self.config.Research_AllowDelay)

        # 不区分大小写
        string = string.lower()
        # 过滤器使用 'hakuryu'，但同时允许 'hakuryu' 和 'hakuryuu'
        string = string.replace('hakuryuu', 'hakuryu')
        # 允许 'fastest' 和 'shortest' 两种写法
        string = string.replace('fastest', 'shortest')
        # 允许 'PR' 和 'PRY' 两种写法
        string = re.sub(r'pr([\d\- >])', r'pry\1', string)

        FILTER.load(string)
        priority = FILTER.apply(self.projects, func=partial(
            self._research_check, enforce=enforce, cube_preserve=cube_preserve))

        # 日志
        logger.attr('Filter_sort', ' > '.join([str(project) for project in priority]))
        return priority

    def _research_check(self, project, enforce=False, cube_preserve=False):
        """
        Args:
            project (ResearchProject):
            enforce (Bool):
        Returns:
            bool:
        """
        if not project.valid:
            return False

        # 检查项目消耗
        is_05 = str(project.duration) == '0.5'
        if project.need_cube:
            if cube_preserve:
                return False
            if self.config.Research_UseCube == 'do_not_use':
                return False
            if self.config.Research_UseCube == 'only_no_project' and not enforce:
                return False
            if self.config.Research_UseCube == 'only_05_hour' and not is_05 and not enforce:
                return False
        if project.need_coin:
            if self.config.Research_UseCoin == 'do_not_use':
                return False
            if self.config.Research_UseCoin == 'only_no_project' and not enforce:
                return False
            if self.config.Research_UseCoin == 'only_05_hour' and not is_05 and not enforce:
                return False
        if project.need_part:
            if self.config.Research_UsePart == 'do_not_use':
                return False
            if self.config.Research_UsePart == 'only_no_project' and not enforce:
                return False
            if self.config.Research_UsePart == 'only_05_hour' and not is_05 and not enforce:
                return False

        # 忽略 B 系列和 E-2 的原因：
        # - 无法保证科研条件被满足。
        #   可能运行一天后因未完成前置条件而一无所获。
        # - B 系列科研收益低。
        #   金色 B-4 基本等同于 C-12，但需要大量石油。

        if project.genre.upper() == 'B':
            return False
        # T 系列需要委托
        # 2022.05.08 允许 T 系列科研，因为委托现已强制启用
        # 2022.07.17 再次禁止 T 系列，除非满足前置条件否则无法加入队列
        if project.genre.upper() == 'T':
            return self.config.Research_AllowGenreT
        # 2021.08.19 允许 E-2 拆解科技箱，但 JP 服务器保持不变
        # 2022.08.23 允许所有 E-2，现已支持拆解装备
        #   如果仓库中没有可拆解的箱子则忽略 E-2，
        #   否则会陷入启动科研、尝试拆解、取消科研的循环
        if not self.storage_has_boxes:
            if self.config.SERVER == 'jp':
                if project.genre.upper() == 'E' and str(project.duration) != '6':
                    return False
            else:
                if project.genre.upper() == 'E' and project.task != '':
                    return False

        return True

    def research_sort_shortest(self, enforce):
        """
        Returns:
            list: ResearchProject 对象和预设字符串的列表，
                如 [object, object, object, 'reset']
        """
        cube_preserve = self.research_cube_preserve_triggered()
        FILTER.load(FILTER_STRING_SHORTEST)
        priority = FILTER.apply(self.projects, func=partial(
            self._research_check, enforce=enforce, cube_preserve=cube_preserve))

        logger.attr('Filter_sort', ' > '.join([str(project) for project in priority]))
        return priority

    def research_sort_cheapest(self, enforce):
        """
        Returns:
            list: ResearchProject 对象和预设字符串的列表，
                如 [object, object, object, 'reset']
        """
        cube_preserve = self.research_cube_preserve_triggered()
        FILTER.load(FILTER_STRING_CHEAPEST)
        priority = FILTER.apply(self.projects, func=partial(
            self._research_check, enforce=enforce, cube_preserve=cube_preserve))

        logger.attr('Filter_sort', ' > '.join([str(project) for project in priority]))
        return priority

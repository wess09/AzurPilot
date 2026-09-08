"""
科研项目筛选器。

本模块负责从截图中检测科研项目列表，并根据用户配置的筛选规则
对项目进行排序和过滤，输出符合优先级的候选项目列表。

支持两种服务器检测策略：
- JP 服务器：逐个点击项目进入详情页，通过模板匹配识别系列、
  类型、消耗和舰船信息（因 JP 服务器无 OCR 项目名称）
- 其他服务器：通过 OCR 识别项目名称 + 模板匹配识别系列编号

筛选规则基于正则表达式解析用户配置的过滤器字符串，
支持按系列(S1-S9)、舰船、稀有度(DR/PRY)、类型(B/C/D/E/G/H/Q/T)、
编号和时长进行多维度筛选，并支持 preset（预设）和 custom（自定义）两种模式。

术语对照：
    系列(Series): 科研系列编号 S1-S9
    类型(Genre): 科研项目类型 B/C/D/E/G/H/Q/T
    蓝图(Blueprint): 科研产出的舰船设计图
    DR: 决战方案(Dreamship Rarity)，金色稀有度科研舰船
    PRY: 近代方案(Priority Rarity)，紫色稀有度科研舰船
"""
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
    """
    科研项目筛选器，负责检测和筛选科研项目。

    从截图中识别 5 个科研项目的名称、系列和状态，然后根据用户
    配置的筛选规则（preset 或 custom）对项目进行优先级排序。

    JP 服务器使用逐个点击详情页的检测策略，其他服务器使用 OCR + 模板匹配。

    Attributes:
        projects (list[ResearchProject]): 当前屏幕上的 5 个科研项目列表。
        storage_has_boxes (bool): 仓库中是否有可拆解的科技箱/装备，
            影响 E 系列科研的筛选。由 StorageHandler 设置。
    """
    # 当前科研项目列表
    projects: list
    # 来自 StorageHandler
    storage_has_boxes = True

    def research_goto_detail(self, index, skip_first_screenshot=True):
        """
        点击进入指定索引的科研项目详情页。

        Args:
            index (int): 科研项目索引，0 到 4。
            skip_first_screenshot (bool): 是否跳过首次截图，复用上一状态的截图。
        """
        logger.info(f'[科研-详情] 进入科研详情 (项目 {index})')
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
                logger.info('[科研-检测] 处理信息栏')
                timeout.reset()
                continue

            project = research_jp_detect(self.device.image)
            if project.duration == '0':
                logger.warning(f'[科研-检测] 无效的科研时长: {project}')
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
            logger.attr('科研项目', project)
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
                logger.warning('[科研-检测] 尝试3次后仍无法OCR科研名称，假设正确')
                break

            if sum([p.valid for p in projects]) < 5:
                # 最左侧的科研系列被战令信息遮挡，参见 #1037
                logger.info('[科研-检测] 检测到无效项目')
                logger.info('[科研-检测] 可能是因为战令信息或截图过快')
                # 罕见情况，少量 sleep 可以接受
                self.device.sleep(1)
                self.device.screenshot()
                continue
            else:
                break

        self.projects = projects

    def research_sort_filter(self, enforce=False):
        """
        根据用户配置的筛选规则对科研项目进行优先级排序。

        加载预设或自定义过滤器字符串，解析后应用到当前项目列表，
        输出按优先级排序的候选项目列表。

        Args:
            enforce (bool): 是否为强制模式，强制模式下会追加默认
                预设作为兜底筛选条件。

        Returns:
            list: ResearchProject 对象和预设字符串的列表，
                如 [object, object, object, 'reset']
        """
        # 加载过滤器字符串
        preset = self.config.Research_PresetFilter
        if preset == 'custom':
            string = self.config.Research_CustomFilter
            if enforce:
                string = string + ' > ' + DICT_FILTER_PRESET[GeneratedConfig.Research_PresetFilter]
        else:
            if (self.config.Research_UseCube == 'always_use' or enforce) \
                    and f'{preset}_cube' in DICT_FILTER_PRESET:
                preset = f'{preset}_cube'
            if preset not in DICT_FILTER_PRESET:
                logger.warning(f'[科研-筛选] 预设未找到: {preset}，使用默认预设')
                preset = GeneratedConfig.Research_PresetFilter
            string = DICT_FILTER_PRESET[preset]

        logger.attr('科研预设', preset)
        logger.info('[科研-资源] 使用魔方: {} 使用金币: {} 使用部件: {}'.format(
            self.config.Research_UseCube,
            self.config.Research_UseCoin,
            self.config.Research_UsePart))
        logger.attr('允许延迟', self.config.Research_AllowDelay)

        # 不区分大小写
        string = string.lower()
        # 过滤器使用 'hakuryu'，但同时允许 'hakuryu' 和 'hakuryuu'
        string = string.replace('hakuryuu', 'hakuryu')
        # 归一化舰船名中的 latin 字符，便于过滤器匹配
        string = string.replace('ägir', 'agir')
        string = string.replace('valparaíso', 'valparaiso')
        # 允许 'fastest' 和 'shortest' 两种写法

        string = string.replace('fastest', 'shortest')
        # 允许 'PR' 和 'PRY' 两种写法
        string = re.sub(r'pr([\d\- >])', r'pry\1', string)

        FILTER.load(string)
        priority = FILTER.apply(self.projects, func=partial(self._research_check, enforce=enforce))

        # 日志
        logger.attr('过滤排序', ' > '.join([str(project) for project in priority]))
        return priority

    def _research_check(self, project, enforce=False):
        """
        检查单个科研项目是否符合用户的资源消耗和类型约束。

        根据用户配置检查魔方(coin)、金币(cube)、部件(part)的消耗限制，
        以及 B 系列、T 系列、E 系列的特殊过滤规则。

        Args:
            project (ResearchProject): 待检查的科研项目。
            enforce (bool): 是否为强制模式，强制模式下忽略部分资源限制。

        Returns:
            bool: 项目是否通过所有检查条件。
        """
        if not project.valid:
            return False

        # 检查项目消耗
        is_05 = str(project.duration) == '0.5'
        if project.need_cube:
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
        按最短时长优先排序科研项目。

        当筛选结果为空时，优先选择时长最短的项目以快速获取科研收益。

        Args:
            enforce (bool): 是否为强制模式。

        Returns:
            list: ResearchProject 对象和预设字符串的列表，
                如 [object, object, object, 'reset']
        """
        FILTER.load(FILTER_STRING_SHORTEST)
        priority = FILTER.apply(self.projects, func=partial(self._research_check, enforce=enforce))

        logger.attr('过滤排序', ' > '.join([str(project) for project in priority]))
        return priority

    def research_sort_cheapest(self, enforce):
        """
        按最低消耗优先排序科研项目。

        当筛选结果为空时，优先选择消耗最少资源的项目以节省资源。

        Args:
            enforce (bool): 是否为强制模式。

        Returns:
            list: ResearchProject 对象和预设字符串的列表，
                如 [object, object, object, 'reset']
        """
        FILTER.load(FILTER_STRING_CHEAPEST)
        priority = FILTER.apply(self.projects, func=partial(self._research_check, enforce=enforce))

        logger.attr('过滤排序', ' > '.join([str(project) for project in priority]))
        return priority

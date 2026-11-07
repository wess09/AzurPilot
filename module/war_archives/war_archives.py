"""作战档案模块。

自动执行碧蓝航线的作战档案战役。作战档案是过往活动的复刻入口，
需要消耗数据密钥（Data Key）才能进入，每日上限 60 把。

本模块的核心功能：
- 通过 OCR 识别剩余数据密钥数量，控制出击节奏
- 管理每日出击次数限制（可配置每日上限）
- 自动在数据密钥用尽或每日额度耗尽时停止任务
- 通关后实时扣减每日额度并持久化到配置
- 自动开荒（AutoClear）：识别关卡准备界面的三颗星暗亮状态并
  选择战斗策略——缺第三颗星开荒全清（一把推进达成度与三颗星），
  仅缺第二颗星自律刷护卫舰队；普通图三星模式覆盖普通图，所有
  关卡打满三星，完成后结束；全图三星模式覆盖普通图与困难图，
  所有关卡打满三星，普通图完成后推进困难图；100% 通关模式覆盖
  困难图，中间关全清一次（达成度 100%）即推进，最后一关在全清
  首通后自律刷满星
- 剧情关卡（如 cs1）按解锁链交错编入开荒序列（通关 c1 后需
  通关 cs1 才解锁 c2），剧情关通关一次即推进
- 开荒进度持久化（AutoClearProgress）：已满星的关卡记录到配置，
  下次运行直接从第一个未满星的关卡开始，不再从第一关重新扫描
- 关卡推进时复用档案关卡选择界面，不再每次经主页重新进入档案

注意：作战档案中禁用自动搜索续战功能，因为自动搜索菜单的模糊背景
会遮挡数据密钥的 OCR 识别区域。

配置路径: WarArchives.DailyRunCount (每日出击上限),
         WarArchives.AutoClear (自动开荒),
         WarArchives.AutoClearTarget (开荒目标),
         WarArchives.AutoSelectEvent (自动选择活动, 需开启自动开荒),
         WarArchives.AutoClearProgress (开荒进度持久化),
         StopCondition.OilLimit (燃油限制)
"""

import re

from campaign.campaign_war_archives.campaign_base import CampaignBase
from module.campaign.run import CampaignRun
from module.config.utils import get_server_last_update
from module.exception import CampaignNameError, RequestHumanTakeover, ScriptEnd
from module.handler.fast_forward import map_files, to_map_file_name
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.war_archives.assets import (OCR_DATA_KEY_CAMPAIGN,
                                        WAR_ARCHIVES_CAMPAIGN_CHECK)


class OcrDataKey(DigitCounter):
    """作战档案数据密钥计数器 OCR。

    处理数据密钥数量的 OCR 识别，修正常见的识别错误。
    数据密钥格式为 "当前/60"，OCR 可能将 "/60" 误识别为 "60"。
    """

    def after_process(self, result):
        """OCR 后处理，修正数据密钥数量识别错误。

        将 OCR 误识别的 "X60" 格式修正为 "X/60"。
        例如：识别结果 "1560" 会被修正为 "15/60"。

        Args:
            result (str): OCR 原始识别结果字符串。

        Returns:
            str: 修正后的数据密钥数量字符串。
        """
        result = super().after_process(result)
        result = re.sub(r'(\d{1,2})60$', r'\1/60', result)
        return result


DATA_KEY_CAMPAIGN = OcrDataKey(OCR_DATA_KEY_CAMPAIGN, letter=(255, 247, 247), threshold=64)


class CampaignWarArchives(CampaignRun, CampaignBase):
    """作战档案战役执行器。

    继承自 CampaignRun（战役运行）和 CampaignBase（作战档案战役基础），
    在标准战役运行逻辑上增加作战档案特有的限制：
    - 数据密钥消耗管理（强制启用 USE_DATA_KEY）
    - 每日出击次数限制（跨天自动重置、配置变更实时调整）
    - 数据密钥 OCR 检测（在档案战役界面识别剩余数量）
    - 禁用自动搜索续战（避免遮挡 OCR 区域）
    - 自动开荒：按三颗星暗亮选择自律刷星或全清拿星，满星自动递进
    """
    def daily_run_limit_reset(self):
        """刷新作战档案每日出击额度。

        DailyRunCount 是用户设置的每日上限；DailyRunCountRemain 是脚本保存的当日剩余额度。
        记录时间早于上次服务器刷新时，说明已经进入新的一天，需要恢复完整额度。
        """
        limit = self.config.WarArchives_DailyRunCount
        if limit <= 0:
            if self.config.WarArchives_DailyRunCountLimit != 0:
                with self.config.multi_set():
                    self.config.WarArchives_DailyRunCountRemain = 0
                    self.config.WarArchives_DailyRunCountLimit = 0
            return

        last_update = get_server_last_update(self.config.Scheduler_ServerUpdate)
        record = self.config.WarArchives_DailyRunCountRecord
        remain = self.config.WarArchives_DailyRunCountRemain
        old_limit = self.config.WarArchives_DailyRunCountLimit
        if record < last_update or remain > limit:
            logger.info(f'[作战档案] 重置每日出击次数: {remain} -> {limit}')
            with self.config.multi_set():
                self.config.WarArchives_DailyRunCountRemain = limit
                self.config.WarArchives_DailyRunCountRecord = last_update
                self.config.WarArchives_DailyRunCountLimit = limit
        elif old_limit != limit:
            remain = max(remain + limit - old_limit, 0)
            remain = min(remain, limit)
            logger.info(f'[作战档案] 更新每日出击次数: {old_limit} -> {limit}，剩余: {remain}')
            with self.config.multi_set():
                self.config.WarArchives_DailyRunCountRemain = remain
                self.config.WarArchives_DailyRunCountLimit = limit

    def daily_run_limit_triggered(self):
        """检查作战档案每日出击额度是否用尽。

        Returns:
            bool: 额度用尽时返回 True，否则返回 False。
        """
        limit = self.config.WarArchives_DailyRunCount
        if limit <= 0:
            return False

        remain = self.config.WarArchives_DailyRunCountRemain
        logger.info(f'[作战档案] 今日剩余出击次数: {remain} / {limit}')
        if remain > 0:
            return False

        logger.hr('触发停止条件：每日出击次数')
        self.config.task_delay(server_update=True)
        return True

    def daily_run_limit_consume(self):
        """通关后扣减并保存作战档案每日出击额度。"""
        limit = self.config.WarArchives_DailyRunCount
        if limit <= 0:
            return

        remain = max(self.config.WarArchives_DailyRunCountRemain - 1, 0)
        logger.info(f'[作战档案] 今日剩余出击次数: {remain} / {limit}')
        with self.config.multi_set():
            self.config.WarArchives_DailyRunCountRemain = remain
            self.config.WarArchives_DailyRunCountRecord = get_server_last_update(self.config.Scheduler_ServerUpdate)
            self.config.WarArchives_DailyRunCountLimit = limit

    def after_campaign_run(self):
        """作战档案单次通关后立即扣减每日出击额度。"""
        self.daily_run_limit_consume()

    def triggered_stop_condition(self, oil_check=True):
        """检查作战档案的停止条件。

        当处于档案战役界面时，通过 OCR 识别剩余数据密钥数量。
        数据密钥用尽时延迟任务到下次服务器重置。

        Pages:
            in: WAR_ARCHIVES_CAMPAIGN_CHECK（档案战役界面）

        Args:
            oil_check (bool): 是否检查燃油停止条件。

        Returns:
            bool: True 表示触发了停止条件，False 表示未触发。
        """
        if self.daily_run_limit_triggered():
            return True

        # 必须在档案战役界面才能进行 OCR 检查
        if self.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
            # 检查数据密钥是否已用尽
            current, remain, total = DATA_KEY_CAMPAIGN.ocr(self.device.image)
            logger.info(f'[作战档案] 档案秘钥: {current} / {total}, 剩余: {current}')
            if remain == total:
                logger.hr('[作战档案] 档案秘钥已用尽')
                # 仅在数据密钥用尽时才能延迟任务
                self.config.task_delay(server_update=True)
                return True

        # 其他情况，检查通用停止条件
        return super().triggered_stop_condition(oil_check)

    def can_use_auto_search_continue(self):
        """判断是否可使用自动搜索续战。

        自动搜索菜单具有模糊背景，会遮挡 DATA_KEY_CAMPAIGN 的 OCR 区域，
        因此作战档案中禁用自动搜索续战功能。

        Returns:
            bool: 始终返回 False，不支持自动搜索续战。
        """
        return False

    @staticmethod
    def _auto_clear_stage_sort_key(name):
        """开荒序列的排序键，剧情关排在同号战斗关之后。

        部分活动（如箱庭疗法）的关卡沿解锁链逐步开放：通关 c1 解锁
        剧情关 cs1，通关 cs1 后才解锁 c2，因此序列需按
        c1 > cs1 > c2 > cs2 > c3 交错剧情关。

        Args:
            name (str): 关卡文件名，如 'c1'、'cs1'、'ht2'。

        Returns:
            tuple[str, int]: (章节组, 组内权重)，剧情关权重为同号战斗关 +1。
        """
        chapter, story, index = re.fullmatch(r'([a-z]+?)(s?)(\d+)', name).groups()
        return chapter, int(index) * 2 + (1 if story else 0)

    def _get_auto_clear_stages(self, folder):
        """推导自动开荒的关卡序列。

        从活动地图文件夹的文件列表中，按开荒目标筛选主关卡并排序：
        - 普通图三星（normal_3_star）：普通图，a/b/t 编号，如
          a1 > as1 > a2 > a3 > b1
        - 全图三星（three_star）：普通图在前、困难图在后，覆盖全部
          主关卡，如 a1 > as1 > a2 > a3 > b1 > c1 > d1
        - 100% 通关（clear_100）：困难图，c/d/ht 编号，如
          c1 > cs1 > c2 > d1
        剧情关（as/bs/cs/ds 等）是后续战斗关的解锁前置，按上述
        顺序一并纳入；sp/ex 等其他特殊关卡不参与开荒序列。仅含
        普通图的活动在全图三星下只推普通图。

        Args:
            folder (str): 活动地图文件夹名称，如 'war_archives_20190321_en'。

        Returns:
            list[str]: 关卡序列，如 ['a1', 'as1', 'a2', 'a3']。

        Raises:
            RequestHumanTakeover: 若活动中未找到符合开荒目标的关卡时抛出。
        """
        files = map_files(folder)
        sort_key = self._auto_clear_stage_sort_key
        normal = sorted((f for f in files if re.fullmatch(r'(a|b|t)s?\d+', f)), key=sort_key)
        hard = sorted((f for f in files if re.fullmatch(r'(c|d|ht)s?\d+', f)), key=sort_key)
        target = self.config.WarArchives_AutoClearTarget
        if target == 'clear_100':
            target_text = '100% 通关（困难图）'
            stages = hard
        elif target == 'normal_3_star':
            target_text = '普通图三星'
            stages = normal
        else:
            target_text = '全图三星（普通图+困难图）'
            stages = normal + hard
        if not stages:
            logger.critical(f'[作战档案] 活动 {folder} 中未找到符合开荒目标（{target_text}）的关卡')
            raise RequestHumanTakeover
        logger.info(f'[作战档案] 开荒目标: {target_text}，关卡序列: {stages}')
        return stages

    def load_campaign(self, name, folder='campaign_main'):
        """加载战役地图，并在自动开荒推进关卡时继承界面导航状态。

        每关满星后由 war_archives.run() 推进到下一关，此时上一关
        已通过 enter_map_cancel() 回到本档案的关卡选择界面。若不为
        新关卡实例继承上一关的 first_run=False，ui_goto_archives_campaign()
        会强制经主页重新进入档案（主页 → 档案列表 → 滚动查找入口），
        造成每完成一关就回一趟主页。继承后，只要关卡选择界面可见
        就直接复用当前界面切换关卡；仅当不在该界面（如停在地图内、
        弹窗界面）时才走原有导航恢复。

        Args:
            name (str): 战役名称或地图文件 stem。
            folder (str): 战役文件夹路径。
        """
        prev_campaign = getattr(self, 'campaign', None)
        prev_name = getattr(self, 'name', None)
        super().load_campaign(name, folder=folder)
        if (self.config.WarArchives_AutoClear
                and prev_campaign is not None
                and name != prev_name
                and not prev_campaign.first_run):
            self.campaign.first_run = False

    def _get_auto_clear_progress(self, folder):
        """读取持久化的开荒进度。

        Args:
            folder (str): 活动地图文件夹名称，如 'war_archives_20190321_en'。

        Returns:
            list[str]: 当前活动、当前开荒目标下已确认完成开荒的关卡列表。
        """
        progress = self.config.WarArchives_AutoClearProgress
        if not isinstance(progress, dict):
            return []
        target = self.config.WarArchives_AutoClearTarget
        stages = progress.get(folder)
        if not isinstance(stages, dict):
            return []
        stages = stages.get(target, [])
        return list(stages) if isinstance(stages, list) else []

    def _record_auto_clear_progress(self, folder, stage):
        """记录单个达标关卡并持久化，用于下次运行直接跳过。

        达标标准随开荒目标变化：100% 通关模式为达成度 100%
        （中间关全清一次即达标，仅最后一关要求满星），普通图三星
        与全图三星模式为满星。进度按活动文件夹和开荒目标分组存储，
        各开荒目标的关卡序列互不相交，切换目标不会误跳过另一目标
        的关卡。

        Args:
            folder (str): 活动地图文件夹名称。
            stage (str): 已完成开荒的关卡，如 't1'。
        """
        progress = self.config.WarArchives_AutoClearProgress
        if not isinstance(progress, dict):
            progress = {}
        target = self.config.WarArchives_AutoClearTarget
        records = progress.get(folder)
        if not isinstance(records, dict):
            records = {}
        stages = records.get(target, [])
        stages = list(stages) if isinstance(stages, list) else []
        if stage in stages:
            return
        stages.append(stage)
        records[target] = stages
        progress[folder] = records
        logger.info(f'[作战档案] 记录开荒进度: {folder} {target} 已完成 {stages}')
        self.config.WarArchives_AutoClearProgress = progress

    def handle_stage_name(self, name, folder, mode='normal'):
        """处理自动开荒推导出的真实地图文件名。

        非自动开荒仍保留父类的用户输入兼容与章节名转换。
        自动开荒序列来自 map_files()，已经是真实 .py 文件 stem；
        若继续执行 A/B/C/D 到 T/HT 的反向转换，可能把 t1/ht1 等
        真实文件名转成不存在的 a1/c1 文件名。

        Args:
            name (str): 战役名称或地图文件 stem。
            folder (str): 战役文件夹。
            mode (str): 战役模式。

        Returns:
            tuple[str, str]: 自动开荒返回原始真实文件名；否则返回父类结果。
        """
        if self.config.WarArchives_AutoClear:
            return to_map_file_name(name), folder
        return super().handle_stage_name(name, folder, mode=mode)

    def _is_story_stage(self, stage):
        """判断是否为剧情关（如 as1、cs1、hts2）。

        剧情关没有三星成就，且为一次性关卡（MAP_IS_ONE_TIME_STAGE），
        通关一次即视为完成开荒。

        Args:
            stage (str): 关卡文件名，如 'c1'、'cs1'。

        Returns:
            bool: 是否为剧情关。
        """
        return re.fullmatch(r'[a-z]+s\d+', stage) is not None

    def _story_stage_passed(self, stage, stages, entrance):
        """判断入口不在界面上的剧情关是否已被通关。

        剧情关通关后入口会从界面移除，未解锁时同样不在界面上。
        解锁链是严格线性的（通关 c1 解锁 cs1，通关 cs1 解锁 c2），
        因此只要序列中位于其后的任一关卡已经出现在界面上，即可
        断定该剧情关早已通关。

        Args:
            stage (str): 剧情关文件名，如 'cs1'。
            stages (list[str]): 完整开荒序列。
            entrance (dict): 界面识别出的关卡入口字典。

        Returns:
            bool: 是否已被通关。
        """
        later = stages[stages.index(stage) + 1:]
        return any(name in entrance for name in later)

    def _run_auto_clear_stage(self, stage, folder, mode, total, farm_full_stars):
        """运行单个开荒关卡并判断是否达标。

        Args:
            stage (str): 关卡文件名，如 'c2'、'cs1'。
            folder (str): 活动地图文件夹名称。
            mode (str): 战役模式，'normal' 或 'hard'。
            total (int): 总运行次数限制，0 表示无限。
            farm_full_stars (bool): 是否需要打满三星；False 时全清一次即达标。

        Returns:
            bool: 是否达成开荒目标。未达标说明停止条件收尾（密钥、
            次数用尽等）或任务被切换。

        Raises:
            ScriptEnd: 关卡入口未找到（关卡尚未解锁）时原样抛出。
        """
        self.config.override(
            StopCondition_MapAchievement='map_3_stars' if farm_full_stars else '100_percent_clear'
        )
        logger.hr(f'自动开荒: {stage}', level=2)
        super().run(name=stage, folder=folder, mode=mode, total=total)
        # 达标后由 handle_map_stop 收尾并以 ScriptEnd 结束本轮；
        # 未达标说明停止条件收尾（密钥、次数用尽等）或任务被切换
        if farm_full_stars:
            return self.campaign.map_is_3_stars
        if self._is_story_stage(stage):
            # 剧情关通关后入口直接从界面移除，没有机会重读通关状态，
            # map_is_100_percent_clear 停留在进场前的 0%；一次性关卡
            # 打过一场即视为通关完成
            return self.run_count >= 1
        return self.campaign.map_is_100_percent_clear

    def _finish_auto_clear_stage(self, stage, folder, finished):
        """记录达标关卡并处理任务切换。

        Args:
            stage (str): 达标的关卡名称。
            folder (str): 活动地图文件夹名称。
            finished (set[str]): 已完成关卡集合。
        """
        self._record_auto_clear_progress(folder, stage)
        finished.add(stage)

        if self.config.task_switched():
            logger.info('[作战档案] 调度器已切换任务，停止自动开荒')
            self.campaign.ensure_auto_search_exit()
            self.config.task_stop()

        self.config.Campaign_Name = stage

    def run(self, name=None, folder='campaign_main', mode='normal', total=0):
        """执行作战档案战役。

        强制启用数据密钥使用，然后调用父类战役运行逻辑。
        作战档案必须使用数据密钥才能进入。

        自动开荒（WarArchives.AutoClear）开启时，忽略用户填写的
        关卡名，由脚本按开荒目标推导关卡序列：持久化进度中已完成
        的关卡直接跳过，从第一个未完成的关卡开始出击；每关达标后
        记录进度并推进到序列中的下一关，直到最后一个关卡完成结束。
        100% 通关模式下，中间关全清一次（达成度 100%）即达标推进，
        只有序列中最后一关需要打满星。剧情关（如 cs1）是后续战斗
        关的解锁前置，按解锁链交错纳入序列，通关一次即推进；个别
        关卡尚未解锁时延后补跑，不再中断任务。

        自动选择活动（WarArchives.AutoSelectEvent）开启时，忽略
        活动名称，由脚本在档案列表中从上到下依次选择活动开荒，
        当前活动全部完成后推进到下一个活动。

        Pages:
            in: page_archives（作战档案选择界面）
            out: page_main（主界面，任务完成后）

        Args:
            name (str | None): 战役名称，如 'war_archives_20190321_en'。
            folder (str): 战役文件夹路径，默认 'campaign_main'。
            mode (str): 战役模式，'normal' 或 'hard'。
            total (int): 总运行次数，0 表示无限。仅限制单关内的运行次数，
                   不限制跨关递进。
        """
        self.config.override(USE_DATA_KEY=True)
        if self.config.WarArchives_AutoClear:
            self.config.override(StopCondition_StageIncrease=True)
        self.daily_run_limit_reset()

        if not self.config.WarArchives_AutoClear:
            if self.config.WarArchives_AutoSelectEvent:
                logger.warning('[作战档案] 自动选择活动需要开启自动开荒，已忽略')
            super().run(name, folder, mode, total)
            return

        if self.config.WarArchives_AutoSelectEvent:
            # 自动选择活动：从档案列表顶部往下，依次开荒未完成的活动
            while 1:
                folder = self._select_next_auto_clear_event()
                if folder is None:
                    logger.hr('自动开荒结束', level=2)
                    logger.info('[作战档案] 所有活动均已完成开荒，关闭自动开荒任务')
                    self.config.cross_set(keys='WarArchives.Scheduler.Enable', value=False)
                    return
                logger.info(f'[作战档案] 自动选择活动: {folder}')
                if not self._auto_clear_one_event(folder, mode, total):
                    # 密钥用尽等停止条件收尾，本次运行结束
                    return

        if self._auto_clear_one_event(folder, mode, total):
            logger.info('[作战档案] 全部关卡均已完成开荒，关闭自动开荒任务')
            self.config.cross_set(keys='WarArchives.Scheduler.Enable', value=False)

    def _auto_clear_one_event(self, folder, mode='normal', total=0):
        """对单个活动执行自动开荒。

        Args:
            folder (str): 活动地图文件夹名称。
            mode (str): 战役模式，'normal' 或 'hard'。
            total (int): 总运行次数限制，0 表示无限。

        Returns:
            bool: 活动是否已全部完成开荒。False 说明被停止条件
            （密钥、次数用尽等）收尾或任务被切换。
        """
        stages = self._get_auto_clear_stages(folder)
        finished = set(self._get_auto_clear_progress(folder))
        # 已完成关卡持久化后直接跳过，不再进入准备界面重新扫描
        remaining = [stage for stage in stages if stage not in finished]
        logger.attr('[作战档案] 已完成关卡', sorted(finished))
        logger.attr('[作战档案] 待开荒关卡', remaining)
        target_is_100 = self.config.WarArchives_AutoClearTarget == 'clear_100'

        # 已在档案战役界面时，先按界面解锁进度排除已通关的剧情关：
        # 入口不在界面、而序列中位于其后的关卡可见，说明解锁链已
        # 越过该剧情关，无需再尝试出击
        if remaining and self.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
            self.device.screenshot()
            try:
                self._get_stage_name(self.device.image)
            except (IndexError, CampaignNameError):
                pass
            else:
                for stage in list(remaining):
                    if self._is_story_stage(stage) and stage not in self.stage_entrance \
                            and self._story_stage_passed(stage, stages, self.stage_entrance):
                        logger.info(f'[作战档案] 剧情关 {stage} 已通关（后续关卡已解锁），直接跳过')
                        self._record_auto_clear_progress(folder, stage)
                        finished.add(stage)
                        remaining.remove(stage)
                        logger.attr('[作战档案] 待开荒关卡', remaining)

        deferred = []
        for stage in remaining:
            # 100% 通关模式：中间关全清一次（达成度 100%）即推进，
            # 只有最后一关需要打满星；普通图三星与全图三星模式
            # 所有关卡都打满星；剧情关没有三星成就，通关一次即完成
            farm_full_stars = (not target_is_100 or stage == stages[-1]) \
                and not self._is_story_stage(stage)
            try:
                goal_reached = self._run_auto_clear_stage(
                    stage, folder, mode, total, farm_full_stars)
            except ScriptEnd as e:
                # 关卡入口未找到：可能是尚未解锁，也可能是剧情关已通关
                # 后入口从界面移除（此时其后的关卡可见，可据此补记录）
                if str(e) != 'Campaign name error':
                    raise
                entrance = self.campaign.stage_entrance
                if self._is_story_stage(stage) and self._story_stage_passed(stage, stages, entrance):
                    logger.info(f'[作战档案] 剧情关 {stage} 已通关（后续关卡已解锁），补记录')
                    self._finish_auto_clear_stage(stage, folder, finished)
                    continue
                logger.warning(f'[作战档案] 关卡 {stage} 尚未解锁，延后补跑')
                deferred.append(stage)
                continue
            if not goal_reached:
                break

            self._finish_auto_clear_stage(stage, folder, finished)

        # 补跑先前因未解锁而延后的关卡，仍失败则按原样结束本轮
        for stage in deferred:
            farm_full_stars = (not target_is_100 or stage == stages[-1]) \
                and not self._is_story_stage(stage)
            try:
                goal_reached = self._run_auto_clear_stage(
                    stage, folder, mode, total, farm_full_stars)
            except ScriptEnd as e:
                # 一次性剧情关通关后入口会从界面移除，补跑时找不到
                # 入口说明此前通关时未及记录，视为已通关收敛
                if str(e) == 'Campaign name error' and self._is_story_stage(stage):
                    logger.warning(f'[作战档案] 剧情关 {stage} 入口已从界面移除，视为已通关')
                    goal_reached = True
                else:
                    raise
            if not goal_reached:
                break

            self._finish_auto_clear_stage(stage, folder, finished)

        logger.hr('自动开荒结束', level=2)
        return not set(stages) - finished

    def _select_next_auto_clear_event(self):
        """自动选择活动：从档案列表顶部往下取第一个未完成开荒的活动。

        Returns:
            str | None: 活动文件夹名称；None 表示列表中没有未完成
            开荒的活动。
        """
        for folder in self._iterate_archives_events():
            if not self._event_auto_clear_finished(folder):
                return folder
            logger.info(f'[作战档案] 活动已完成开荒，跳过: {folder}')
        return None

    def _event_auto_clear_finished(self, folder):
        """判断活动的开荒是否已全部完成。

        Args:
            folder (str): 活动地图文件夹名称。

        Returns:
            bool: 是否全部完成。
        """
        try:
            stages = self._get_auto_clear_stages(folder)
        except RequestHumanTakeover:
            # 活动目录缺失或没有符合开荒目标的关卡，视为完成并跳过
            logger.warning(f'[作战档案] 活动无可开荒关卡，跳过: {folder}')
            return True
        finished = set(self._get_auto_clear_progress(folder))
        return not set(stages) - finished

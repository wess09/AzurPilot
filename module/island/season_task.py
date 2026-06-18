from yaml import safe_dump

import module.config.server as server
from module.base.button import ButtonGrid
from module.base.decorator import cached_property, del_cached_property, Config
from module.base.timer import Timer
from module.base.utils import area_offset
from module.island.assets import *
from module.island.data import DIC_ISLAND_SEASONAL_TASK
from module.island.ui import IslandUI, ISLAND_SEASON_TASK_SCROLL
from module.logger import logger
from module.map_detection.utils import Points
from module.ocr.ocr import DigitCounter, Ocr
from module.ui.page import page_island_season

if server.server == 'cn':
    lang = 'cnocr'
elif server.server == 'en':
    lang = 'azur_lane'
else:
    lang = server.server
TASK_NAME_OCR = Ocr([], lang=lang, letter=(64, 64, 64), name='TASK_NAME_OCR')
TASK_COUNTER_OCR = DigitCounter([], letter=(128, 128, 128), name='TASK_COUNTER_OCR')

class IslandSeasonTaskHandler(IslandUI):
    def _get_icons(self):
        """
        获取季节任务奖励图标的位置。

        Returns:
            np.array: 图标左上角坐标数组 [[x1, y1], [x2, y2]]
        """
        area = (43, 298, 875, 604)
        image = self.image_crop(area, copy=True)
        bars = TEMPLATE_ISLAND_SEASON_REWARD.match_multi(image, threshold=5)
        bars = Points([(0., b.area[1]) for b in bars]).group(threshold=5)
        logger.attr('bars_icon', len(bars))
        return bars

    def wait_until_icon_appear(self, skip_first_screenshot=False):
        """
        等待季节任务页面加载完成。

        进入季节任务页面后任务不会立即加载，
        需要等待奖励图标出现才表示页面加载完毕。
        """
        confirm_timer = Timer(1.5, count=3).start()
        for _ in self.loop(skip_first=skip_first_screenshot):
            icons = self._get_icons()
            if len(icons):
                if confirm_timer.reached():
                    return
                else:
                    pass
            else:
                confirm_timer.reset()

    @cached_property
    def task_grid(self):
        return self.task_icon_grid()

    def task_icon_grid(self):
        """
        根据奖励图标位置计算任务网格。

        Returns:
            ButtonGrid: 任务按钮网格
        """
        icons = self._get_icons()
        count = len(icons)
        if count == 0:
            logger.warning('Unable to find bar icon, assume task list is at top')
            origin_y = 178
            delta_y = 229
            row = 2
        elif count == 1:
            y_list = icons[:, 1]
            # -18 用于将图标位置调整到网格位置
            origin_y = y_list[0] - 18 + 178
            delta_y = 229
            row = 1
        elif count == 2:
            y_list = icons[:, 1]
            origin_y = min(y_list) - 18 + 178
            delta_y = abs(y_list[1] - y_list[0])
            row = 2
        else:
            logger.warning(f'Too many icons found ({count}), assume max rows')
            y_list = icons[:, 1]
            origin_y = min(y_list) - 18 + 178
            delta_y = abs(y_list[1] - y_list[0])
            row = 2
        task_grid = ButtonGrid(
            origin=(43, origin_y), delta=(394, delta_y),
            button_shape=(375, 210), grid_shape=(3, row),
            name='SEASONAL_TASK_GRID'
        )
        return task_grid

    @Config.when(SERVER='jp')
    def task_id_parse(self, string):
        string = string.replace('一', 'ー').replace('へ', 'ヘ')
        import jellyfish
        min_key = ''
        min_distance = 100
        for key, value in DIC_ISLAND_SEASONAL_TASK.items():
            distance = jellyfish.levenshtein_distance(value['name']['jp'], string)
            if distance < min_distance:
                min_distance = distance
                min_key = key
        if min_distance < 3:
            return min_key
        logger.warning(f'Unknown task name: {string}')
        return None

    @Config.when(SERVER=None)
    def task_id_parse(self, string):
        for key, value in DIC_ISLAND_SEASONAL_TASK.items():
            if string == value['name'][server.server]:
                return key
        logger.warning(f'Unknown task name: {string}')
        return None

    def predict(self, grid: ButtonGrid):
        """
        预测给定网格中的所有季节任务。

        Args:
            grid (ButtonGrid): 任务按钮网格
        """
        name_area = (30, 18, 250, 52)
        counter_area = (270, 20, 360, 50)
        name_list = [self.image_crop(area, copy=True) for area in grid.crop(name_area).buttons]
        name_list = TASK_NAME_OCR.ocr(name_list, direct_ocr=True)
        task_id_list = [self.task_id_parse(name) for name in name_list]
        counter_list = [self.image_crop(area, copy=True) for area in grid.crop(counter_area).buttons]
        counter_list = [
            TASK_COUNTER_OCR.ocr([image], direct_ocr=True)
            for image in counter_list
        ]
        for task_id, counter_result, button in zip(task_id_list, counter_list, grid.buttons):
            if task_id is None:
                continue
            target = DIC_ISLAND_SEASONAL_TASK[task_id]['target']
            if target:
                target_item = list(target.keys())[0]
                current, _, total = counter_result
                obtained = TEMPLATE_ISLAND_SEASON_TASK_OBTAINED.match(self.image_crop(button, copy=True))
                yield task_id, (target_item, current, total), obtained

    def scan_all(self):
        """
        扫描岛屿季节页面上的所有季节任务。

        Returns:
            dict: {task_id: (item_id, current, total)} 未完成任务字典
        """
        self.wait_until_icon_appear()
        logger.hr('Scanning seasonal tasks')
        ISLAND_SEASON_TASK_SCROLL.set_top(main=self)
        unfinished_tasks = {}
        while 1:
            for task_id, (target_item, current, total), obtained in self.predict(self.task_grid):
                if current < total:
                    unfinished_tasks[task_id] = (target_item, current, total)
                if obtained:
                    logger.info(f'Detect obtained task, early stop scanning')
                    return unfinished_tasks
            if ISLAND_SEASON_TASK_SCROLL.at_bottom(main=self):
                logger.info('Task list reach bottom, stop')
                break
            else:
                ISLAND_SEASON_TASK_SCROLL.next_page(main=self, page=0.5)
                del_cached_property(self, 'task_grid')
                continue
        return unfinished_tasks

    def run(self):
        """
        运行季节任务扫描流程。

        Pages:
            in: 任意页面
            out: page_island

        Returns:
            dict: {task_id: (item_id, current, total)} 任务进度字典
        """
        self.ui_ensure(page_island_season)
        self.island_season_bottom_navbar_ensure(left=3)
        result = self.scan_all()
        value = safe_dump(result)
        self.config.cross_set(keys="IslandInfo.IslandSeasonTask.TaskDict", value=value)
        self.config.task_delay(server_update=True)

from module.island.island import *
from module.island_mine_forest.assets import *
from module.ui.page import *
from module.handler.login import LoginHandler
from module.config.utils import *
from module.island.warehouse import *


class IslandMineForest(Island,LoginHandler):
    def __init__(self, *args, **kwargs):
        Island.__init__(self, *args, **kwargs)

    PRODUCT_CONFIGS = {
        "Copper": (SELECT_COPPER, SELECT_COPPER_CHECK, POST_COPPER),
        "Aluminium": (SELECT_ALUMINIUM, SELECT_ALUMINIUM_CHECK, POST_ALUMINIUM),
        "Iron": (SELECT_IRON, SELECT_IRON_CHECK, POST_IRON),
        "Sulphur": (SELECT_SULPHUR, SELECT_SULPHUR_CHECK, POST_SULPHUR),
        "Silver": (SELECT_SILVER, SELECT_SILVER_CHECK, POST_SILVER),
        "Elegant": (SELECT_ELEGANT, SELECT_ELEGANT_CHECK, POST_ELEGANT),
        "Practical": (SELECT_PRACTICAL, SELECT_PRACTICAL_CHECK, POST_PRACTICAL),
        "Selected": (SELECT_SELECTED, SELECT_SELECTED_CHECK, POST_SELECTED),
        "Natural": (SELECT_NATURAL, SELECT_NATURAL_CHECK, POST_NATURAL),
    }

    def run_single_post(self, post_id, product_name, time_var_name):
        """运行单个岗位，包含完整的处理逻辑"""
        self.post_close()
        self.post_open(post_id)
        self.device.sleep(0.5)
        self.device.screenshot()
        selection, selection_check, post_check = self.PRODUCT_CONFIGS.get(product_name, (None, None, None))
        if self.appear(ISLAND_WORKING) and not self.appear(post_check):
            time_work = Duration(ISLAND_WORKING_TIME)
            time_value = time_work.ocr(self.device.image)
            setattr(self, time_var_name, datetime.now() + time_value)
        else:
            self.post_get_and_add(selection, selection_check)
            self.post_open(post_id)
            self.device.sleep(0.5)
            self.device.screenshot()
            time_work = Duration(ISLAND_WORKING_TIME)
            time_value = time_work.ocr(self.device.image)
            setattr(self, time_var_name, datetime.now() + time_value)
        self.post_close()

    def run(self):
        """运行所有岗位"""
        self.island_error = False
        # 初始化时间变量
        time_vars = ['time_Mining1', 'time_Mining2', 'time_Mining3', 'time_Mining4',
                     'time_Felling1', 'time_Felling2', 'time_Felling3', 'time_Felling4']
        for var in time_vars:
            setattr(self, var, None)

        # 配置所有岗位
        all_configs = [
            (ISLAND_MINE_POST1, self.config.IslandMine_Mining1, 'time_Mining1'),
            (ISLAND_MINE_POST2, self.config.IslandMine_Mining2, 'time_Mining2'),
            (ISLAND_MINE_POST3, self.config.IslandMine_Mining3, 'time_Mining3'),
            (ISLAND_MINE_POST4, self.config.IslandMine_Mining4, 'time_Mining4'),
            (ISLAND_FOREST_POST1, self.config.IslandForest_Felling1, 'time_Felling1'),
            (ISLAND_FOREST_POST2, self.config.IslandForest_Felling2, 'time_Felling2'),
            (ISLAND_FOREST_POST3, self.config.IslandForest_Felling3, 'time_Felling3'),
            (ISLAND_FOREST_POST4, self.config.IslandForest_Felling4, 'time_Felling4')
        ]

        # 通用设置
        self.goto_postmanage()
        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_close()
        self.post_manage_down_swipe(450)
        self.post_manage_down_swipe(450)

        # 运行所有岗位
        for post_id, product_config, time_var_name in all_configs:
            if product_config is not None:
                self.run_single_post(post_id, product_config, time_var_name)

        # 收集并处理完成时间
        self._process_finish_times(time_vars)
        if self.island_error:
            from module.exception import GameBugError
            raise GameBugError("检测到岛屿ERROR1，需要重启")

    def _process_finish_times(self, time_vars):
        """处理完成时间"""
        finish_times = [getattr(self, var) for var in time_vars if getattr(self, var) is not None]
        six_hours_later = datetime.now() + timedelta(hours=6)
        finish_times.append(six_hours_later)
        finish_times.sort()
        self.config.task_delay(target=finish_times)
        logger.info(f'Found {len(finish_times)} post timers, next run at {finish_times[0]}')

    def test(self):
        self.post_get_and_add(SELECT_SILVER, SELECT_SILVER_CHECK)
if __name__ == "__main__":
    az =IslandMineForest('alas', task='Alas')
    az.device.screenshot()
    az.test()

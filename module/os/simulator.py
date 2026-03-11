import logging
import os
import threading
import time
from datetime import datetime

import numpy as np

from module.config.config import AzurLaneConfig
from module.log_res.log_res import LogRes
from module.statistics.cl1_database import db
from module.statistics.ship_exp_stats import get_ship_exp_stats

class OSSimulator:
    def __init__(self, config: AzurLaneConfig):
        self.config = config
        self._init_logger()
        self._thread = None
        self._stop_event = threading.Event()

    def _init_logger(self):
        self.logger_path = f'./log/oss/{datetime.now().strftime("%Y-%m-%d")}.log'
        self.logger = logging.getLogger('OSSimulator')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        if not self.logger.handlers:
            os.makedirs('./log/oss', exist_ok=True)
            fh = logging.FileHandler(self.logger_path, encoding='utf-8')
            fh.setFormatter(logging.Formatter(
                fmt='%(asctime)s.%(msecs)03d | %(levelname)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ))
            self.logger.addHandler(fh)
    
    AP = 0
    COIN = 1
    STATUS = 2
    USED_TIME = 3
    HAS_CRASHED = 4
    HAS_EARNED_COIN = 5
    MEOW_COUNT = 6
    CL1_COUNT = 7
    PASSED_DAYS = 8
    
    STATUS_CL1 = 0
    STATUS_MEOW = 1
    STATUS_CRASHED = 2
    STATUS_DONE = 3
    
    AKASHI = np.array([20, 40, 50, 100, 100, 200] + [0] * 22)
    
    AP_RECOVER = 1 / 600
    AP_COSTS = {
        1: 5,
        2: 10,
        3: 15,
        4: 20,
        5: 30,
        6: 40
    }
    
    def _get_azurstat_data(self):
        # 预计之后使用azurstat统计数据，目前先这样吧（
        
        # 目前包括吊机
        self.coin_expectation = {
            1: 145,
            5: 1700
        }
        self.logger.info(f'每轮对应侵蚀等级期望获得黄币: {self.coin_expectation}')
        
        self.akashi_probability = 0.05
        self.logger.info(f'遇见明石概率: {self.akashi_probability}')

        self.daily_reward = 6520
        self.logger.info(f'每日任务获得黄币: {self.daily_reward}')
    
    def get_paras(self):
        self.samples = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Samples')
        self.logger.info(f'样本数: {self.samples}')
        self.meow_hazard_level = 5
        self.logger.info(f'短猫侵蚀等级（目前只支持侵蚀5）: {self.meow_hazard_level}')
        
        log_res = LogRes(self.config)
        ap = log_res.group('ActionPoint')
        ap = ap['Total'] if ap and 'Total' in ap else 0
        coin = log_res.group('YellowCoin')
        coin = coin['Value'] if coin and 'Value' in coin else 0

        self.initial_state = np.array([
            np.ones(self.samples) * ap,    # ap
            np.ones(self.samples) * coin, # coin
            np.zeros(self.samples), # status (cl1: 0, meow: 1, crashed: 2, done: 3)
            np.zeros(self.samples), # used_time
            np.zeros(self.samples), # has_crashed
            np.zeros(self.samples), # has_earned_coin
            np.zeros(self.samples), # meow_count
            np.zeros(self.samples), # cl1_count
            np.zeros(self.samples), # passed_days
        ])
        self.logger.info(f'初始黄币: {coin}')
        self.logger.info(f'初始行动力: {ap}')
        
        self.coin_preserve = self.config.cross_get('OpsiScheduling.OpsiScheduling.OperationCoinsPreserve')
        self.logger.info(f'保留黄币: {self.coin_preserve}')
        self.ap_preserve = self.config.cross_get('OpsiScheduling.OpsiScheduling.ActionPointPreserve')
        self.logger.info(f'保留行动力: {self.ap_preserve}')
        self.coin_threshold = self.config.cross_get('OpsiScheduling.OpsiScheduling.OperationCoinsReturnThreshold')
        self.logger.info(f'短猫直到获得多少黄币: {self.coin_threshold}')
        
        self.instance_name = getattr(self.config, 'config_name', 'default')
        self.logger.info(f'实例名: {self.instance_name}')
        
        self.meow_time = db.get_meow_stats(self.instance_name).get('avg_round_time', 200)
        self.logger.info(f'每轮短猫时间: {self.meow_time}')
        self.cl1_time = get_ship_exp_stats(self.instance_name).get_average_round_time()
        self.logger.info(f'每轮侵蚀1时间: {self.cl1_time}')

        self.days_until_next_monday = self._get_days_until_next_monday()
        self.logger.info(f'距离下周一还有多少天: {self.days_until_next_monday}')
        
        self._get_azurstat_data()
    
    @property
    def is_running(self):
        return bool(self._thread and self._thread.is_alive())
    
    def _run(self):
        try:
            self.get_paras()

            if self.meow_hazard_level not in self.coin_expectation:
                raise ValueError(f'不支持的短猫侵蚀等级: {self.meow_hazard_level}')

            self.logger.info("开始模拟...")
            start_time = time.time()
            result = self.simulate()
            self.logger.info(f"模拟完成，用时: {time.time() - start_time:.2f}秒")
            self._handle_result(result)
        except Exception as e:
            self.logger.exception(f"运行中出现错误: {e}")
    
    def start(self):
        if self.is_running:
            self.logger.warning("模拟正在进行，请耐心等待")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run)
        self._thread.start()
    
    def interrupt(self):
        if self.is_running:
            self.logger.info("等待模拟中断")
            self._stop_event.set()
        else:
            self.logger.info("无正在进行的模拟")

    def _get_remaining_seconds(self):
        now = datetime.now()
        if now.month == 12:
            next_month = datetime(now.year + 1, 1, 1)
        else:
            next_month = datetime(now.year, now.month + 1, 1)
        return (next_month - now).total_seconds()

    def _get_days_until_next_monday(self):
        now = datetime.now()
        current_weekday = now.weekday()
        days_ahead = 7 - current_weekday
        return days_ahead
    
    def _handle_akashi(self, state, base_mask):
        # Create a random mask for Akashi encounters, which is a subset of the base_mask
        rand_array = np.random.rand(state.shape[1])
        akashi_mask = (rand_array < self.akashi_probability) & base_mask
        n = np.sum(akashi_mask)
        
        if n == 0:
            return
        
        # 不放回采样28个里选6个 （我们numpy真是太厉害了）
        rand_mat = np.random.rand(28, n)
        indices = np.argpartition(rand_mat, 6, axis=0)[:6, :]
        sampled_values = self.AKASHI[indices]
        result = sampled_values.sum(axis=0)
        
        # 这里默认不会有人买不起行动力（不会吧？
        state[self.AP][akashi_mask] += result
        state[self.COIN][akashi_mask] -= result * 40
        
    def _cl1_simulate(self, state, mask):
        state[self.CL1_COUNT][mask] += 1
        
        state[self.AP][mask] -= self.AP_COSTS[1]
        state[self.COIN][mask] += self.coin_expectation[1]
        
        state[self.AP][mask] += self.AP_RECOVER * self.cl1_time
        state[self.USED_TIME][mask] += self.cl1_time
        
        self._handle_akashi(state, mask)
    
    def _meow_simulate(self, state, mask):
        state[self.MEOW_COUNT][mask] += 1
        
        state[self.AP][mask] -= self.AP_COSTS[self.meow_hazard_level]
        state[self.COIN][mask] += self.coin_expectation[self.meow_hazard_level]
        state[self.HAS_EARNED_COIN][mask] += self.coin_expectation[self.meow_hazard_level]
        
        state[self.AP][mask] += self.AP_RECOVER * self.meow_time
        state[self.USED_TIME][mask] += self.meow_time
        
        self._handle_akashi(state, mask)
    
    def _crashed_simulate(self, state, mask):
        state[self.HAS_CRASHED][mask] = 1
        skip_time = 43200   # 12 * 60 * 60
        
        state[self.USED_TIME][mask] += skip_time
        state[self.AP][mask] += 72
    
    def simulate(self):
        if not hasattr(self, 'initial_state'):
            self.get_paras()
        
        total_time = self._get_remaining_seconds()
        now_state = np.copy(self.initial_state)
        
        while np.any(now_state[self.STATUS] != self.STATUS_DONE):
            if self._stop_event.is_set():
                self.logger.info("模拟中断")
                break

            # 1. 计算状态转移
            is_cl1 = now_state[self.STATUS] == self.STATUS_CL1
            is_meow = now_state[self.STATUS] == self.STATUS_MEOW
            
            # 从侵蚀1切换到短猫
            to_meow_mask = is_cl1 & (now_state[self.COIN] < self.coin_preserve)
            # 从短猫切换到侵蚀1
            to_cl1_mask = is_meow & (now_state[self.HAS_EARNED_COIN] >= self.coin_threshold)
            # 坠机拥有最高优先级
            to_crashed_mask = (now_state[self.COIN] < self.coin_preserve) & (now_state[self.AP] < self.ap_preserve)
            
            # 2. 应用状态转移
            now_state[self.STATUS][to_meow_mask] = self.STATUS_MEOW
            now_state[self.HAS_EARNED_COIN][to_meow_mask] = 0
            now_state[self.STATUS][to_cl1_mask] = self.STATUS_CL1
            now_state[self.STATUS][to_crashed_mask] = self.STATUS_CRASHED
            
            # 3. 执行模拟步进
            for status_val, sim_func in zip([self.STATUS_CL1, self.STATUS_MEOW, self.STATUS_CRASHED], [self._cl1_simulate, self._meow_simulate, self._crashed_simulate]):
                mask = now_state[self.STATUS] == status_val
                if np.any(mask):
                    sim_func(now_state, mask)

            # 4. 更新跨日
            sim_days = now_state[self.USED_TIME] // 86400
            cross_day_mask = sim_days > now_state[self.PASSED_DAYS]
            if np.any(cross_day_mask):
                now_state[self.PASSED_DAYS][cross_day_mask] += 1
                now_state[self.COIN][cross_day_mask] += self.daily_reward

                cross_week_mask = (sim_days - self.days_until_next_monday) % 7 == 0
                if np.any(cross_week_mask & cross_day_mask):
                    now_state[self.AP][cross_day_mask & cross_week_mask] += 1000
            
            # 5. 标记完成状态
            now_state[self.STATUS][now_state[self.USED_TIME] >= total_time] = self.STATUS_DONE
            
        return now_state
    
    def _handle_result(self, result):
        self.result_cl1_count = np.average(result[self.CL1_COUNT])
        self.logger.info(f'[模拟结果] 侵蚀1次数: {self.result_cl1_count}')
        self.result_meow_count = np.average(result[self.MEOW_COUNT])
        self.logger.info(f'[模拟结果] 短猫次数: {self.result_meow_count}')
        self.result_crashed_probability = np.average(result[self.HAS_CRASHED])
        self.logger.info(f'[模拟结果] 坠机概率: {self.result_crashed_probability}')
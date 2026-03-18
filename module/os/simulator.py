import logging
import os
import threading
import time
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from module.config.config import AzurLaneConfig
from module.log_res.log_res import LogRes
from module.statistics.cl1_database import db
from module.statistics.ship_exp_stats import get_ship_exp_stats

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun', 'Arial'] 
plt.rcParams['axes.unicode_minus'] = False

class OSSimulator:
    def __init__(self):
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
    
    AKASHI = np.array([20, 40, 50, 100, 100, 200] + [0] * 18)
    '''
    明石可能卖的24种物品 (纯臆测)
    6种行动力箱子:
    能源补给箱（小）*1
    能源补给箱（小）*2
    能源补给箱（中）*1
    能源补给箱（中）*2
    能源补给箱（大）*1
    能源补给箱（大）*2
    18种垃圾:
    特别兑换凭证*5
    特别兑换凭证*5
    特别兑换凭证*10
    特别兑换凭证*10
    应急维修箱*1
    应急维修箱*5
    豪华维修箱*1
    豪华维修箱*5
    应急维修箱（组件）*1
    应急维修箱（组件）*3
    豪华应急维修箱（组件）*1
    豪华应急维修箱（组件）*3
    效能样本-攻击*1
    效能样本-攻击*1
    效能样本-耐久*1
    效能样本-耐久*1
    效能样本-恢复*1
    效能样本-恢复*1
    '''
    
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
        cl1_coin = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Cl1Coin')
        meow3_coin = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Meow3Coin')
        meow5_coin = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Meow5Coin')
        self.coin_expectation = {
            1: cl1_coin,
            3: meow3_coin,
            5: meow5_coin
        }
        self.logger.info(f'每轮对应侵蚀等级期望获得黄币: {self.coin_expectation}')
        
        self.akashi_probability = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.AkashiProbability')
        self.logger.info(f'遇见明石概率: {self.akashi_probability}')

        self.daily_reward = 6520
        self.logger.info(f'每日任务获得黄币: {self.daily_reward}')
        
        self.stronghold_reward = 40000
        self.logger.info(f'每周要塞期望获得黄币: {self.stronghold_reward}')
    
    def get_paras(self):
        self.config.load()
        
        self.samples = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Samples')
        self.logger.info(f'样本数: {self.samples}')

        self.draw_setting = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Draw')
        self.logger.info(f'绘图设置: {self.draw_setting}')
        
        self.total_time = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.TotalTime')
        if not self.total_time:
            self.total_time = self._get_remaining_seconds()
        self.logger.info(f'总模拟时间 (s): {self.total_time}')
        
        self.time_use_ratio = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.TimeUseRatio')
        self.logger.info(f'时间利用率: {self.time_use_ratio}')
        
        hazard_level = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.MeowHazardLevel', 'level5')
        if hazard_level == 'level3':
            self.meow_hazard_level = 3
        else:
            self.meow_hazard_level = 5
        self.logger.info(f'短猫侵蚀等级: {self.meow_hazard_level}')
        
        log_res = LogRes(self.config)
        ap = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.InitialAp')
        if not ap:
            ap = log_res.group('ActionPoint')
            ap = ap['Total'] if ap and 'Total' in ap else 0
        coin = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.InitialCoin')
        if not coin:
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
            np.zeros(self.samples) # passed_days
        ])
        self.logger.info(f'初始黄币: {coin}')
        self.logger.info(f'初始行动力: {ap}')

        self.cross_week = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.CrossWeek')
        self.logger.info(f'是否计算跨周: {self.cross_week}')

        self.buy_ap = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.BuyAp')
        self.logger.info(f'每周是否购买行动力: {self.buy_ap}')
        
        self.coin_preserve = self.config.cross_get('OpsiScheduling.OpsiScheduling.OperationCoinsPreserve')
        self.logger.info(f'保留黄币: {self.coin_preserve}')
        self.ap_preserve = self.config.cross_get('OpsiScheduling.OpsiScheduling.ActionPointPreserve')
        self.logger.info(f'保留行动力: {self.ap_preserve}')
        self.coin_threshold = self.config.cross_get('OpsiScheduling.OpsiScheduling.OperationCoinsReturnThreshold')
        self.logger.info(f'短猫直到获得多少黄币: {self.coin_threshold}')
        
        self.instance_name = getattr(self.config, 'config_name', 'default')
        self.logger.info(f'实例名: {self.instance_name}')
        
        if self.meow_hazard_level == 3:
            self.meow_time = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Meow3Time')
            if not self.meow_time:
                # 尝试从数据库获取短猫统计，如果不区分等级则统一使用平均值
                self.meow_time = db.get_meow_stats(self.instance_name).get('avg_round_time', 100)
        else: # hazard level 5
            self.meow_time = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Meow5Time')
            if not self.meow_time:
                self.meow_time = db.get_meow_stats(self.instance_name).get('avg_round_time', 200)
        
        self.logger.info(f'每轮短猫时间: {self.meow_time}')

        self.cl1_time = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Cl1Time')
        if not self.cl1_time:
            self.cl1_time = get_ship_exp_stats(self.instance_name).get_average_round_time()
        self.logger.info(f'每轮侵蚀1时间: {self.cl1_time}')
        
        self.days_until_next_monday = self._get_days_until_next_monday()
        self.logger.info(f'距离下周一还有多少天: {self.days_until_next_monday}')

        # 调试模式开关：设置为 True 则取消随机性，按照期望值计算演化
        self.deterministic = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Deterministic', False)
        if self.deterministic:
            self.samples = 1
            self.logger.info('调试模式：使用确定性计算。采样数已强制设置为 1 以提高计算速度。')
            self.logger.info('（不使用随机概率，按期望演化）')

        # 修正后的单轮时间：包含了因“时间利用率”不足而产生的空闲时间，用于正确计算AP的自然恢复
        self.modified_meow_time = self.meow_time / self.time_use_ratio
        self.modified_cl1_time = self.cl1_time / self.time_use_ratio

        self._get_azurstat_data()
    
    @property
    def is_running(self):
        return bool(self._thread and self._thread.is_alive())
    
    @property
    def figure(self):
        return getattr(self, 'result_figure_path', '')
    
    def _run(self):
        try:
            if not self.config:
                raise ValueError('缺少配置')
            
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
    
    def set_config(self, config: AzurLaneConfig):
        self.config = config

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
        if np.sum(base_mask) == 0:
            return

        if self.deterministic:
            # 确定性模式：直接加上期望值
            # 期望 = 遇见的概率 * 购买的项数 * 奖池平均奖励
            reward_avg = np.mean(self.AKASHI)
            total_reward_expect = self.akashi_probability * 6 * reward_avg
            
            state[self.AP][base_mask] += total_reward_expect
            state[self.COIN][base_mask] -= total_reward_expect * 40
            return

        # Create a random mask for Akashi encounters, which is a subset of the base_mask
        rand_array = np.random.rand(self.samples)
        akashi_mask = (rand_array < self.akashi_probability) & base_mask
        n_akashi = np.sum(akashi_mask)
        
        if n_akashi == 0:
            return
        
        # 不放回采样24个里选6个 （我们numpy真是太厉害了）
        rand_mat = np.random.rand(len(self.AKASHI), n_akashi)
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
        
        state[self.AP][mask] += self.AP_RECOVER * self.modified_cl1_time
        state[self.USED_TIME][mask] += self.modified_cl1_time
        
        self._handle_akashi(state, mask)
    
    def _meow_simulate(self, state, mask):
        state[self.MEOW_COUNT][mask] += 1
        
        state[self.AP][mask] -= self.AP_COSTS[self.meow_hazard_level]
        state[self.COIN][mask] += self.coin_expectation[self.meow_hazard_level]
        state[self.HAS_EARNED_COIN][mask] += self.coin_expectation[self.meow_hazard_level]
        
        state[self.AP][mask] += self.AP_RECOVER * self.modified_meow_time
        state[self.USED_TIME][mask] += self.modified_meow_time
        
        self._handle_akashi(state, mask)
    
    def _crashed_simulate(self, state, mask):
        state[self.HAS_CRASHED][mask] = 1
        skip_time = 43200   # 12 * 60 * 60
        
        state[self.USED_TIME][mask] += skip_time
        state[self.AP][mask] += 72
    
    def simulate(self):
        if not hasattr(self, 'initial_state'):
            self.get_paras()
            
        now_state = np.copy(self.initial_state)

        if self.draw_setting == 'single_sample':
            self.history_single = {
                'time': [now_state[self.USED_TIME][0]],
                'ap': [now_state[self.AP][0]],
                'coin': [now_state[self.COIN][0]],
                'status': [now_state[self.STATUS][0]]
            }
            last_time_0 = now_state[self.USED_TIME][0]
        elif self.draw_setting == 'multi_sample':
            self.history_mean = {
                'time': [np.average(now_state[self.USED_TIME])],
                'ap': [np.average(now_state[self.AP])],
                'coin': [np.average(now_state[self.COIN])],
                'meow_prob': [np.average(now_state[self.STATUS] == self.STATUS_MEOW)],
                'has_crashed_prob': [np.average(now_state[self.HAS_CRASHED])]
            }
        
        while np.any(now_state[self.STATUS] != self.STATUS_DONE):
            if self._stop_event.is_set():
                self.logger.info("模拟中断")
                raise KeyboardInterrupt

            # 1. 计算状态转移
            is_cl1 = now_state[self.STATUS] == self.STATUS_CL1
            is_meow = now_state[self.STATUS] == self.STATUS_MEOW
            is_crashed = now_state[self.STATUS] == self.STATUS_CRASHED
            
            # 从侵蚀1切换到短猫
            # 触发条件：当前处于侵蚀1，且黄币跌破保留值
            to_meow_mask = is_cl1 & (now_state[self.COIN] < self.coin_preserve)
            
            # 从短猫切换到侵蚀1
            # 触发条件：当前处于短猫，且黄币由于短猫补充后，已经超过了 (保留值 + 单次目标值)
            to_cl1_mask = is_meow & (now_state[self.COIN] >= (self.coin_preserve + self.coin_threshold))
            
            # 从坠机切换到侵蚀1
            # 触发条件：当前处于坠机等待，行动力自然恢复到了允许执行侵蚀1的水平（至少5点）
            to_cl1_mask |= is_crashed & (now_state[self.AP] >= self.AP_COSTS[1])
            
            # 从侵蚀1或者短猫切换到坠机
            # 触发条件：行动力低于行动力保留值停止所有，等待行动力自然回复
            to_crashed_mask = (is_cl1 | is_meow) & (now_state[self.AP] < self.ap_preserve)
            
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

                if self.cross_week:
                    cross_week_mask = (sim_days - self.days_until_next_monday) % 7 == 0
                    if np.any(cross_week_mask & cross_day_mask):
                        if self.buy_ap:
                            now_state[self.AP][cross_day_mask & cross_week_mask] += 1000
                        
                        # 每周要塞（应该没人没200行动力吧？
                        now_state[self.AP][cross_day_mask & cross_week_mask] -= 200
                        now_state[self.COIN][cross_day_mask & cross_week_mask] += self.stronghold_reward
            
            # 5. 标记完成状态
            now_state[self.STATUS][now_state[self.USED_TIME] >= self.total_time] = self.STATUS_DONE

            # 6. 记录历史数据
            if self.draw_setting == 'single_sample':
                current_time_0 = now_state[self.USED_TIME][0]
                if current_time_0 > last_time_0:
                    self.history_single['time'].append(current_time_0)
                    self.history_single['ap'].append(now_state[self.AP][0])
                    self.history_single['coin'].append(now_state[self.COIN][0])
                    self.history_single['status'].append(now_state[self.STATUS][0])
                    last_time_0 = current_time_0
            elif self.draw_setting == 'multi_sample':
                self.history_mean['time'].append(np.average(now_state[self.USED_TIME]))
                self.history_mean['ap'].append(np.average(now_state[self.AP]))
                self.history_mean['coin'].append(np.average(now_state[self.COIN]))
                self.history_mean['meow_prob'].append(np.average(now_state[self.STATUS] == self.STATUS_MEOW))
                self.history_mean['has_crashed_prob'].append(np.average(now_state[self.HAS_CRASHED]))
            
        return now_state
    
    def _handle_result(self, result):
        self.logger.info('====================模拟结果====================')

        self.result_cl1_count = np.average(result[self.CL1_COUNT])
        self.logger.info(f'[模拟结果] 侵蚀1次数: {self.result_cl1_count}')
        self.result_meow_count = np.average(result[self.MEOW_COUNT])
        self.logger.info(f'[模拟结果] 短猫次数: {self.result_meow_count}')
        self.result_crashed_probability = np.average(result[self.HAS_CRASHED])
        self.logger.info(f'[模拟结果] 坠机概率: {self.result_crashed_probability}')
        self.result_cl1_total_time = self.result_cl1_count * self.cl1_time
        self.logger.info(f'[模拟结果] 侵蚀一总时长 (h): {self.result_cl1_total_time / 3600}')
        self.result_meow_total_time = self.result_meow_count * self.meow_time
        self.logger.info(f'[模拟结果] 短猫总时长 (h): {self.result_meow_total_time / 3600}')
        self.result_ap = np.average(result[self.AP])
        self.logger.info(f'[模拟结果] 最终行动力: {self.result_ap}')
        self.result_coin = np.average(result[self.COIN])
        self.logger.info(f'[模拟结果] 最终黄币: {self.result_coin}')

        # 获取样本总数，防止请求的 5 个超出范围
        top_k = min(5, self.samples)
        
        # 找到 AP 最低的 5 个索引
        # np.argsort 默认升序，即前 5 个是最小的
        bottom_indices = np.argsort(result[self.AP])[:top_k]
        # 找到 AP 最高的 5 个索引
        top_indices = np.argsort(result[self.AP])[-top_k:][::-1]
        
        self.logger.info(f'[模拟结果] 最差情况 (AP最低的前 {top_k} 个样本):')
        for i, idx in enumerate(bottom_indices):
            self.logger.info(f'  No.{i+1}: AP {result[self.AP][idx]:.1f}, Coin {result[self.COIN][idx]:.0f}')
        
        self.logger.info(f'[模拟结果] 最好情况 (AP最高的后 {top_k} 个样本):')
        for i, idx in enumerate(top_indices):
            self.logger.info(f'  No.{i+1}: AP {result[self.AP][idx]:.1f}, Coin {result[self.COIN][idx]:.0f}')

        if self.draw_setting == 'single_sample':
            self._plot_single_sample_history()
        elif self.draw_setting == 'multi_sample':
            self._plot_multi_sample_history()

    def _plot_single_sample_history(self):
        self.logger.info("正在生成单样本轨迹图...")
        
        fig, ax1 = plt.subplots(figsize=(18, 6))
        
        times = np.array(self.history_single['time']) / 86400
        aps = self.history_single['ap']
        coins = self.history_single['coin']
        statuses = self.history_single['status']

        ax1.plot(times, aps, color='blue', label='行动力', linewidth=1.5)
        ax1.set_xlabel('时间 (天)')
        ax1.set_ylabel('行动力', color='blue')
        ax1.tick_params(axis='y', labelcolor='blue')

        ax2 = ax1.twinx()
        ax2.plot(times, coins, color='gold', label='黄币', linewidth=1.5)
        ax2.set_ylabel('黄币', color='gold')
        ax2.tick_params(axis='y', labelcolor='gold')

        if len(times) > 1:
            start_t = times[0]
            current_s = statuses[1]
            for i in range(1, len(times)):
                if statuses[i] != current_s:
                    end_t = times[i-1]
                    if current_s == self.STATUS_CL1:
                        ax1.axvspan(start_t, end_t, facecolor='green', alpha=0.15)
                    elif current_s == self.STATUS_MEOW:
                        ax1.axvspan(start_t, end_t, facecolor='orange', alpha=0.15)
                    elif current_s == self.STATUS_CRASHED:
                        ax1.axvspan(start_t, end_t, facecolor='red', alpha=0.15)
                    start_t = end_t
                    current_s = statuses[i]
            
            if current_s == self.STATUS_CL1:
                ax1.axvspan(start_t, times[-1], facecolor='green', alpha=0.15)
            elif current_s == self.STATUS_MEOW:
                ax1.axvspan(start_t, times[-1], facecolor='orange', alpha=0.15)
            elif current_s == self.STATUS_CRASHED:
                ax1.axvspan(start_t, times[-1], facecolor='red', alpha=0.15)
                
        cl1_patch = mpatches.Patch(color='green', alpha=0.15, label='侵蚀1')
        meow_patch = mpatches.Patch(color='orange', alpha=0.15, label='短猫')
        crash_patch = mpatches.Patch(color='red', alpha=0.15, label='坠机')
        
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2 + [cl1_patch, meow_patch, crash_patch], 
                labels1 + labels2 + ['侵蚀1', '短猫', '坠机'], 
                loc='upper left')

        plt.title('大世界模拟器: 单样本轨迹图')
        plt.tight_layout()
        os.makedirs('./log/oss/figures', exist_ok=True)
        self.result_figure_path = f'./log/oss/figures/{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}_single_sample.png'
        plt.savefig(self.result_figure_path)
        self.logger.info(f"单样本图表已保存至: {self.result_figure_path}")
        plt.close()

    def _plot_multi_sample_history(self):
        self.logger.info("正在生成多样本平均趋势图...")
        
        fig, ax1 = plt.subplots(figsize=(18, 6))

        times = np.array(self.history_mean['time']) / 86400
        aps = self.history_mean['ap']
        coins = self.history_mean['coin']
        meow_probs = self.history_mean['meow_prob']
        crash_probs = self.history_mean['has_crashed_prob']

        ax1.plot(times, aps, color='blue', label='平均行动力', linewidth=2)
        ax1.set_xlabel('平均时间 (天)')
        ax1.set_ylabel('行动力', color='blue')
        ax1.tick_params(axis='y', labelcolor='blue')

        ax2 = ax1.twinx()
        ax2.plot(times, coins, color='gold', label='平均黄币', linewidth=2)
        ax2.set_ylabel('黄币', color='gold')
        ax2.tick_params(axis='y', labelcolor='gold')

        ax3 = ax1.twinx()
        ax3.spines['right'].set_position(('outward', 60))
        ax3.plot(times, meow_probs, color='orange', linestyle='--', label='短猫概率', linewidth=1.5)
        ax3.plot(times, crash_probs, color='red', linestyle='-.', label='坠机概率', linewidth=1.5)
        ax3.set_ylabel('概率', color='black')
        ax3.tick_params(axis='y', labelcolor='black')
        ax3.set_ylim(0, 1.05)

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        lines3, labels3 = ax3.get_legend_handles_labels()
        ax1.legend(lines1 + lines2 + lines3, labels1 + labels2 + labels3, loc='upper left')

        plt.title('大世界模拟器: 多样本平均趋势图')
        plt.tight_layout()
        os.makedirs('./log/oss/figures', exist_ok=True)
        self.result_figure_path = f'./log/oss/figures/{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}_multi_sample.png'
        plt.savefig(self.result_figure_path)
        self.logger.info(f"多样本图表已保存至: {self.result_figure_path}")
        plt.close()
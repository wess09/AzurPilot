"""保留未知恢复批次相位的整数心情模型，不依赖游戏识别或配置对象。"""

from dataclasses import dataclass
from datetime import datetime, timedelta


PERIOD_US = 360_000_000
MAX_SEGMENTS = 64
MAX_OBSERVATION_US = 30_000_000
MICROSECOND = timedelta(microseconds=1)
EPOCH = datetime(1970, 1, 1)
DIC_RECOVER = {'not_in_dormitory': 2, 'dormitory_floor_1': 4, 'dormitory_floor_2': 5}
DIC_RECOVER_MAX = {'not_in_dormitory': 119, 'dormitory_floor_1': 150, 'dormitory_floor_2': 150}
OATH_RECOVER = 1
ONSEN_RECOVER = 1


def time_us(value: datetime) -> int:
    """转换为整数微秒，避免浮点 timestamp 丢失时间精度。"""
    return (value - EPOCH) // MICROSECOND


@dataclass
class EmotionRecoveryState:
    """一个恢复周期内各相位区间对应的心情值。

    区间位于 [0, 360000000)，相位是恢复批次时刻对周期取模的结果。
    学习后允许区间之间有间隙；这些相位已被实测排除，不能重新合并进来。
    相位始终沿用同一绝对时间基准，不能在每次保存时重新初始化。
    """

    record: datetime
    recover: str
    oath: bool
    onsen: bool
    segments: list[tuple[int, int, int]]

    @property
    def signature(self):
        """返回决定当前恢复速度的条件签名。"""
        return [self.recover, self.oath, self.onsen]

    @property
    def speed(self):
        """返回每个恢复周期的整数心情增量。"""
        return DIC_RECOVER[self.recover] + int(self.oath) + int(self.onsen)

    @property
    def cap(self):
        """返回当前恢复条件允许达到的心情上限。"""
        return 150 if self.onsen else DIC_RECOVER_MAX[self.recover]

    @property
    def lower(self):
        """获取所有可能恢复相位对应心情的下界。"""
        if len(self.segments) == 1:
            return self.segments[0][2]
        return min(value for _, _, value in self.segments)

    @property
    def upper(self):
        """获取所有可能恢复相位对应心情的上界。"""
        if len(self.segments) == 1:
            return self.segments[0][2]
        return max(value for _, _, value in self.segments)

    @property
    def value(self):
        """返回用于展示的心情区间中间值。"""
        if len(self.segments) == 1:
            return self.segments[0][2]
        return (self.lower + self.upper) // 2

    @classmethod
    def calibrate(cls, value, record, recover, oath, onsen):
        """用同一时刻的实测整数心情建立基准；恢复相位仍完全未知。"""
        if type(value) is not int or not 0 <= value <= 150:
            raise ValueError('实测心情必须是 0–150 的整数')
        if recover not in DIC_RECOVER or type(oath) is not bool or type(onsen) is not bool:
            raise ValueError('心情恢复条件无效')
        time_us(record)
        return cls(record, recover, oath, onsen, [(0, PERIOD_US, value)])

    @classmethod
    def restore(cls, data, value, record, recover, oath, onsen):
        """验证存档版本、恢复条件和三字段一致性，拒绝把旧值当作校准值。"""
        if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] not in (1, 2):
            raise ValueError('尚未校准或恢复存档版本无效')
        signature = data.get('signature')
        if (not isinstance(signature, list) or len(signature) != 3 or
                type(signature[1]) is not bool or type(signature[2]) is not bool or
                signature != [recover, oath, onsen]):
            raise ValueError('恢复条件已改变')
        try:
            saved_record = datetime.fromisoformat(data['record'])
            state = cls.calibrate(value, record, recover, oath, onsen)
            if saved_record != record:
                raise ValueError('心情值、时间和恢复存档不一致')
            segments = data['segments']
            legacy, speed = data['version'] == 1, state.speed
            limit = speed + 2 if legacy else MAX_SEGMENTS
            if not isinstance(segments, list) or not segments or len(segments) > limit:
                raise ValueError('恢复相位区间无效')
            end = 0
            previous_value = None
            for item in segments:
                if not isinstance(item, (list, tuple)) or len(item) != 3 or any(type(x) is not int for x in item):
                    raise ValueError('恢复相位区间无效')
                start, stop, points = item
                if (start < end or not start < stop <= PERIOD_US or not 0 <= points <= 150 or
                        (start == end and points == previous_value) or (legacy and start != end)):
                    raise ValueError('恢复相位区间无效')
                end, previous_value = stop, points
            state.segments = [tuple(item) for item in segments]
            if ((legacy and end != PERIOD_US) or
                    state.upper - state.lower > speed or state.value != value):
                raise ValueError('心情值和恢复范围不一致')
            return state
        except (KeyError, TypeError, OverflowError) as exc:
            raise ValueError('恢复存档无效') from exc

    def export(self):
        """序列化带恢复相位的状态以供配置保存。"""
        return {'version': 2, 'record': self.record.isoformat(timespec='microseconds'),
                'signature': self.signature, 'segments': [list(item) for item in self.segments]}

    @staticmethod
    def _append(segments, start, stop, value):
        """合并连续且心情值相同的相位区间。"""
        if segments and segments[-1][1] == start and segments[-1][2] == value:
            segments[-1] = (segments[-1][0], stop, value)
        else:
            segments.append((start, stop, value))

    def advance(self, now):
        """精确推进所有可能相位，合并相邻相同状态，不按秒采样相位。"""
        old_us, new_us = time_us(self.record), time_us(now)
        if new_us < old_us:
            raise ValueError('时间源早于心情记录，需重新校准')
        # 整数微秒相位在余数 + 1 处改变批次数，边界时刻的批次已经生效。
        cuts = sorted({old_us % PERIOD_US + 1, new_us % PERIOD_US + 1})
        speed, cap = self.speed, self.cap
        segments = []
        for start, stop, value in self.segments:
            edges = [start, *(cut for cut in cuts if start < cut < stop), stop]
            for left, right in zip(edges, edges[1:]):
                ticks = (new_us - left) // PERIOD_US - (old_us - left) // PERIOD_US
                # 移出后宅不会主动把原有的 120–150 心情截成 119。
                points = max(value, min(value + ticks * speed, cap))
                self._append(segments, left, right, points)
        self.segments, self.record = segments, now

    def observe(self, observations):
        """用完整舰队各截图的最低读数过滤相位，不重置基准或扩大范围。

        Args:
            observations: 每个完整分类的 (最低心情, 截图开始下界, 截图结束上界)。
                调用方负责确认六艘船完整、归属及识别可信，期间没有战斗扣减。

        Returns:
            bool: 是否接受观测。矛盾、时间无效或片段超限时原状态完全不变。
        """
        if not isinstance(observations, (list, tuple)) or not observations:
            return False
        origin = time_us(self.record)
        windows = []
        try:
            for points, begin, end in observations:
                if type(points) is not int or not 0 <= points <= 150:
                    return False
                left, right = time_us(begin), time_us(end)
                if not origin <= left <= right or right - left > MAX_OBSERVATION_US:
                    return False
                windows.append((points, left, right))
        except (TypeError, ValueError, OverflowError, AttributeError):
            return False
        cuts = sorted({origin % PERIOD_US + 1} |
                      {value % PERIOD_US + 1 for _, left, right in windows for value in (left, right)})
        speed, cap = self.speed, self.cap
        kept = []
        for start, stop, value in self.segments:
            edges = [start, *(cut for cut in cuts if start < cut < stop), stop]
            for left, right in zip(edges, edges[1:]):
                matches_minimum = False
                for points, begin, end in windows:
                    first_ticks = (begin - left) // PERIOD_US - (origin - left) // PERIOD_US
                    last_ticks = (end - left) // PERIOD_US - (origin - left) // PERIOD_US
                    low = max(value, min(value + first_ticks * speed, cap))
                    high = max(value, min(value + last_ticks * speed, cap))
                    if points < low:
                        break
                    # 窗口至多跨一次批次；中间整数并不是真实可能值。
                    matches_minimum |= points == low or points == high
                else:
                    # 至少有一个分类含真实最低心情的船；不能合并异时读数取 min。
                    if matches_minimum:
                        self._append(kept, left, right, value)
        if not kept or len(kept) > MAX_SEGMENTS:
            return False
        # 预留后续推进的值分界，防止碎片化观测导致将来存档超过硬上限。
        components = sum(i == 0 or kept[i - 1][1] != item[0] for i, item in enumerate(kept))
        if components + 2 * (speed + 1) > MAX_SEGMENTS:
            return False
        candidate = EmotionRecoveryState(self.record, self.recover, self.oath, self.onsen, kept)
        candidate.advance(max(end for _, _, end in observations))
        if len(candidate.segments) > MAX_SEGMENTS:
            return False
        self.segments, self.record = candidate.segments, candidate.record
        return True

    def consume(self, amount):
        """对每个相位扣减同一笔事件，心情最低为零。"""
        if type(amount) is not int or amount < 0:
            raise ValueError('心情扣减必须是非负整数')
        segments = []
        for start, stop, value in self.segments:
            self._append(segments, start, stop, max(value - amount, 0))
        self.segments = segments

    def recovered_at(self, target):
        """所有相位均恢复到目标的最早时刻，向上取整到调度器支持的秒。"""
        if type(target) is not int or not 0 <= target <= 150:
            raise ValueError('心情恢复目标必须是 0–150 的整数')
        if self.lower >= target:
            return self.record
        if target > self.cap:
            raise ValueError('心情恢复目标超过恢复上限')
        now_us = time_us(self.record)
        latest = now_us
        for start, stop, value in self.segments:
            needed = max(target - value, 0)
            if not needed:
                continue
            ticks = (needed + self.speed - 1) // self.speed
            candidates = [start, stop - 1]
            if start <= now_us % PERIOD_US < stop:
                candidates.append(now_us % PERIOD_US)
            last_tick = max((now_us - phase) // PERIOD_US * PERIOD_US + phase for phase in candidates)
            latest = max(latest, last_tick + ticks * PERIOD_US)
        latest = (latest + 999_999) // 1_000_000 * 1_000_000
        return EPOCH + latest * MICROSECOND

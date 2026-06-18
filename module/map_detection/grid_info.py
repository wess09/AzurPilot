from module.base.utils import location2node


class GridInfo:
    """收集 map_v1 中网格基本信息的类。

    访问碧蓝航线WIKI http://wiki.biligame.com/blhx 可获取地图基本信息。
    例如访问 http://wiki.biligame.com/blhx/7-2 可了解战役 7-2 的详情，
    包括 Boss 点位和敌人刷新点。

    网格包含以下可从 WIKI 获取的固定属性。
    | 显示名     | 属性名                   | 说明                    |
    |------------|--------------------------|-------------------------|
    | ++         | is_land                  | 舰队无法进入陆地        |
    | --         | is_sea                   | 海洋                    |
    | __         | is_submarine_spawn_point | 潜艇刷新点              |
    | SP         | is_spawn_point           | 舰队可能在此刷新        |
    | ME         | may_enemy                | 敌人可能在此刷新        |
    | MB         | may_boss                 | Boss 可能在此刷新       |
    | MM         | may_mystery              | 神秘事件可能在此刷新    |
    | MA         | may_ammo                 | 舰队可在此获取弹药      |
    | MS         | may_siren                | 塞壬/精英敌人刷新点     |
    """
    is_os = False

    # is_sea --
    is_land = False  # ++
    is_spawn_point = False  # SP
    is_submarine_spawn_point = False  # __

    may_enemy = False  # ME
    may_boss = False  # MB
    may_mystery = False  # MM
    may_ammo = False  # MA
    may_siren = False  # MS
    may_ambush = False

    is_enemy = False  # example: 0L 1M 2C 3T 3E
    is_boss = False  # BO
    is_mystery = False  # MY
    is_ammo = False  # AM
    is_fleet = False  # FL
    is_current_fleet = False
    is_submarine = False  # ss
    is_siren = False  # SI
    is_portal = False
    portal_link = ()
    is_maze = False
    maze_round = (0, 1, 2)
    maze_nearby = None  # SelectedGrids

    enemy_scale = 0
    enemy_genre = None  # Light, Main, Carrier, Treasure, Enemy(未知)

    is_cleared = False
    is_caught_by_siren = False
    is_carrier = False  # 是否为神秘事件中刷新的航母
    is_movable = False  # 是否为可移动敌人
    is_mechanism_trigger = False  # 机关是否已触发
    is_mechanism_block = False  # 是否被机关阻挡
    mechanism_trigger = None  # SelectedGrids
    mechanism_block = None  # SelectedGrids
    mechanism_wait = 2  # 等待机关解锁动画的秒数
    is_fortress = False  # 机械要塞
    is_flare = False
    is_missile_attack = False
    may_bouncing_enemy = False
    cost = 9999
    cost_1 = 9999
    cost_2 = 9999
    connection = None
    weight = 1

    location = None

    def decode(self, text):
        text = text.upper()
        dic = {
            '++': 'is_land',
            'SP': 'is_spawn_point',
            '__': 'is_submarine_spawn_point',
            'ME': 'may_enemy',
            'MB': 'may_boss',
            'MM': 'may_mystery',
            'MA': 'may_ammo',
            'MS': 'may_siren',
        }
        valid = text in dic
        for k, v in dic.items():
            self.__setattr__(v, valid and bool(k == text))

        self.may_ambush = not (self.may_enemy or self.may_boss or self.may_mystery or self.may_mystery)
        # if self.may_siren:
        #     self.may_enemy = True
        # if self.may_boss:
        #     self.may_enemy = True

    def encode(self):
        dic = {
            '++': 'is_land',
            'BO': 'is_boss',
        }
        for key, value in dic.items():
            if self.__getattribute__(value):
                return key

        if self.is_siren:
            if not self.enemy_genre:
                return 'SU'
            # enemy_genre 的格式类似 "Siren_xxx"
            name = self.enemy_genre[6:]
            if '_' in name:
                _, _, name = name.partition('_')
            name = name[:2]
            length = len(name)
            if length == 2:
                return name.upper()
            if length == 1:
                return f'{name.upper()} '
            return 'SU'

        if self.is_enemy:
            return '%s%s' % (
                self.enemy_scale if self.enemy_scale else 0,
                self.enemy_genre[0].upper() if self.enemy_genre else 'E')

        dic = {
            'FL': 'is_current_fleet',
            'Fc': 'is_caught_by_siren',
            'Fl': 'is_fleet',
            'ss': 'is_submarine',
            'MY': 'is_mystery',
            'AM': 'is_ammo',
            'FR': 'is_fortress',
            'MI': 'is_missile_attack',
            'BE': 'may_bouncing_enemy',
            '==': 'is_cleared',
        }
        for key, value in dic.items():
            if self.__getattribute__(value):
                return key

        return '--'

    def __str__(self):
        return location2node(self.location)

    __repr__ = __str__

    def __hash__(self):
        return hash(self.location)

    def __eq__(self, other):
        return self.location == other.location

    @property
    def str(self):
        return self.encode()

    @property
    def is_sea(self):
        return False if self.is_land or self.is_enemy or self.is_siren or self.is_fortress or self.is_boss else True

    @property
    def may_carrier(self):
        return self.is_sea and not self.may_enemy

    @property
    def is_accessible(self):
        return self.cost < 9999

    @property
    def is_accessible_1(self):
        return self.cost_1 < 9999

    @property
    def is_accessible_2(self):
        return self.cost_2 < 9999

    @property
    def is_nearby(self):
        return self.cost < 20

    def merge(self, info, mode='normal'):
        """将扫描到的网格信息合并到当前网格。

        Args:
            info (GridInfo): 待合并的网格信息。
            mode (str): 扫描模式，如 'init'、'normal'、'carrier'、'movable'。

        Returns:
            bool: 是否合并成功。
        """
        # 潜艇可能出现在任何位置，因此合并信息没有成功/失败之分
        # 但期望潜艇在刷新点处能被尽早发现
        if info.is_submarine:
            if self.is_submarine_spawn_point:
                self.is_submarine = True
            else:
                pass
        if info.is_caught_by_siren:
            if self.is_sea:
                self.is_fleet = True
                self.is_caught_by_siren = True
            else:
                return False
        if info.is_fleet:
            if self.is_sea:
                self.is_fleet = True
                if info.is_current_fleet:
                    self.is_current_fleet = True
                if mode == 'init' and info.is_enemy:
                    # 在初始扫描时，允许网格同时为 is_fleet 和 is_enemy
                    # 以便 fixup_submarine_fleet 获取信息
                    pass
                else:
                    return True
            else:
                return False
        if info.is_boss:
            if not self.is_land and self.may_boss:
                self.is_boss = True
                return True
            else:
                return False
        if info.is_siren:
            if not self.is_land and self.may_siren:
                self.is_siren = True
                self.enemy_scale = 0
                self.enemy_genre = info.enemy_genre
                return True
            elif (mode == 'movable' or self.is_movable) and not self.is_land:
                self.is_siren = True
                self.enemy_scale = 0
                self.enemy_genre = info.enemy_genre
                return True
            else:
                return False
        if info.is_enemy:
            if self.is_fortress:
                # 要塞可以是普通敌人
                return True
            elif not self.is_land and (self.may_enemy or self.is_carrier or mode == 'decoy'):
                self.is_enemy = True
                if info.enemy_scale and not self.enemy_scale:
                    self.enemy_scale = info.enemy_scale
                if info.enemy_scale == 3 and self.enemy_scale == 2:
                    # 但允许 3 覆盖 2
                    self.enemy_scale = info.enemy_scale
                if info.enemy_genre and not (info.enemy_genre == 'Enemy' and self.enemy_genre):
                    self.enemy_genre = info.enemy_genre
                return True
            elif mode == 'carrier' and not self.is_land and self.may_carrier:
                self.is_enemy = True
                self.is_carrier = True
                if info.enemy_scale:
                    self.enemy_scale = info.enemy_scale
                if info.enemy_genre and not (info.enemy_genre == 'Enemy' and self.enemy_genre):
                    self.enemy_genre = info.enemy_genre
                return True
            elif (mode == 'movable' or self.is_movable) and not self.is_land:
                self.is_enemy = True
                if info.enemy_scale:
                    self.enemy_scale = info.enemy_scale
                if info.enemy_genre and not (info.enemy_genre == 'Enemy' and self.enemy_genre):
                    self.enemy_genre = info.enemy_genre
                return True
            else:
                return False
        if info.is_mystery:
            if self.may_mystery:
                self.is_mystery = info.is_mystery
                return True
            else:
                return False
        if info.is_ammo:
            if self.may_ammo:
                self.is_ammo = info.is_ammo
                return True
            else:
                return False
        if info.is_missile_attack:
            if self.may_siren:
                self.is_siren = True
                return True
            elif self.may_enemy:
                self.is_enemy = True
                return True
            # 允许错误的预测
            # else:
            #     return False

        return True

    def wipe_out(self):
        """当舰队踏上网格时调用此方法，清除网格上的敌人/事件信息。"""
        self.is_enemy = False
        self.enemy_scale = 0
        self.enemy_genre = None
        self.is_mystery = False
        self.is_boss = False
        self.is_ammo = False
        self.is_siren = False
        self.is_fortress = False
        self.is_caught_by_siren = False
        self.is_carrier = False
        self.is_movable = False
        if self.is_mechanism_trigger:
            self.mechanism_trigger.set(is_mechanism_trigger=False)
            self.mechanism_block.set(is_mechanism_block=False)

    def reset(self):
        """进入地图后调用此方法，重置网格所有状态。"""
        self.wipe_out()
        self.is_fleet = False
        self.is_current_fleet = False
        self.is_submarine = False
        self.is_cleared = False
        self.is_mechanism_trigger = False
        self.is_mechanism_block = False
        self.mechanism_trigger = None
        self.mechanism_block = None
        self.may_bouncing_enemy = False

    def covered_grid(self):
        """获取被遮挡网格的相对坐标。

        Returns:
            list[tuple]: 被遮挡网格的相对坐标列表。
        """
        if self.is_current_fleet:
            return [(0, -1), (0, -2)]
        if self.is_fleet or self.is_siren or self.is_mystery:
            return [(0, -1)]

        return []

    def distance_to(self, other):
        """计算到另一个网格的曼哈顿距离。

        Args:
            other (GridInfo): 目标网格。

        Returns:
            int: 曼哈顿距离。
        """
        l1 = self.location
        l2 = other.location
        return abs(l1[0] - l2[0]) + abs(l1[1] - l2[1])

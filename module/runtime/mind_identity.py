"""心智与科技共用群组消歧，目录和计费分类由心智资料独立提供。"""
from module.runtime.fleet_tech_identity import FleetTechIdentity, name_key
from module.runtime.mind_name import _similarity
from module.runtime.mind_calculator import catalog, find_ship, find_ships, normalize_name


class MindIdentity(FleetTechIdentity):
    """复用多值身份索引与正向舰种证据，不借用科技可见图鉴过滤。"""
    extended_retries = False

    def __init__(self, nationalities=None, *, continuous=False):
        self.continuous = continuous
        self.meta_only = nationalities is not None and set(nationalities) == {97}
        super().__init__([row for row in catalog()['ships'].values() if row['group'] != '改造'
                          and (nationalities is None or row['nationality'] in nationalities)])
        # 共享资料来自 Lua；同分按资料中首次出现的群组顺序回填，重复运行不随机选舰。
        self.priority = {gid: index for index, gid in enumerate(self.ships)}

    def fallback(self, texts, frame_rarity='', *, ellipsis=False, aviation=False, surface=False, **kwargs):
        """连续扫描按已核实阵营回填；舰种区分加贺、天城，同分沿 Lua 目录顺序。"""
        reads = [name_key(text) for text in texts]
        ranked = []
        for key, identities in self.names.items():
            score = max((_similarity(read, key, ellipsis) for read in reads), default=0.)
            for gid, retrofit in identities:
                row = self.ships[gid]
                hull = (not aviation or bool(set(row['scan_types']) & {6, 7, 10, 17})
                        or retrofit and row['type'] == '战列')
                hull = hull and (not surface or aviation or bool(set(row['scan_types']) & {4, 5, 13, 18}))
                ranked.append((score, hull, self._info(gid, retrofit)['rarity'] == frame_rarity,
                               -self.priority[gid], not retrofit, gid, retrofit))
        if not ranked:
            return None, '当前阵营的 Lua 目录为空'
        # 舰种仅筛选最相近的一组名字，不能让普通舰种图标压过完全不同的精确名字。
        best = max(item[0] for item in ranked)
        close = [item for item in ranked if best - item[0] <= .05]
        selected = max(close, key=lambda item: (item[1], item[0], item[2], item[3], item[4]))
        info = self._info(selected[-2], selected[-1])
        return info, f'自动回填（阵营限定、Lua 目录优先）：{info["name"]}；匹配度 {selected[0]:.0%}'

    def _truncated_meta_groups(self, texts, ellipsis):
        """完整基础名仍可能只是 META 前缀；只列出共享此精确前缀的身份。"""
        if not ellipsis and not any(str(text).endswith(('..', '…', '⋯')) for text in texts):
            return set()
        groups = set()
        for text in texts:
            key = name_key(text)
            ordinary, meta = self.names.get(key, ()), self.names.get(key + 'meta', ())
            if ordinary and meta:
                groups.update(gid for gid, _ in (*ordinary, *meta))
        return groups

    def candidates(self, texts, *, ellipsis=False):
        groups = self._truncated_meta_groups(texts, ellipsis)
        return sorted(groups) if groups else super().candidates(texts, ellipsis=ellipsis)

    def _info(self, gid, retrofit=False):
        row = self.ships[gid]
        return find_ship(row['retrofit_names'][0] if retrofit else row['name'], gid)

    def needs_retry(self, info):
        # 原心智路径已有 II/META、单字及截断名复读，不能再叠加科技全部相位重读。
        return False

    def stroke_shifts(self, texts):
        """失败短名无冲突精确线索时，用有限相位双读核实细笔画。"""
        hints = {info['group_type'] for text in texts if (info := find_ship(str(text))) is not None}
        return (1, -1, 2, -2) if len(hints) <= 1 else ()

    def match(self, texts, *args, **kwargs):
        # 沿用已有匿名实图核实过的字形修正；不按重名舰逐船补丁选群组。
        from module.runtime.mind_recognition import NAME_CORRECTIONS, _match_name
        texts = [str(text).strip().strip('、,，\'"‘’“”') for text in texts]
        texts = [NAME_CORRECTIONS.get(normalize_name(text), text) for text in texts]
        if self.continuous:
            # 按阵营首扫不再叠加整页、相位及跨阵营复读；失败直接采用明确的回填策略。
            context = dict(kwargs)
            context['meta_frame'] = self.meta_only
            info, note = super().match(texts, *args, **context)
            return (info, note) if info else self.fallback(texts, *args, **context)
        if self.meta_only:
            # 只有实际按钮核验后的 META 阵营能提供这条正向证据。
            kwargs['meta_frame'] = True
        if self._truncated_meta_groups(texts, kwargs.get('ellipsis', False)) and not kwargs.get('meta_frame'):
            return None, '普通舰与 META 共用截断名前缀，需要阵营证据'
        if any(len(find_ships(text)) > 1 for text in texts):
            return super().match(texts, *args, **kwargs)
        rarity = args[0] if args else ''
        if kwargs.get('fuzzy'):
            from module.runtime.mind_name import match_lua_name
            info, note = match_lua_name(texts, rarity, ellipsis=kwargs.get('ellipsis', False),
                                        meta_frame=kwargs.get('meta_frame', False), aviation=kwargs.get('aviation', False))
        else:
            info, note = _match_name(texts, rarity, ellipsis=kwargs.get('ellipsis', False))
        if info and info.get('group_type') not in self.ships:
            return None, '舰名与已核实的阵营筛选不一致，待核对'
        return info, note

/**
 * @fileoverview 舰队科技图鉴的数据模型与纯函数：图鉴行合并、里程碑联动与筛选匹配。
 */

interface Technology {pt_get: number; pt_upgrage: number; pt_level: number; max_star: number; add_get_shiptype: number[]; add_get_attr: number; add_get_value: number; add_level_shiptype: number[]; add_level_attr: number; add_level_value: number}
/** 图鉴数据源里的单艘舰船，字段名沿用数据源原文。 */
export interface Ship {group_type: number; code: number; handbook_type: number; blueprint: boolean; full_star_rule: 'ordinary_level_cap' | 'explicit_breakthrough'; name: string; names: Record<string, string | null>; nationality: number; rarity: string; type: number; variant?: 'child' | 'mu' | ''; technology: Technology | null}
/** 舰船图鉴目录快照：ships 为全量舰船，updated_at 与 source_commit 记录数据来源，max_points、nation_points 等供科技点数换算。 */
export interface Catalog {ships: Ship[]; nations: Record<string, [number[], number, number][][]>; updated_at: string; source_commit: string; max_points: number; nation_points: Record<string, number>; mind_costs_100_to_120?: Record<string, number>}
/** 需要逐项确认的里程碑：已拥有、满星、120 级。 */
export type Milestone = 'owned' | 'full_star' | 'lv120'
/** 进度记录字段：里程碑之外再加 awakening_pending（待觉醒）。 */
export type RecordField = Milestone | 'awakening_pending'
/** 里程碑是否达成的布尔状态。 */
export type State = boolean
/** 一条进度修改：group_type 定位舰船组，各可选布尔为要写成的记录字段。 */
export interface Change {group_type: number; owned?: State; full_star?: State; lv120?: State; awakening_pending?: State}
/** 单艘舰船的进度：里程碑状态、各里程碑的证据条目（evidence）、科技点数与完成状态。 */
export interface Progress {source?: string; updated_at?: string; group_type: number; owned: State; full_star: State; lv120: State; awakening_pending: State; current_count: number; current_level: number | null; evidence: Record<Milestone, number[]>; points: number; status: 'complete' | 'unowned' | 'unfinished'}
/** 分类 → 属性 → 数值的两层加成表。 */
export type Bonuses = Record<string, Record<string, number>>
/** 一份已确认的舰队科技报告：进度行、国籍等级、三类加成与合计点数；revision 用于乐观锁。 */
export interface Report {instance: string; revision: string; data_version?: string; ships: Progress[]; nation_levels: Record<string, number | null>; bonuses: Bonuses; ship_bonuses: Bonuses; nation_bonuses: Bonuses; confirmed_points: number; completed: number; milestone_counts: Record<Milestone, number>}
/** 表格行：图鉴静态数据与用户进度的合并视图。 */
export type Row = Ship & Progress
export const milestones: Milestone[] = ['owned', 'full_star', 'lv120']
export const recordFields: RecordField[] = [...milestones, 'awakening_pending']
/** 归并舰种代码：20、21 并入 1；22、23、24 并入 22；其余原样。 */
export const shipType = (value: number) => [20, 21].includes(value) ? 1 : [22, 23, 24].includes(value) ? 22 : value
/**
 * 以图鉴为底、按 group_type 对齐进度报告，产出每艘舰的合并行。
 * 报告里没有记录的舰船按「未拥有、全部里程碑未达成」起步，不从现有持有推断。
 */
export function catalogRows(catalog: Catalog, progress: Progress[]): Row[] {
  const facts = new Map(progress.map(row => [row.group_type, row]))
  return catalog.ships.map(ship => ({...ship, ...(facts.get(ship.group_type) ?? {
    group_type: ship.group_type, owned: false, full_star: false, lv120: false, awakening_pending: false, current_count: 0,
    current_level: null, evidence: {owned: [], full_star: [], lv120: []}, points: 0, status: 'unowned' as const,
  })}))
}
/** 该舰的三个里程碑是否全部勾上。 */
export function complete(row: Row) {return milestones.every(key => row[key] === true)}
/**
 * 判断一行是否命中筛选：搜索词对舰名与代号；普通筛选键（舰种、状态、国籍、稀有度）
 * 与选中值取交集；加成类筛选（bonusType/attr 及 get、level 前缀）单独检查科技条目。
 */
export function matches(row: Row, filters: Record<string, string[]>, query: string) {
  if (query && ![row.name, ...Object.values(row.names), String(row.code).padStart(3, '0')].some(value => value?.toLocaleLowerCase().includes(query.toLocaleLowerCase()))) return false
  const statuses = [
    ...(!row.current_count ? ['notHeld'] : ['held']),
    ...(row.owned === false ? ['unowned'] : []),
    ...(row.owned === true ? ['owned'] : []),
    ...(row.lv120 === true ? ['lv120'] : row.owned === true && row.lv120 === false ? ['unfinished'] : []),
    ...(row.full_star === false ? ['missingStar'] : []),
    ...(row.awakening_pending ? ['awakening_pending'] : []),
    ...(row.lv120 === false && !row.awakening_pending ? ['notTrained120'] : []),
    ...(row.lv120 === false ? ['missing120'] : []),
    ...(row.technology && !complete(row) ? ['incomplete'] : []),
    ...(row.technology && complete(row) ? ['complete'] : []),
  ]
  for (const [key, values] of Object.entries(filters)) {
    if (!values.length || ['bonusType', 'attr', 'getBonusType', 'getAttr', 'levelBonusType', 'levelAttr'].includes(key)) continue
    // S(22) 属潜艇位：V(23) 在前排、M(24) 在后排，所以 22/23/24 归并成舰种 22，筛选时再按原始舰种补 front/back。
    const current = key === 'type' ? [String(shipType(row.type)), ...([1, 2, 3, 18, 19, 20, 21, 23].includes(row.type) ? ['front'] : []), ...([4, 5, 6, 7, 10, 12, 13, 24].includes(row.type) ? ['back'] : [])] : key === 'status' ? statuses : key === 'nation' ? [String(row.nationality)] : [row.rarity]
    if (!values.some(value => current.includes(value))) return false
  }
  if (filters.bonusType?.length || filters.attr?.length) {
    const t = row.technology
    if (!t) return false
    const effects = [[t.add_get_shiptype, t.add_get_attr], [t.add_level_shiptype, t.add_level_attr]] as const
    if (!effects.some(([types, attr]) => (!filters.bonusType?.length || types.some(value => filters.bonusType!.includes(String(shipType(value))))) && (!filters.attr?.length || filters.attr.includes(String(attr))))) return false
  }
  for (const stage of ['get', 'level'] as const) {
    const classes = filters[`${stage}BonusType`], attrs = filters[`${stage}Attr`], t = row.technology
    if ((classes?.length || attrs?.length) && (!t
      || classes?.length && !t[`add_${stage}_shiptype`].some(value => classes.includes(String(shipType(value))))
      || attrs?.length && !attrs.includes(String(t[`add_${stage}_attr`])))) return false
  }
  return true
}
/**
 * 里程碑勾选联动：勾上非 owned 自动补勾 owned；ordinary_level_cap 规则下勾 lv120 同时补勾满星。
 * 取消时反向连带：取消 owned 清掉满星与 120 级；ordinary_level_cap 下取消满星连带取消 120 级。
 */
export function changeMilestone(change: Change, key: Milestone, value: State, fullStarRule?: Ship['full_star_rule']): Change {
  const next = {...change, [key]: value}
  if (key === 'owned' && !value) return {...next, full_star: false, lv120: false}
  if (key === 'full_star' && !value && fullStarRule === 'ordinary_level_cap') return {...next, lv120: false}
  if (value && key !== 'owned') next.owned = true
  if (value && key === 'lv120' && fullStarRule === 'ordinary_level_cap') next.full_star = true
  return next
}

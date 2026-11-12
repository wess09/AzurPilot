/**
 * @fileoverview 养成计算的数据模型与候选规则：按组去重取最高副本、筛出待养成候选、解析手动排除计划。
 */

import type {DockCard} from '../api/types'
import type {Catalog, Progress, Ship} from '../fleet-tech/types'
/** 比较所有舰船时一律按完成全部四次觉醒的科技点算，与当前实际进度无关。 */
export function technologyEfficiency(ship: Pick<Ship, 'rarity' | 'technology'> | undefined, mindCosts: Record<string, number>) {
  const points = ship?.technology?.pt_level
  const rarity = ship?.rarity === 'PR' ? 'SSR' : ship?.rarity === 'DR' ? 'UR' : ship?.rarity
  const mind = rarity ? mindCosts[rarity] : undefined
  return {points, mind, value: points != null && mind != null && mind > 0 ? points / mind * 1000 : null}
}
interface CultivationRow {
  id: number; name: string; current_level: number; level: number; target_level: number
  mind: number | null; mind2: number | null; gold: number | null
  status: 'exact' | 'unknown'; notes: string[]; stages: number[]
}
/** 养成计算报告：逐舰明细与整体合计；included、unknown 对应界面上「计入」「信息不足」的计数。 */
export interface CultivationReport {
  instance: string; revision: string; ships: CultivationRow[]; target_level: number
  included: number; unknown: number
  mind: number; mind2: number; gold: number; rules_sha256: string
  mind_costs_100_to_120: Record<string, number>
}
/** 手动排除计划：不参与养成计算的分组号列表，按实例持久化。 */
export interface CultivationPlan {excluded_groups: number[]}
/** 取每组等级最高的一份副本；需核对的卡与无分组号的卡各成一组，不参与同组去重。 */
export function highestCopies(cards: DockCard[]): number[] {
  const groups = new Map<string, DockCard>()
  for (const card of cards) {
    const key = card.review || !card.group_type ? `copy:${card.id}` : `group:${card.group_type}`
    const previous = groups.get(key)
    if (!previous || card.level > previous.level || card.level === previous.level && card.id < previous.id) groups.set(key, card)
  }
  return [...groups.values()].map(card => card.id)
}
/** 账号已完成的成就退役后仍然保留；未完成的条目继续作为养成候选。 */
export function automaticCandidates(cards: DockCard[], catalog: Catalog, progress: Progress[]): DockCard[] {
  const supported = new Set(catalog.ships.filter(row => row.technology).map(row => row.group_type))
  const completed = new Set(progress.filter(row => row.lv120 === true).map(row => row.group_type))
  const confirmed = cards.filter(card => !card.review && card.group_type && supported.has(card.group_type))
  const highest = new Set(highestCopies(confirmed))
  return confirmed.filter(card => highest.has(card.id) && card.level < 120 && !completed.has(card.group_type!))
}
/** 解析手动排除计划：只保留目录里存在的分组号并去重；损坏或非法数据回落为空排除表。 */
export function readPlan(raw: string | null, cards: DockCard[]): CultivationPlan {
  const groups = new Set(cards.map(card => card.group_type))
  try {
    const value = JSON.parse(raw ?? 'null') as CultivationPlan
    if (value && Array.isArray(value.excluded_groups)) {
      return {excluded_groups: [...new Set(value.excluded_groups.filter(id => Number.isInteger(id) && groups.has(id)))]}
    }
  } catch { /* 偏好损坏时宁可全不排除，也不能错误改动已确认的数据。 */ }
  return {excluded_groups: []}
}

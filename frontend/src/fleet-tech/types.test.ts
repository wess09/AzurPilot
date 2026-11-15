/**
 * @fileoverview 舰队科技目录计算与筛选的回归：里程碑默认未记录、退役不等于从未获得、帆船舰种归一与修正联动。
 */

import {describe, expect, it} from 'vitest'
import {catalogRows, changeMilestone, complete, matches, type Catalog, type Row} from './types'
const row: Row = {group_type: 10102, code: 4, handbook_type: 0, blueprint: false, full_star_rule: 'ordinary_level_cap', name: '杜威', names: {cn: '杜威', en: 'Dewey'}, nationality: 1, rarity: 'R', type: 20,
  owned: true, full_star: false, lv120: true, awakening_pending: false, current_count: 0, current_level: null, evidence: {owned: [], full_star: [], lv120: []}, status: 'unfinished', points: 8,
  technology: {pt_get: 3, pt_upgrage: 7, pt_level: 5, max_star: 5, add_get_shiptype: [1, 20, 21], add_get_attr: 1, add_get_value: 1, add_level_shiptype: [7], add_level_attr: 5, add_level_value: 1}}
const catalog: Catalog = {ships: [row, {...row, group_type: 10103, name: '卡辛', code: 5}], nations: {}, updated_at: '', source_commit: '', max_points: 30, nation_points: {}}
describe('authoritative cumulative technology', () => {
  it('keeps the full catalog and defaults unrecorded milestones to incomplete', () => {
    const rows = catalogRows(catalog, [row])
    expect(rows).toHaveLength(2)
    expect(rows[1]).toMatchObject({owned: false, full_star: false, lv120: false, current_count: 0, points: 0})
    expect(matches(rows[1]!, {status: ['unowned']}, '')).toBe(true)
  })
  it('does not equate retirement with never obtained or erase confirmed rewards', () => {
    expect(matches(row, {status: ['notHeld']}, '')).toBe(true)
    expect(matches(row, {status: ['unowned']}, '')).toBe(false)
    expect(catalogRows(catalog, [row])[0]?.points).toBe(8)
  })
  it('requires all three milestones for complete technology', () => {
    expect(complete(row)).toBe(false)
    expect(matches(row, {status: ['incomplete']}, '')).toBe(true)
    expect(complete({...row, full_star: true})).toBe(true)
    expect(matches({...row, lv120: false}, {status: ['missing120']}, '')).toBe(true)
  })
  it('keeps duplicate counts and current level separate from milestones', () => {
    const held = {...row, owned: false, current_count: 2, current_level: 120}
    expect(catalogRows(catalog, [held])[0]).toMatchObject({owned: false, current_count: 2})
    expect(matches(held, {status: ['held']}, 'dewey')).toBe(true)
  })
  it('requires bonus attribute and class to match the same stage', () => {
    expect(matches(row, {bonusType: ['1'], attr: ['5']}, '')).toBe(false)
    expect(matches(row, {getBonusType: ['1'], getAttr: ['1']}, '')).toBe(true)
    expect(matches(row, {levelBonusType: ['1'], levelAttr: ['1']}, '')).toBe(false)
  })
})

describe('ship position and class filters', () => {
  // 分组 ID 与原始舰种码取自权威数据 assets/ship/ship_data.json（group * 10 + 1）。
  const sailing = [
    {...row, group_type: 960001, name: '皇家财富号', nationality: 96, type: 22},
    {...row, group_type: 960003, name: '金鹿号', nationality: 96, type: 23},
    {...row, group_type: 960002, name: '圣马丁号', nationality: 96, type: 24},
  ]
  it('classifies sailing S, V and M by their raw positions', () => {
    expect(sailing.map(ship => matches(ship, {type: ['front']}, ''))).toEqual([false, true, false])
    expect(sailing.map(ship => matches(ship, {type: ['back']}, ''))).toEqual([false, false, true])
    expect(sailing.map(ship => matches(ship, {type: ['22']}, ''))).toEqual([true, true, true])
    expect(sailing.map(ship => matches(ship, {type: ['8']}, ''))).toEqual([false, false, false])
  })
  it('retains ordinary surface and submarine position exclusions', () => {
    const ships = [1, 20, 21, 2, 5, 7, 8, 17].map(type => ({...row, type}))
    expect(ships.map(ship => matches(ship, {type: ['front']}, ''))).toEqual([true, true, true, true, false, false, false, false])
    expect(ships.map(ship => matches(ship, {type: ['back']}, ''))).toEqual([false, false, false, false, true, true, false, false])
    expect(ships.map(ship => matches(ship, {type: ['1']}, ''))).toEqual([true, true, true, false, false, false, false, false])
  })
  it('ORs selections within the type filter and ANDs separate filters', () => {
    const ships = [...sailing, {...row, type: 1}, {...row, type: 5}, {...row, type: 8}]
    expect(ships.map(ship => matches(ship, {type: ['front', '22']}, ''))).toEqual([true, true, true, true, false, false])
    expect(ships.map(ship => matches(ship, {type: ['back', '8']}, ''))).toEqual([false, false, true, false, true, true])
    expect(sailing.map(ship => matches(ship, {type: ['22'], nation: ['96']}, ''))).toEqual([true, true, true])
    expect(sailing.map(ship => matches(ship, {type: ['22'], nation: ['1']}, ''))).toEqual([false, false, false])
  })
  it('normalizes sailing types in both general and stage-specific bonus filters', () => {
    for (const type of [22, 23, 24]) {
      const ship = {...row, technology: {...row.technology!, add_get_shiptype: [type], add_level_shiptype: [type]}}
      expect(matches(ship, {bonusType: ['22'], attr: ['1']}, '')).toBe(true)
      expect(matches(ship, {getBonusType: ['22'], getAttr: ['1'], levelBonusType: ['22'], levelAttr: ['5']}, '')).toBe(true)
      expect(matches(ship, {bonusType: ['8']}, '')).toBe(false)
    }
  })
})

describe('explicit correction dependencies', () => {
  it('completes prerequisites and clears dependents when ownership is cancelled', () => {
    expect(changeMilestone({group_type: 1, full_star: true, lv120: true}, 'owned', false)).toEqual({group_type: 1, owned: false, full_star: false, lv120: false})
    expect(changeMilestone({group_type: 1, owned: false}, 'lv120', true, 'ordinary_level_cap')).toEqual({group_type: 1, owned: true, full_star: true, lv120: true})
    expect(changeMilestone({group_type: 1, owned: false}, 'lv120', true, 'explicit_breakthrough')).toEqual({group_type: 1, owned: true, lv120: true})
    expect(changeMilestone({group_type: 1, owned: true, lv120: true}, 'full_star', false, 'ordinary_level_cap')).toEqual({group_type: 1, owned: true, full_star: false, lv120: false})
    expect(changeMilestone({group_type: 1, owned: true, lv120: true}, 'full_star', false, 'explicit_breakthrough')).toEqual({group_type: 1, owned: true, full_star: false, lv120: true})
  })
})

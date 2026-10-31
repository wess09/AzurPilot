import {describe, expect, it} from 'vitest'
import {FLEET_TRAINING, FLEET_LEVEL_TRAINING, FLEET_AFFINITY_TRAINING, taskLabel, taskNavItems} from '../components/taskNavItems'
import {translateUi} from '../i18n'
import {renderToStaticMarkup} from 'react-dom/server'
import {createElement} from 'react'
import {AppContext, type AppContextValue} from '../app/context'
import {TrainingRecords, trainingRecordGroups} from './FleetTraining'
import {rotationRules} from './FleetRotation'

const names = ['企业', '胡德', '厌战', '拉菲', '克利夫兰', '海伦娜']
function recordsFixture(): Parameters<typeof trainingRecordGroups>[0] {
  return {
    formation: {main: {'1': [3, 1, 2].map(slot => ({name: names[slot - 1], slot, level: 119, emotion: 150 - slot}))},
      vanguard: {'1': [6, 4, 5].map(slot => ({name: names[slot - 1], slot, level: 119, emotion: slot === 6 ? 0 : 150 - slot}))}},
    rules: rotationRules({'1': {slots: [6, 4, 2, 5, 1, 3], sources: [3]}}),
    records: Object.fromEntries([
      ...names.map((name, index) => [name, {level: 119, exp: 23456 + index, affinity: 98, fleet: 5, slot: 6, emotion: 50}]),
      ...Array.from({length: 8}, (_, index) => [`完成${index}`, {level: 120, exp: 0, affinity: 100,
        completed_for: {level: 120}, completed_at: `2026-10-26T10:0${index}:00`, fleet: 2, slot: index % 6 + 1, emotion: 80}]),
      ...Array.from({length: 8}, (_, index) => [`历史${index}`, {level: 80, affinity: 50,
        checked_at: `2026-10-26T10:0${index}:00`, fleet: 3, slot: index % 6 + 1}]),
    ]),
  }
}

describe('换船调度记录分组', () => {
  it('未扫描的旧空字符串快照仍可展示历史记录，不要求额外运行扫描', () => {
    for (const formation of ['', '  ', '{}']) {
      const snapshot = {records: {'旧舰船': {level: 99, affinity: 50}}, formation, rules: rotationRules(undefined)}
      const grouped = trainingRecordGroups(snapshot)
      expect(grouped.training).toEqual([])
      expect(grouped.history).toHaveLength(1)
      expect(grouped.history[0]?.name).toBe('旧舰船')
      expect(grouped.history[0]?.slot).toBeUndefined()
    }
  })
  it('按实际舰队和舰位1到6排列，显示真实名字及最新快照心情，零值有效', () => {
    const grouped = trainingRecordGroups(recordsFixture())
    expect(grouped.training.map(row => row.slot)).toEqual([1, 2, 3, 4, 5, 6])
    expect(grouped.training.map(row => row.name)).toEqual(names)
    expect(grouped.training.map(row => row.fleet)).toEqual([1, 1, 1, 1, 1, 1])
    expect(grouped.training.map(row => row.emotion)).toEqual([149, 148, 147, 146, 145, 0])
    expect(grouped.training[0]?.exp).toBe(23456)
  })
  it('完成和历史各取最新六条后按舰位排列，完整底层记录不变', () => {
    const snapshot = recordsFixture(), before = JSON.stringify(snapshot)
    const grouped = trainingRecordGroups(snapshot)
    expect(grouped.completedCount).toBe(8)
    expect(grouped.historyCount).toBe(8)
    expect(grouped.completed.map(row => row.name)).toEqual(['完成6', '完成7', '完成2', '完成3', '完成4', '完成5'])
    expect(grouped.history.map(row => row.name)).toEqual(['历史6', '历史7', '历史2', '历史3', '历史4', '历史5'])
    expect(JSON.stringify(snapshot)).toBe(before)
  })
  it('达到完成状态的在队船只放入完成分类，固定舰位记录属于历史', () => {
    const snapshot = recordsFixture()
    snapshot.records[names[0]!]!.completed_for = {level: 120}
    snapshot.rules['1']!.slots = [1, 2, 3, 4, 5]
    const grouped = trainingRecordGroups(snapshot)
    expect(grouped.training.map(row => row.name)).not.toContain(names[0])
    expect(grouped.completedCount).toBe(9)
    expect(grouped.historyCount).toBe(9)
    expect(grouped.training.map(row => row.slot)).toEqual([2, 3, 4, 5])
  })
  it('旧记录缺少舰位和心情时保留未知，不能从同名多艘船归并进度', () => {
    const snapshot = {records: {'企业': {level: 120, exp: 10, completed_for: {level: 120}}},
      formation: {main: {'1': [{name: '企业', slot: 1, level: 80, emotion: 100}],
        '2': [{name: '企业', slot: 1, level: 90, emotion: 110}]}},
      rules: rotationRules({'1': {slots: [1], sources: [3]}, '2': {slots: [1], sources: [3]}})}
    const grouped = trainingRecordGroups(snapshot)
    expect(grouped.training.map(row => row.level)).toEqual([80, 90])
    expect(grouped.training.map(row => row.exp)).toEqual([undefined, undefined])
    expect(grouped.completed[0]?.fleet).toBeUndefined()
    expect(grouped.completed[0]?.emotion).toBeNull()
  })
  it('最近快照心情未知时不回填旧心情，培养列表不受六条上限约束', () => {
    const snapshot = recordsFixture()
    snapshot.formation = {main: {'1': [{name: names[0], slot: 1, level: 119, emotion: null}],
      '2': names.map((name, index) => ({name: `新${name}`, slot: index + 1, level: 80, emotion: 50}))}}
    snapshot.rules['2'] = {slots: [1, 2, 3, 4, 5, 6], sources: [3]}
    const grouped = trainingRecordGroups(snapshot)
    expect(grouped.training).toHaveLength(7)
    expect(grouped.training[0]?.emotion).toBeNull()
  })
  it('同名舰船按实际舰位展示已实读的60好感，不借用旧同名完成记录', () => {
    const snapshot: Parameters<typeof trainingRecordGroups>[0] = {
      records: {'泛用型布里': {level: 125, exp: 0, affinity: 200, completed_for: {level: 120}, fleet: 6, slot: 4}},
      readings: {'5:4': {name: '泛用型布里', fleet: 5, slot: 4, level: 100, exp: 13669, affinity: 60,
        emotion: 119, checked_at: '2026-10-27T05:19:05'}},
      formation: {vanguard: {'5': [{name: '泛用型布里', slot: 4, level: 100, emotion: 119}],
        '6': [{name: '泛用型布里', slot: 4, level: 100, emotion: null}]}},
      rules: rotationRules({'5': {slots: [4], sources: [3]}, '6': {slots: [4], sources: [3]}}),
    }
    const grouped = trainingRecordGroups(snapshot)
    expect(grouped.training.map(row => row.affinity)).toEqual([60, undefined])
    expect(grouped.training[0]).toMatchObject({fleet: 5, slot: 4, level: 100, exp: 13669, emotion: 119})
    expect(grouped.completedCount).toBe(1)
    snapshot.formation = {vanguard: {'5': [{name: '拉菲', slot: 4, level: 100, emotion: 120}]}}
    expect(trainingRecordGroups(snapshot).training[0]?.affinity).toBeUndefined()
  })
  it('培养与完成行使用已折算等级，保留原始界面等级供核对', () => {
    const snapshot: Parameters<typeof trainingRecordGroups>[0] = {
      records: {
        '花月': {level: 118, display_level: 105, exp: 1594218},
        '文琴佐·焦贝蒂': {level: 120, display_level: 105, exp: 1919750, completed_for: {level: 120}},
      },
      formation: {vanguard: {'1': [{name: '花月', slot: 5, level: 105},
        {name: '文琴佐·焦贝蒂', slot: 6, level: 105}]}},
      rules: rotationRules({'1': {slots: [5, 6], sources: [3]}}),
    }
    const grouped = trainingRecordGroups(snapshot)
    expect(grouped.training[0]).toMatchObject({level: 118, display_level: 105, exp: 1594218})
    expect(grouped.completed[0]).toMatchObject({level: 120, display_level: 105, exp: 1919750})
    const html = renderToStaticMarkup(createElement(AppContext.Provider, {value: {
      ui: (key, params) => translateUi('zh-CN', key, params),
    } as AppContextValue}, createElement(TrainingRecords, {snapshot})))
    expect(html).toContain('实际等级')
    expect(html).toContain('界面等级：105')
  })
  it('用三个独立大框显示，舰队舰位名字心情等列均可查看', () => {
    const html = renderToStaticMarkup(createElement(AppContext.Provider, {value: {
      ui: (key, params) => translateUi('zh-CN', key, params),
    } as AppContextValue}, createElement(TrainingRecords, {snapshot: recordsFixture()})))
    expect(html.match(/<section/g)).toHaveLength(3)
    expect(html.match(/<tr>/g)).toHaveLength(21)
    for (const text of ['培养舰船', '完成舰船', '旧记录舰船', '舰队', '舰位', '心情（最近记录）', '企业', '当前经验'])
      expect(html).toContain(text)
  })
})

describe('统一换船调度入口', () => {
  it('旧规则默认关闭常用，新规则保留常用与原有候补舰队', () => {
    expect(rotationRules({'1': {slots: [4], sources: [3, 4, 5]}})['1']).toEqual({slots: [4], sources: [3, 4, 5], favourite: false})
    expect(rotationRules({'1': {slots: [4], sources: [3, 4, 5], favourite: true}})['1']).toEqual({slots: [4], sources: [3, 4, 5], favourite: true})
    for (const language of ['zh-CN', 'zh-TW', 'en-US', 'ja-JP'] as const)
      for (const key of ['rotation.favourite', 'rotation.favouriteHelp', 'training.stopOnComplete', 'training.stopHelp', 'training.notify', 'training.notifyHelp'] as const)
        expect(translateUi(language, key)).not.toBe(key)
  })
  it('舰队管理只提供一个调度入口，旧名称仍能解析为统一页面名', () => {
    const items = taskNavItems('FleetManagement', ['FleetInfo'])
    expect(items).toContain('FleetSwitch')
    expect(items.filter(item => [FLEET_TRAINING, FLEET_LEVEL_TRAINING, FLEET_AFFINITY_TRAINING].includes(item))).toEqual([])
    expect(taskNavItems('Tool', [])).not.toContain(FLEET_TRAINING)
    for (const task of [FLEET_TRAINING, FLEET_LEVEL_TRAINING, FLEET_AFFINITY_TRAINING])
      expect(taskLabel(task, key => translateUi('zh-CN', key), () => '不应使用任务名')).toBe('换船调度')
  })
  it('四种语言提供小时单位和实际经验记录文案', () => {
    for (const language of ['zh-CN', 'zh-TW', 'en-US', 'ja-JP'] as const)
      for (const key of ['training.title', 'training.moraleTitle', 'training.exp', 'training.checkedAt', 'training.unread', 'training.interval', 'training.reset', 'training.resetHelp', 'training.resetDone'] as const)
        expect(translateUi(language, key)).not.toBe(key)
    expect(translateUi('zh-CN', 'training.interval')).toContain('小时')
    expect(translateUi('zh-CN', 'training.interval')).toContain('等级/好感')
    expect(translateUi('zh-CN', 'training.interval')).toContain('无上限')
  })
})

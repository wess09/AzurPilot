import {describe, expect, it} from 'vitest'
import {rotationRules} from './FleetRotation'
import {FLEET_SWITCH, FLEET_ROTATION, taskLabel, taskNavItems} from '../components/taskNavItems'
import {rotationZhCN} from '../fleet-rotation-i18n'

describe('智能换船配置和入口', () => {
  it('六个舰队的所有舰位默认不变，且未选择候补舰队', () => {
    expect(rotationRules(undefined)).toEqual(Object.fromEntries([1, 2, 3, 4, 5, 6].map(fleet => [fleet, {slots: [], sources: [], favourite: false}])))
  })
  it('从持久化规则恢复指定舰位和多选来源', () => {
    expect(rotationRules('{"1":{"slots":[3,4,5],"sources":[3,4,5,6]}}')[1]).toEqual({slots: [3, 4, 5], sources: [3, 4, 5, 6], favourite: false})
    expect(() => rotationRules('broken')).toThrow()
  })
  it('配置入口收进智能换船，旧名称仍可用于页签', () => {
    expect(taskNavItems('FleetManagement', ['FleetInfo'])).toContain(FLEET_SWITCH)
    expect(taskNavItems('FleetManagement', ['FleetInfo'])).not.toContain(FLEET_ROTATION)
    expect(taskNavItems('Tool', ['FleetScan'])).not.toContain(FLEET_ROTATION)
    expect(taskLabel(FLEET_ROTATION, () => rotationZhCN['rotation.title'], () => '不应使用任务翻译')).toBe('换船配置')
  })
})

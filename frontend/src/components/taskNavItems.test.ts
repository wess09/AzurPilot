/** @fileoverview 侧栏导航拼装的纯函数回归：配置项归属任务解析与舰队分析入口。 */

import { describe, expect, it } from 'vitest'
import { ownerTaskOf, ownerTaskOfGroup, taskNavItems } from './taskNavItems'

describe('ownerTaskOf', () => {
  const args = {
    OpsiAshBeacon: {OpsiAshBeacon: {AttackMode: {}, AssistRequestLimit: {}}},
    Campaign: {Campaign: {Use2xBook: {}}},
  }

  it('把 分组.配置项 解析回它所属的任务', () => {
    expect(ownerTaskOf(args, 'OpsiAshBeacon', 'AttackMode')).toBe('OpsiAshBeacon')
  })

  it('分组名与任务名不同也能解析', () => {
    expect(ownerTaskOf({Main: {Campaign: {Use2xBook: {}}}}, 'Campaign', 'Use2xBook')).toBe('Main')
  })

  it('找不到时返回 undefined，调用方据此不跳转', () => {
    expect(ownerTaskOf(args, 'OpsiAshBeacon', 'NotExist')).toBeUndefined()
    expect(ownerTaskOf({}, 'OpsiAshBeacon', 'AttackMode')).toBeUndefined()
  })
})

describe('ownerTaskOfGroup', () => {
  const args = {
    OpsiAshBeacon: {OpsiAshBeacon: {AttackMode: {}}},
    Main: {Campaign: {Use2xBook: {}}},
  }

  it('卡片命中只按分组是否存在解析任务', () => {
    expect(ownerTaskOfGroup(args, 'Campaign')).toBe('Main')
    expect(ownerTaskOfGroup(args, 'OpsiAshBeacon')).toBe('OpsiAshBeacon')
  })

  it('没有这张卡片时返回 undefined，调用方据此不跳转', () => {
    expect(ownerTaskOfGroup(args, 'NotExist')).toBeUndefined()
    expect(ownerTaskOfGroup({}, 'Campaign')).toBeUndefined()
  })
})


describe('舰队分析入口', () => {
  it('舰队管理提供智能换船和舰船数据两个统一入口', () => {
    expect(taskNavItems('FleetManagement', ['FleetInfo'])).toEqual(['FleetSwitch', 'FleetAnalysis'])
  })
  it('工具菜单隐藏共享扫描任务', () => {
    expect(taskNavItems('Tool', ['Other', 'DockScan'])).toEqual(['Other'])
  })
})

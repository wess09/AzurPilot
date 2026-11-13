import { describe, expect, it } from 'vitest'
import type { Schema } from '../api/types'
import { groupWaiting, runNowChanges, waitingTasks } from './RunNowMenu'

const tasks = [
  {name: 'Commission', nextRun: '', pending: false, state: 'running' as const},
  {name: 'IslandFarm', nextRun: '', pending: true, state: 'pending' as const},
  {name: 'Restart', nextRun: '', pending: false, state: 'waiting' as const},
  {name: 'IslandBusiness', nextRun: '', pending: false, state: 'waiting' as const},
  {name: 'Reward', nextRun: '', pending: false, state: 'waiting' as const},
  {name: 'IslandRancher', nextRun: '', pending: false, state: 'waiting' as const},
]

const menu: Schema['menu'] = {
  Alas: {menu: 'collapse', page: 'setting', tasks: ['Alas', 'General', 'Restart']},
  Reward: {menu: 'collapse', page: 'setting', tasks: ['Commission', 'Reward']},
  Island: {menu: 'collapse', page: 'setting', tasks: ['IslandRancher', 'IslandFarm', 'IslandBusiness']},
  Tool: {menu: 'collapse', page: 'tool', tasks: ['GemsFarming']},
}

describe('批量立刻运行', () => {
  it('只取等待中的任务，跳过重启，保持任务计划顺序', () => {
    expect(waitingTasks(tasks)).toEqual(['IslandBusiness', 'Reward', 'IslandRancher'])
  })

  it('按菜单分组，组内保持任务计划顺序，没有等待任务的分组不列出', () => {
    expect(groupWaiting(waitingTasks(tasks), menu)).toEqual([
      {key: 'Reward', tasks: ['Reward']},
      {key: 'Island', tasks: ['IslandBusiness', 'IslandRancher']},
    ])
  })

  it('NextRun 设为参数默认值，缺少默认值时用 2020-01-01', () => {
    const args = {
      Reward: {Scheduler: {NextRun: {type: 'datetime', value: '2020-01-01 00:00:00'}}},
    } as unknown as Schema['args']
    expect(runNowChanges(['Reward', 'IslandRancher'], args)).toEqual([
      {path: 'Reward.Scheduler.NextRun', value: '2020-01-01 00:00:00'},
      {path: 'IslandRancher.Scheduler.NextRun', value: '2020-01-01 00:00:00'},
    ])
  })
})

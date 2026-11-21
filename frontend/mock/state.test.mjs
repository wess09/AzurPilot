import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { createMockState } from './state.mjs'
import { normalizeReport } from '../src/components/statisticsData'

describe('刷新智能换船状态', () => {
  it('独立接口清空记录并保留调度配置', () => {
    const {dispatch} = createMockState()
    const before = dispatch('config.get', {instance: 'demo-main'})
    const after = dispatch('fleetTraining.reset', {instance: 'demo-main', revision: before.revision})
    expect(after.values.FleetInfo.FleetTraining.State).toEqual({})
    expect(after.values.FleetInfo.FleetRotation.State).toEqual({})
    expect(after.values.FleetInfo.FleetEquipment.State).toEqual({})
    expect(after.values.FleetInfo.FleetInfo.Result).toEqual({})
    expect(after.values.FleetInfo.FleetRotation.Rules).toBe(before.values.FleetInfo.FleetRotation.Rules)
    expect(after.values.FleetInfo.FleetTraining.CheckIntervalHours).toBe(before.values.FleetInfo.FleetTraining.CheckIntervalHours)
    expect(after.values.FleetInfo.FleetEquipment).toEqual(before.values.FleetInfo.FleetEquipment)
    expect(() => dispatch('fleetTraining.reset', {instance: 'demo-main', revision: '过期'})).toThrow(/配置已变化/)
  })
  it('实例运行时拒绝清空', () => {
    const {dispatch} = createMockState()
    dispatch('scheduler.start', {instance: 'demo-main'})
    const before = dispatch('config.get', {instance: 'demo-main'})
    expect(() => dispatch('fleetTraining.reset', {instance: 'demo-main', revision: before.revision})).toThrow(/先停止实例/)
    expect(dispatch('config.get', {instance: 'demo-main'})).toEqual(before)
  })
})

describe('前端模拟服务', () => {
  it('活动候选按实例包名隔离，切换地区时刷新旧选择', () => {
    const {dispatch} = createMockState()
    const schema = dispatch('schema.get', {language: 'zh-CN'})
    for (const [server, packageName] of [
      ['cn', 'com.bilibili.azurlane'], ['en', 'com.YoStarEN.AzurLane'],
      ['jp', 'com.YoStarJP.AzurLane'], ['tw', 'com.hkmanjuu.azurlane.gp'],
    ]) {
      const saved = dispatch('config.patch', {instance: 'demo-main', changes: [
        {path: 'Alas.Emulator.PackageName', value: packageName},
      ]})
      const candidates = schema.args.Event.Campaign.Event[`option_${server}`]
      expect(saved.options['Event.Campaign.Event']).toEqual(candidates)
      expect(saved.values.Event.Campaign.Event).toBe(candidates[0])
    }
    expect(dispatch('config.get', {instance: 'demo-alt'}).options['Event.Campaign.Event'])
      .toEqual(schema.args.Event.Campaign.Event.option_cn)
  })

  it('无效活动选择失败不会部分保存同一批其他字段', () => {
    const {dispatch} = createMockState()
    const initial = dispatch('config.get', {instance: 'demo-main'})
    // 当前四服共用 event_20261022_cn，不能再将台服候选当作无效活动。
    const invalidEvent = 'event_nonexistent'
    expect(() => dispatch('config.patch', {instance: 'demo-main', changes: [
      {path: 'Alas.Emulator.Serial', value: 'should-not-save'},
      {path: 'Event.Campaign.Event', value: invalidEvent},
    ]})).toThrow(/有效选项/)
    expect(dispatch('config.get', {instance: 'demo-main'})).toEqual(initial)
  })

  it('大世界模拟独立于游戏进程，支持完成、绘图、中断和重跑', () => {
    const {dispatch, tick} = createMockState()
    const name = 'demo-main'
    dispatch('config.patch', {instance: name, changes: [{path: 'OpsiSimulator.OpsiSimulatorParameters.Draw', value: 'multi_sample'}]})
    const game = dispatch('overview.get', {instance: name})
    const started = dispatch('opsi.simulator.start', {instance: name})
    expect(started.state).toBe('running')
    expect(dispatch('opsi.simulator.status', {instance: 'demo-alt'}).state).toBe('idle')
    expect(() => dispatch('opsi.simulator.start', {instance: name})).toThrow(/模拟正在进行/)
    tick()
    const status = dispatch('opsi.simulator.status', {instance: name})
    expect(status.state).toBe('completed')
    expect(status.completedSamples).toBe(status.totalSamples)
    expect(status.result.ap).toBe(485.3)
    expect(dispatch('opsi.simulator.figure', {instance: name}).image).toMatch(/^data:image/)
    expect(dispatch('overview.get', {instance: name}).status).toBe(game.status)
    expect(dispatch('opsi.simulator.status', {instance: name, after: status.logs.cursor}).logs.entries).toEqual([])
    expect(dispatch('opsi.simulator.start', {instance: name}).runId).toBe(started.runId + 1)
    expect(dispatch('opsi.simulator.figure', {instance: name}).image).toBeNull()
    expect(dispatch('opsi.simulator.stop', {instance: name}).state).toBe('interrupted')
  })
  it('配置按实例隔离，合并过期快照的字段修改并拒绝非原子保存', () => {
    const {dispatch} = createMockState()
    const initial = dispatch('config.get', {instance: 'demo-main'})
    const params = {instance: 'demo-main', revision: initial.revision, changes: [{path: 'Alas.Emulator.Serial', value: 'mock-serial'}]}
    const saved = dispatch('config.patch', params)
    expect(saved.values.Alas.Emulator.Serial).toBe('mock-serial')
    expect(dispatch('config.get', {instance: 'demo-alt'}).values.Alas.Emulator.Serial).toBe('127.0.0.1:5557')
    expect(dispatch('config.patch', params)).toEqual(saved)
    expect(() => dispatch('config.patch', {...params, revision: saved.revision, changes: [{path: 'Alas.Emulator.Serial', value: '不应部分保存'}, {path: 'Main.Scheduler.Enable', value: 'false'}]})).toThrow()
    expect(dispatch('config.get', {instance: 'demo-main'})).toEqual(saved)
  })
  it('compares expected values atomically while preserving unrelated updates', () => {
    const {dispatch} = createMockState()
    const instance = 'demo-main'
    const initial = dispatch('config.get', {instance})
    const serial = initial.values.Alas.Emulator.Serial
    dispatch('config.patch', {instance, changes: [{path: 'Main.Scheduler.Enable', value: true}]})
    const saved = dispatch('config.patch', {instance, changes: [{path: 'Alas.Emulator.Serial', value: 'new', expected: serial}]})
    expect(saved.values.Main.Scheduler.Enable).toBe(true)
    expect(() => dispatch('config.patch', {instance, changes: [
      {path: 'Alas.Emulator.Serial', value: 'lost', expected: 'new'},
      {path: 'Main.Scheduler.Enable', value: false, expected: null},
    ]})).toThrow()
    expect(dispatch('config.get', {instance}).values.Alas.Emulator.Serial).toBe('new')
  })
  it('空场景支持创建、复制和删除，重启后恢复初始数据', () => {
    const {dispatch} = createMockState({empty: true})
    expect(dispatch('instances.list')).toEqual([])
    dispatch('instances.create', {name: 'first'})
    expect(() => dispatch('instances.create', {name: 'first'})).toThrow(/同名/)
    dispatch('instances.create', {name: 'second', source: 'first'})
    dispatch('scheduler.start', {instance: 'second'})
    const config = dispatch('config.get', {instance: 'second'})
    expect(() => dispatch('instances.delete', {instance: 'second', revision: config.revision})).toThrow(/停止/)
    dispatch('scheduler.stop', {instance: 'second'})
    dispatch('instances.delete', {instance: 'second', revision: config.revision})
    expect(dispatch('instances.list').map(item => item.name)).toEqual(['first'])
    expect(createMockState({empty: true}).dispatch('instances.list')).toEqual([])
  })
  it('实例名允许汉字与数字，仍拒绝路径字符与保留名', () => {
    const {dispatch} = createMockState({empty: true})
    const allowed = ['测试', '测试实例', 'alas测试', '测试-2', '2ap', 'zz.v2', 'ap 2', '测 试']
    for (const name of allowed) dispatch('instances.create', {name})
    expect(dispatch('instances.list').map(item => item.name)).toEqual(allowed)
    for (const name of ['-测试', '测 试/实例', '测试#1', 'template', 'template.fpy', '.隐藏'])
      expect(() => dispatch('instances.create', {name})).toThrow(/无效/)
  })
  it('实例名规则与前端共享常量保持一致', () => {
    // instanceName.ts 是纯 JS 语法，剥掉每处 export 后可直接求值，两份规则共用同一来源。
    const source = readFileSync(new URL('../src/app/instanceName.ts', import.meta.url), 'utf8')
    const {INSTANCE_NAME_PATTERN} = new Function(`${source.replaceAll('export const', 'const')}\nreturn {INSTANCE_NAME_PATTERN}`)()
    const app = new RegExp(`^(?:${INSTANCE_NAME_PATTERN})$`, 'v')
    const line = readFileSync(new URL('./state.mjs', import.meta.url), 'utf8').split('\n').find(text => text.includes('.test(params.name) ||'))
    const mock = new RegExp(line.match(/!\/(\^[^/]+)\//)[1])
    const names = ['测试', '测试实例', 'alas测试', '測試', '测试-2', 'a', 'A1_b-c', 'x'.repeat(64),
      '2ap', '1测试', '12zz', 'zz.v2', 'ap 2', '测试.1', 'テスト', 'ひらがな', 'ｱｽﾞｰﾙ',
      '-测试', '测试/实例', '测试\\实例', '测 试', '.隐藏', '测试#1', '', 'x'.repeat(65), '..',
      '../template', 'a/b', 'template', 'template.fpy', 'CON', 'c:foo', 'a*b']
    for (const name of names) expect(mock.test(name), name).toBe(app.test(name))
  })
  it('总览投影保留行动力总值并覆盖三个档位', () => {
    const {dispatch} = createMockState()
    const altAp = dispatch('overview.get', {instance: 'demo-alt'}).resources.find(resource => resource.name === 'ActionPoint')
    const mainAp = dispatch('overview.get', {instance: 'demo-main'}).resources.find(resource => resource.name === 'ActionPoint')
    const dogAp = dispatch('overview.get', {instance: 'demo-dog'}).resources.find(resource => resource.name === 'ActionPoint')

    expect(altAp).toMatchObject({value: 99, total: 8001})
    expect(mainAp).toMatchObject({value: 101, total: 6001})
    expect(dogAp).toMatchObject({value: 95, total: 12001})
  })
  it('契约参数、只读字段、语言、日志游标和被动预览可验证', () => {
    const {dispatch, tick} = createMockState()
    expect(() => dispatch('schema.get', {language: '../deploy'})).toThrow(/契约/)
    expect(dispatch('schema.get', {language: 'en-US'}).translations.Emulator.Serial.name).toMatch(/serial/i)
    const config = dispatch('config.get', {instance: 'demo-main'})
    expect(() => dispatch('config.patch', {...config, values: undefined, changes: []})).toThrow(/契约/)
    expect(() => dispatch('config.patch', {instance: config.instance, revision: config.revision, changes: [{path: 'Main.Scheduler.Command', value: 'Main'}]})).toThrow(/不可修改/)
    dispatch('scheduler.start', {instance: 'demo-main'})
    const before = dispatch('logs.get', {instance: 'demo-main'})
    tick()
    expect(dispatch('logs.get', {instance: 'demo-main', after: before.cursor}).entries).toHaveLength(1)
    expect(dispatch('preview.capture', {instance: 'demo-error'}).image).toBeNull()
    const frame = dispatch('preview.capture', {instance: 'demo-main'})
    expect(frame.image).toMatch(/^data:image/)
    expect(dispatch('preview.capture', {instance: 'demo-main'})).toEqual(frame)
  })

  it('指挥喵评分报告按机器共享，demo-alt 用来验证未跑过任务的空状态', () => {
    const {dispatch} = createMockState()
    const result = dispatch('meowfficer.scoreReport', {instance: 'demo-main'})
    expect(result.instance).toBe('demo-main')
    expect(result.count).toBe(result.cats.length)
    expect(result.cats[0]).toMatchObject({cat: '克雷喵', primary: 'submarine'})
    expect(result.cats[0].rubrics[0]).toMatchObject({key: 'submarine', primary: true})
    // 雷暴是加权点制，与真实后端一致：x/y 为 null，用 yLabel 说明这一行的语义。
    expect(result.cats[1]).toMatchObject({cat: '海伦娜喵', primary: 'torpedo'})
    expect(result.cats[1].rubrics[0]).toMatchObject({key: 'torpedo', x: null, y: null, yLabel: '加权命中'})
    // limit 取最新的若干只，但示例数据不足时仍返回全部。
    expect(dispatch('meowfficer.scoreReport', {instance: 'demo-main', limit: 1}).cats).toHaveLength(1)
    expect(() => dispatch('meowfficer.scoreReport', {instance: 'demo-alt'})).toThrow(/尚未生成/)
  })



  it('统计服务提供完整的 9 种资源、5 种大世界趋势及全部分类明细，空实例返回空数据', () => {
    const {dispatch} = createMockState()
    const overview = dispatch('overview.get', {instance: 'demo-main'})
    expect(overview.resources).toHaveLength(12)
    expect(overview.resources.every(item => item.value != null && item.record !== '2020-01-01 00:00:00')).toBe(true)

    const resources = dispatch('statistics.report', {instance: 'demo-main', category: 'resources', days: 7})
    expect(resources.series).toHaveLength(9)
    expect(resources.series[0].label).toBe('石油')
    expect(resources.series.map(s => s.label)).toEqual(['石油', '物资', '钻石', '心智魔方', '活动 PT', '核心数据', '荣誉勋章', '功勋', '舰队币'])
    expect(resources.series[0].points).toHaveLength(24)
    const decoded = normalizeReport(resources)
    expect(decoded.series.flatMap(series => series.points).every(point =>
      Number.isFinite(Date.parse(point.time.replace(' ', 'T'))) && Number.isFinite(point.value))).toBe(true)

    const action = dispatch('statistics.report', {instance: 'demo-main', category: 'action', days: 7})
    expect(action.series).toHaveLength(5)
    expect(action.series.map(s => s.label)).toEqual(['行动力', '行动力资产', '海里数', '作战补给凭证', '特别兑换凭证'])

    const commission = dispatch('statistics.report', {instance: 'demo-main', category: 'commission'})
    expect(commission.series).toHaveLength(5)
    expect(commission.metrics).toHaveLength(6)
    expect(commission.tables).toHaveLength(2)

    const ships = dispatch('statistics.report', {instance: 'demo-main', category: 'ships'})
    expect(ships.series).toHaveLength(3)
    expect(ships.metrics).toHaveLength(8)
    expect(ships.tables).toHaveLength(1)

    const opsi = dispatch('statistics.report', {instance: 'demo-main', category: 'opsi'})
    expect(opsi.metrics).toHaveLength(11)
    expect(opsi.tables).toHaveLength(1)

    const loot = dispatch('statistics.report', {instance: 'demo-main', category: 'loot'})
    // 大世界掉落：收获明细 + 掉落记录 + 原有的短猫收益表
    expect(loot.tables).toHaveLength(3)
    expect(loot.tables[0].title).toBe('大世界掉落明细')
    expect(loot.tables[0].rows[0][0]).toBe('opsi:PlateGeneralT4')
    expect(loot.tables[1].title).toBe('掉落记录')
    expect(loot.tables[2].columns).toContain('平均黄币/轮')
    expect(loot.taskOptions.map(option => option.key)).toContain('opsi_meowfficer_farming')
    expect(loot.metrics.some(metric => metric.icon === 'opsi:GearDesignPlanPlaneT5')).toBe(true)

    const altResources = dispatch('statistics.report', {instance: 'demo-alt', category: 'resources'})
    expect(altResources.series[0].points).toHaveLength(0)
    const altLoot = dispatch('statistics.report', {instance: 'demo-alt', category: 'loot'})
    expect(altLoot.metrics).toHaveLength(0)
    expect(altLoot.tables[0].rows).toHaveLength(0)
    expect(altLoot.tables.at(-1).rows).toHaveLength(0)

    const longRange = dispatch('statistics.report', {instance: 'demo-main', category: 'resources', days: 365})
    expect(longRange.series[0].points).toHaveLength(24)
    const singleResource = dispatch('statistics.resources', {instance: 'demo-main', resource: 'Oil', days: 30})
    expect(singleResource.points).toHaveLength(24)
  })
})

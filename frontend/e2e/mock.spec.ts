import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

test('换船常用候补可保存，保留舰队来源且手机布局不溢出', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.language', 'zh-CN'))
  await page.goto('/#/i/demo-main/task/FleetSwitch?tab=rotation')
  const fleet = page.getByRole('region', {name: '第 1 舰队', exact: true})
  const common = fleet.getByRole('checkbox', {name: '常用', exact: true})
  await expect(common).not.toBeChecked()
  const original = await Promise.all([3, 4, 5].map(number => fleet.getByRole('checkbox', {name: `候补舰队 ${number}`, exact: true}).isChecked()))
  await common.check()
  await fleet.getByRole('checkbox', {name: '候补舰队 3', exact: true}).check()
  await fleet.getByRole('checkbox', {name: '候补舰队 4', exact: true}).check()
  await fleet.getByRole('checkbox', {name: '候补舰队 5', exact: true}).check()
  await page.getByRole('button', {name: '保存规则', exact: true}).click()
  await expect(page.getByRole('button', {name: '保存规则', exact: true})).toBeDisabled()
  await page.reload()
  await expect(common).toBeChecked()
  for (const number of [3, 4, 5])
    await expect(fleet.getByRole('checkbox', {name: `候补舰队 ${number}`, exact: true})).toBeChecked()
  await page.setViewportSize({width: 390, height: 844})
  await common.scrollIntoViewIfNeeded()
  await expect(common).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await fleet.screenshot({path: 'test-results/fleet-favourite-mobile.png', animations: 'disabled'})
  await common.uncheck()
  for (const [index, number] of [3, 4, 5].entries())
    await fleet.getByRole('checkbox', {name: `候补舰队 ${number}`, exact: true}).setChecked(original[index]!)
  await page.getByRole('button', {name: '保存规则', exact: true}).click()
  await expect(page.getByRole('button', {name: '保存规则', exact: true})).toBeDisabled()
})

test('全部达标停止和培养推送默认关闭并可独立保存', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.language', 'zh-CN'))
  await page.goto('/#/i/demo-main/task/FleetSwitch?tab=training')
  const stop = page.getByRole('checkbox', {name: '本轮全部达标后停止练级任务', exact: true})
  const push = page.getByRole('checkbox', {name: '启用培养与换船推送', exact: true})
  await expect(stop).not.toBeChecked()
  await expect(push).not.toBeChecked()
  await stop.check()
  await push.check()
  await page.getByRole('button', {name: '保存调度设置', exact: true}).click()
  await expect(page.getByRole('button', {name: '保存调度设置', exact: true})).toBeDisabled()
  await page.reload()
  await expect(stop).toBeChecked()
  await expect(push).toBeChecked()
  for (const name of ['心情调度', '等级调度', '好感调度'])
    await expect(page.getByRole('switch', {name: `启用${name}`, exact: true})).toHaveAttribute('aria-checked', 'false')
  await page.setViewportSize({width: 390, height: 844})
  await stop.scrollIntoViewIfNeeded()
  await expect(stop).toBeVisible()
  await expect(push).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await stop.locator('..').locator('..').screenshot({path: 'test-results/fleet-training-options-mobile.png', animations: 'disabled'})
  await stop.uncheck()
  await push.uncheck()
  await page.getByRole('button', {name: '保存调度设置', exact: true}).click()
  await expect(page.getByRole('button', {name: '保存调度设置', exact: true})).toBeDisabled()
})

test('换船休息默认关闭，楼层可保存且不改变其他调度开关', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.material', 'plain')
  })
  await page.goto('/#/i/demo-main/task/FleetSwitch?tab=training')
  const dorm = page.getByRole('region', {name: '换船休息', exact: true})
  const toggle = dorm.getByRole('switch', {name: '启用换船休息', exact: true})
  const floor = dorm.getByRole('combobox', {name: '后宅楼层', exact: true})
  await expect(toggle).toHaveAttribute('aria-checked', 'false')
  await expect(floor).toHaveValue('floor_1')
  await floor.selectOption('floor_2')
  await page.getByRole('button', {name: '保存调度设置', exact: true}).click()
  await expect(page.getByRole('button', {name: '保存调度设置', exact: true})).toBeDisabled()
  await page.reload()
  await expect(toggle).toHaveAttribute('aria-checked', 'false')
  await expect(floor).toHaveValue('floor_2')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-checked', 'true')
  await page.reload()
  await expect(toggle).toHaveAttribute('aria-checked', 'true')
  await expect(floor).toHaveValue('floor_2')
  for (const name of ['心情调度', '等级调度', '好感调度'])
    await expect(page.getByRole('switch', {name: `启用${name}`, exact: true})).toHaveAttribute('aria-checked', 'false')
  await expect(dorm).toContainText('全队出击、道中队、Boss队优先')
  await dorm.screenshot({path: 'test-results/fleet-dorm-desktop.png', animations: 'disabled'})
  await page.setViewportSize({width: 390, height: 844})
  await dorm.scrollIntoViewIfNeeded()
  await expect(toggle).toBeVisible()
  await expect(floor).toBeVisible()
  await dorm.screenshot({path: 'test-results/fleet-dorm-mobile.png', animations: 'disabled'})
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-checked', 'false')
  await floor.selectOption('floor_1')
  await page.getByRole('button', {name: '保存调度设置', exact: true}).click()
  await expect(page.getByRole('button', {name: '保存调度设置', exact: true})).toBeDisabled()
})

test('智能换船整合四个页签，旧入口兼容且刷新与手机布局正常', async ({page}) => {
  const methods: string[] = []
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'plain')
    localStorage.setItem('azurpilot.background.plain', JSON.stringify({source: 'off'}))
  })
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {methods.push(JSON.parse(String(message)).method); server.send(message)})
    server.onMessage(message => socket.send(message))
  })
  await page.goto('/#/i/demo-main/task/FleetSwitch')
  await expect(page.getByRole('heading', {name: '智能换船', exact: true})).toBeVisible()
  const tabs = page.getByRole('tablist', {name: '智能换船'})
  await expect(tabs.getByRole('tab')).toHaveText(['舰队信息', '换船配置', '换船调度', '换船装备'])
  await expect(page.getByRole('tabpanel')).toHaveAccessibleName('舰队信息')
  await expect(page.getByRole('tabpanel').locator('.loading')).toHaveCount(0)
  await page.getByRole('button', {name: '舰队管理', exact: true}).hover()
  const menu = page.getByRole('menu', {name: '舰队管理', exact: true})
  await expect(menu.getByRole('menuitem')).toHaveText(['智能换船', '舰船数据'])
  await menu.getByRole('menuitem', {name: '智能换船', exact: true}).click()
  for (const [id, name] of [['rotation', '换船配置'], ['training', '换船调度'], ['equipment', '换船装备']]) {
    await tabs.getByRole('tab', {name, exact: true}).click()
    await expect(page).toHaveURL(url => url.hash === `#/i/demo-main/task/FleetSwitch?tab=${id}`)
    await expect(page.getByRole('tabpanel')).toHaveAccessibleName(name)
    await expect(page.getByRole('heading', {name, exact: true})).toBeVisible()
    await expect(tabs.getByRole('tab', {name, exact: true})).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('tabpanel').locator('.loading')).toHaveCount(0)
    await expect(page.getByRole('tabpanel').getByRole('alert')).toHaveCount(0)
  }
  await page.reload()
  await expect(tabs.getByRole('tab', {name: '换船装备', exact: true})).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.breadcrumb-current')).toHaveText('智能换船')
  await expect(page.locator('.right-rail')).toHaveCount(0)
  await tabs.getByRole('tab', {name: '换船调度', exact: true}).click()
  await expect(page.getByRole('switch', {name: '启用等级调度', exact: true})).toBeVisible()
  await page.screenshot({path: 'test-results/fleet-switch-desktop.png', animations: 'disabled'})
  await page.setViewportSize({width: 390, height: 844})
  for (const name of ['舰队信息', '换船配置', '换船调度', '换船装备']) {
    await tabs.getByRole('tab', {name, exact: true}).click()
    await expect(page.getByRole('heading', {name, exact: true})).toBeVisible()
    await expect(page.getByRole('tabpanel').locator('.loading')).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await page.screenshot({path: 'test-results/fleet-switch-mobile.png', animations: 'disabled'})
  for (const [task, tab] of [['FleetInfo', 'info'], ['FleetRotation', 'rotation'], ['FleetTraining', 'training'], ['FleetEquipment', 'equipment'], ['FleetLevelTraining', 'training'], ['FleetAffinityTraining', 'training']]) {
    await page.goto(`/#/i/demo-main/task/${task}`)
    await expect(page).toHaveURL(url => url.hash === `#/i/demo-main/task/FleetSwitch?tab=${tab}`)
    await expect(page.getByRole('heading', {name: '智能换船', exact: true})).toBeVisible()
  }
  for (const method of ['config.patch', 'tasks.run', 'scheduler.start', 'scheduler.stop', 'startup.set'])
    expect(methods).not.toContain(method)
})

test('换船调度区分心情触发和毕业检查，移除全舰扫描间隔', async ({page}) => {
  const requests: {method: string; params?: {changes?: {path: string; value: unknown}[]}}[] = []
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'plain')
    localStorage.setItem('azurpilot.background.plain', JSON.stringify({source: 'off'}))
  })
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {requests.push(JSON.parse(String(message))); server.send(message)})
    server.onMessage(message => socket.send(message))
  })
  await page.goto('/#/i/demo-main/task/FleetRotation')
  await expect(page.getByRole('heading', {name: '换船配置', exact: true})).toBeVisible()
  await expect(page.getByRole('switch')).toHaveCount(0)
  await expect(page.getByRole('checkbox', {name: '仅计算更换舰船心情', exact: true})).toHaveCount(0)
  const fleet = page.getByRole('region', {name: '第 1 舰队', exact: true})
  await fleet.getByRole('checkbox', {name: '舰位 4 · 不变', exact: true}).check()
  await fleet.getByRole('checkbox', {name: '候补舰队 3', exact: true}).check()
  await page.getByRole('button', {name: '保存规则', exact: true}).click()
  await expect(page.getByRole('button', {name: '保存规则', exact: true})).toBeDisabled()
  await page.locator('main').getByRole('link', {name: '换船调度', exact: true}).click()
  await expect(page.getByRole('heading', {name: '换船调度', exact: true})).toBeVisible()
  const level = page.getByRole('region', {name: '等级调度', exact: true})
  const affinity = page.getByRole('region', {name: '好感调度', exact: true})
  const interval = '等级/好感检查间隔（小时，0为每次结算，无上限）'
  const sharedInterval = page.getByRole('spinbutton', {name: interval, exact: true})
  const fullInterval = page.getByRole('spinbutton', {name: '全舰队扫描间隔（天）', exact: true})
  for (const title of ['心情调度', '等级调度', '好感调度'])
    await expect(page.getByRole('switch', {name: `启用${title}`, exact: true})).toHaveAttribute('aria-checked', 'false')
  await expect(sharedInterval).toHaveCount(1)
  await expect(sharedInterval).toHaveValue('6')
  await expect(fullInterval).toHaveCount(0)
  await expect(page.getByText(/仅用于等级和好感检查/)).toBeVisible()
  await expect(page.getByText(/心情到保留要求就触发全舰队扫描/)).toBeVisible()
  await page.screenshot({path: 'test-results/fleet-scan-intervals-defaults.png', fullPage: true, animations: 'disabled'})
  await expect(level.getByRole('spinbutton')).toHaveCount(1)
  await expect(affinity.getByRole('spinbutton')).toHaveCount(1)
  await level.getByRole('spinbutton', {name: '目标等级', exact: true}).fill('125')
  await affinity.getByRole('spinbutton', {name: '目标好感', exact: true}).fill('200')
  await sharedInterval.fill('48.5')
  expect(await sharedInterval.getAttribute('max')).toBeNull()
  expect(await sharedInterval.evaluate(element => {
    const cards = document.querySelector('.fleet-grid')!
    return !!(element.compareDocumentPosition(cards) & Node.DOCUMENT_POSITION_FOLLOWING)
  })).toBe(true)
  const selected = page.getByRole('checkbox', {name: '仅计算更换舰船心情', exact: true})
  await selected.check()
  await page.getByRole('button', {name: '保存调度设置', exact: true}).click()
  await expect(page.getByRole('button', {name: '保存调度设置', exact: true})).toBeDisabled()
  for (const title of ['等级调度', '好感调度', '心情调度']) {
    const toggle = page.getByRole('switch', {name: `启用${title}`, exact: true})
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-checked', 'true')
  }
  await page.reload()
  for (const title of ['心情调度', '等级调度', '好感调度'])
    await expect(page.getByRole('switch', {name: `启用${title}`, exact: true})).toHaveAttribute('aria-checked', 'true')
  await page.getByRole('switch', {name: '启用心情调度', exact: true}).click()
  await expect(page.getByRole('switch', {name: '启用心情调度', exact: true})).toHaveAttribute('aria-checked', 'false')
  for (const title of ['等级调度', '好感调度'])
    await expect(page.getByRole('switch', {name: `启用${title}`, exact: true})).toHaveAttribute('aria-checked', 'true')
  await expect(selected).toBeChecked()
  await expect(sharedInterval).toHaveValue('48.5')
  await expect(fullInterval).toHaveCount(0)
  await expect(level.getByRole('spinbutton', {name: '目标等级', exact: true})).toHaveValue('125')
  await expect(affinity.getByRole('spinbutton', {name: '目标好感', exact: true})).toHaveValue('200')
  await sharedInterval.fill('-1')
  await expect(page.getByRole('button', {name: '保存调度设置', exact: true})).toBeDisabled()
  await sharedInterval.fill('0')
  await page.getByRole('button', {name: '保存调度设置', exact: true}).click()
  await expect(page.getByRole('button', {name: '保存调度设置', exact: true})).toBeDisabled()
  await expect(sharedInterval).toBeEnabled()
  await page.reload()
  await expect(sharedInterval).toHaveValue('0')
  await expect(page.locator('.right-rail')).toHaveCount(0)
  await page.screenshot({path: 'test-results/fleet-scheduling-desktop.png', fullPage: true, animations: 'disabled'})
  await page.locator('main').getByRole('link', {name: '换船配置：设置舰位与候补舰队'}).click()
  await expect(fleet.getByRole('checkbox', {name: '舰位 4 · 换船', exact: true})).toBeChecked()
  await expect(fleet.getByRole('checkbox', {name: '候补舰队 3', exact: true})).toBeChecked()
  for (const path of ['FleetLevelTraining', 'FleetAffinityTraining']) {
    await page.goto(`/#/i/demo-main/task/${path}`)
    await expect(page).toHaveURL(/task\/FleetSwitch\?tab=training$/)
    await expect(page.getByRole('heading', {name: '换船调度', exact: true})).toBeVisible()
  }
  await page.setViewportSize({width: 390, height: 844})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({path: 'test-results/fleet-scheduling-mobile.png', fullPage: true, animations: 'disabled'})
  expect(requests.map(item => item.method)).not.toContain('tasks.run')
  expect(requests.map(item => item.method)).not.toContain('scheduler.start')
  const patches = requests.filter(item => item.method === 'config.patch')
  expect(patches.slice(1).flatMap(item => item.params?.changes ?? []).some(item => /\.(Rules|State)$/.test(item.path))).toBe(false)
  const intervals = patches.flatMap(item => item.params?.changes ?? []).filter(item => /CheckInterval/.test(item.path))
  expect(intervals.length).toBeGreaterThan(0)
  expect(intervals.every(item => item.path === 'FleetInfo.FleetTraining.CheckIntervalHours')).toBe(true)
  expect(patches.flatMap(item => item.params?.changes ?? [])
    .some(item => item.path === 'FleetInfo.FleetTraining.FullScanIntervalDays')).toBe(false)
})

test('异常实例无需恢复未完成操作即可刷新换船状态并保留设置', async ({page}) => {
  let cleared = false
  const methods: string[] = []
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'plain')
    localStorage.setItem('azurpilot.background.plain', JSON.stringify({source: 'off'}))
  })
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      methods.push(request.method)
      if (request.method === 'fleetTraining.reset') cleared = true
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      const fleet = response.result?.values?.FleetInfo
      if (fleet && !cleared) {
        fleet.FleetRotation.Rules = JSON.stringify({'1': {slots: [4], sources: [3]}})
        fleet.FleetInfo.Result = {vanguard: {'1': [{name: '热心.改', slot: 4, level: 105, emotion: 136}]}}
        fleet.FleetTraining.State = {records: {
          '热心.改': {fleet: 1, slot: 4, level: 117, exp: 1288961, checked_at: '2026-10-27T19:34:32'},
          '花月': {fleet: 3, slot: 5, level: 120, completed_for: {level: 120}},
          '拉菲': {fleet: 4, slot: 4, level: 80},
        }, checks: {Main: {checked_at: '2026-10-27T19:34:32'}},
        pending: {'1:4': {fleet: 1}}, reading: {fleet: 1}}
        fleet.FleetRotation.State = {'1': {source: 3, pending: {slot: 4}}}
        fleet.FleetEquipment.State = {'1:4': {fleet: 1, slot: 4}}
      }
      socket.send(JSON.stringify(response))
    })
  })
  await page.goto('/#/i/demo-error/task/FleetTraining')
  const groups = ['培养舰船', '完成舰船', '旧记录舰船'].map(name => page.getByRole('region', {name, exact: true}))
  for (const group of groups) await expect(group.locator('tbody tr')).toHaveCount(1)
  const interval = page.getByRole('spinbutton', {name: '等级/好感检查间隔（小时，0为每次结算，无上限）', exact: true})
  const hours = await interval.inputValue()
  const enabled = await page.getByRole('switch', {name: '启用等级调度', exact: true}).getAttribute('aria-checked')
  await expect(page.getByText(/卡住的状态可直接清空，无需先恢复/)).toBeVisible()
  await expect(page.getByRole('button', {name: '刷新状态', exact: true})).toBeEnabled()
  await groups[0].locator('..').screenshot({path: 'test-results/fleet-training-reset-before.png', animations: 'disabled'})
  await page.getByRole('button', {name: '刷新状态', exact: true}).click()
  await expect(page.getByText('换船记录和检查状态已清空', {exact: true})).toBeVisible()
  for (const group of groups) {
    await expect(group.locator('tbody tr')).toHaveCount(0)
    await expect(group.getByText('尚无实读记录', {exact: true})).toBeVisible()
  }
  await expect(interval).toHaveValue(hours)
  await expect(page.getByRole('switch', {name: '启用等级调度', exact: true})).toHaveAttribute('aria-checked', enabled!)
  await groups[0].locator('..').screenshot({path: 'test-results/fleet-training-reset-after.png', animations: 'disabled'})
  await page.screenshot({path: 'test-results/fleet-training-reset-recovery.png', fullPage: true, animations: 'disabled'})
  await page.reload()
  for (const group of groups) await expect(group.locator('tbody tr')).toHaveCount(0)
  expect(methods).toContain('fleetTraining.reset')
  expect(methods).not.toContain('config.patch')
  expect(methods).not.toContain('tasks.run')
  expect(methods).not.toContain('scheduler.start')
  expect(methods).not.toContain('scheduler.stop')
})

test('换船调度记录按舰位展示真实舰名心情，三框区分且历史各不超过六条', async ({page}) => {
  const methods: string[] = []
  await page.setViewportSize({width: 1440, height: 1800})
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'plain')
    localStorage.setItem('azurpilot.background.plain', JSON.stringify({source: 'off'}))
  })
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {methods.push(JSON.parse(String(message)).method); server.send(message)})
    server.onMessage(message => {
      const response = JSON.parse(String(message)), values = response.result?.values?.FleetInfo
      if (values) {
        const names = ['企业', '胡德', '厌战', '拉菲', '克利夫兰', '海伦娜']
        values.FleetRotation.Rules = JSON.stringify({'1': {slots: [6, 2, 3, 1, 5, 4], sources: [3]}})
        values.FleetInfo.Result = {
          main: {'1': [3, 1, 2].map(slot => ({name: names[slot - 1], slot, level: 119, emotion: 151 - slot}))},
          vanguard: {'1': [6, 4, 5].map(slot => ({name: names[slot - 1], slot, level: 119, emotion: slot === 6 ? 0 : 151 - slot}))},
        }
        values.FleetTraining.State = {records: Object.fromEntries([
          ...names.map((name, index) => [name, {level: 119, exp: 23456 + index, affinity: 98,
            checked_at: '2026-10-26T12:34:56', fleet: 5, slot: 6, emotion: 80}]),
          ...['欧根亲王', '圣地亚哥', '独角兽', '萨拉托加', '光辉', '明石', '贝尔法斯特', '绫波'].map((name, index) =>
            [name, {level: 125, exp: 0, affinity: 200, emotion: 100, fleet: 2, slot: index % 6 + 1,
              completed_at: `2026-10-26T11:0${index}:00`, completed_for: {level: 120, affinity: 100}}]),
          ...['加贺', '赤城', '高雄', '爱宕', '翔鹤', '瑞鹤', '长门', '陆奥'].map((name, index) =>
            [name, {level: 80, affinity: 50, checked_at: `2026-10-26T10:0${index}:00`,
              ...(index === 7 ? {} : {fleet: 3, slot: index % 6 + 1, emotion: 50})}]),
        ])}
      }
      socket.send(JSON.stringify(response))
    })
  })
  await page.goto('/#/i/demo-main/task/FleetTraining')
  const training = page.getByRole('region', {name: '培养舰船', exact: true})
  const completed = page.getByRole('region', {name: '完成舰船', exact: true})
  const history = page.getByRole('region', {name: '旧记录舰船', exact: true})
  for (const group of [training, completed, history]) {
    await expect(group).toBeVisible()
    await expect(group.locator('tbody tr')).toHaveCount(6)
  }
  await expect(training.locator('tbody tr td:nth-child(2)')).toHaveText(['舰位 1', '舰位 2', '舰位 3', '舰位 4', '舰位 5', '舰位 6'])
  await expect(training.locator('tbody tr td:nth-child(3)')).toHaveText(['企业', '胡德', '厌战', '拉菲', '克利夫兰', '海伦娜'])
  const row = training.getByRole('row').filter({hasText: '企业'})
  for (const value of ['第 1 舰队', '舰位 1', '150', '119', '23456', '98', '2026-10-26 12:34:56'])
    await expect(row.getByRole('cell', {name: value, exact: true})).toBeVisible()
  await expect(training.getByRole('row').filter({hasText: '海伦娜'}).locator('td').nth(3)).toHaveText('0')
  await expect(completed.getByText('最多显示最近 6 条，共 8 条；完整历史记录保留。')).toBeVisible()
  await expect(history.getByText('最多显示最近 6 条，共 8 条；完整历史记录保留。')).toBeVisible()
  await expect(completed.getByRole('heading')).toHaveText('完成舰船 · 6')
  await expect(history.getByRole('heading')).toHaveText('旧记录舰船 · 6')
  for (const name of ['欧根亲王', '圣地亚哥']) await expect(completed.getByRole('cell', {name, exact: true})).toHaveCount(0)
  for (const name of ['加贺', '赤城']) await expect(history.getByRole('cell', {name, exact: true})).toHaveCount(0)
  await expect(completed.getByRole('row').filter({hasText: '绫波'}).locator('td').nth(5)).toHaveText('0')
  await expect(history.getByRole('row').filter({hasText: '陆奥'}).getByRole('cell', {name: '未读取', exact: true})).toHaveCount(4)
  await page.screenshot({path: 'test-results/fleet-training-three-panels-desktop.png', fullPage: true, animations: 'disabled'})
  await training.locator('..').screenshot({path: 'test-results/fleet-training-three-panels.png', animations: 'disabled'})
  await page.setViewportSize({width: 390, height: 844})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  for (const group of [training, completed, history]) {
    await group.scrollIntoViewIfNeeded()
    await expect(group.getByRole('heading')).toBeVisible()
  }
  await training.scrollIntoViewIfNeeded()
  const tableViewport = training.locator('.training-record-table')
  expect(await tableViewport.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true)
  await tableViewport.evaluate(element => {
    const name = element.querySelector('tbody tr td:nth-child(3)') as HTMLElement
    element.scrollLeft += name.getBoundingClientRect().left - element.getBoundingClientRect().left - 4
  })
  const headingBox = await training.getByRole('heading').boundingBox()
  expect(headingBox!.x).toBeGreaterThanOrEqual(0)
  const nameBox = await row.getByRole('cell', {name: '企业', exact: true}).boundingBox()
  const moraleBox = await row.getByRole('cell', {name: '150', exact: true}).boundingBox()
  expect(nameBox!.x).toBeGreaterThanOrEqual(0)
  expect(moraleBox!.x + moraleBox!.width).toBeLessThanOrEqual(390)
  await training.screenshot({path: 'test-results/fleet-training-three-panels-mobile.png', animations: 'disabled'})
  expect(methods).not.toContain('config.patch')
  expect(methods).not.toContain('tasks.run')
  expect(methods).not.toContain('scheduler.start')
})

test('同名舰船实读按舰位展示60好感，不串用另一艘布里的记录', async ({page}) => {
  const methods: string[] = []
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'plain')
    localStorage.setItem('azurpilot.background.plain', JSON.stringify({source: 'off'}))
  })
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {methods.push(JSON.parse(String(message)).method); server.send(message)})
    server.onMessage(message => {
      const response = JSON.parse(String(message)), values = response.result?.values?.FleetInfo
      if (values) {
        values.FleetRotation.Rules = JSON.stringify({'5': {slots: [1, 4], sources: [3]}, '6': {slots: [4], sources: [3]}})
        values.FleetInfo.Result = {
          main: {'5': [{name: '博格', slot: 1, level: 100, emotion: 150}]},
          vanguard: {'5': [{name: '泛用型布里', slot: 4, level: 100, emotion: 119}],
            '6': [{name: '泛用型布里', slot: 4, level: 100, emotion: null}]},
        }
        values.FleetTraining.State = {
          records: {'博格': {level: 100, exp: 0, affinity: 5, fleet: 5, slot: 1, checked_at: '2026-10-27T05:19:05'}},
          readings: {'5:4': {name: '泛用型布里', fleet: 5, slot: 4, level: 100, exp: 13669, affinity: 60,
            emotion: 119, checked_at: '2026-10-27T05:19:05'}},
          pending: {},
        }
      }
      socket.send(JSON.stringify(response))
    })
  })
  await page.goto('/#/i/demo-main/task/FleetTraining')
  const training = page.getByRole('region', {name: '培养舰船', exact: true})
  await expect(training.locator('tbody tr')).toHaveCount(3)
  const bulin = training.getByRole('row').filter({hasText: '泛用型布里'})
  const current = bulin.filter({hasText: '第 5 舰队'})
  for (const value of ['舰位 4', '100', '13669', '60', '119', '2026-10-27 05:19:05'])
    await expect(current.getByRole('cell', {name: value, exact: true})).toBeVisible()
  await expect(bulin.filter({hasText: '第 6 舰队'}).getByRole('cell', {name: '未读取', exact: true})).toHaveCount(4)
  await expect(page.getByRole('region', {name: '完成舰船', exact: true}).locator('tbody tr')).toHaveCount(0)
  await page.screenshot({path: 'test-results/fleet-training-duplicate-reading.png', fullPage: true, animations: 'disabled'})
  expect(methods).not.toContain('config.patch')
  expect(methods).not.toContain('tasks.run')
  expect(methods).not.toContain('scheduler.start')
})

test('仅等级调度展示未突破舰船的实际120级与存储经验', async ({page}) => {
  const methods: string[] = []
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'plain')
    localStorage.setItem('azurpilot.background.plain', JSON.stringify({source: 'off'}))
  })
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {methods.push(JSON.parse(String(message)).method); server.send(message)})
    server.onMessage(message => {
      const response = JSON.parse(String(message)), values = response.result?.values?.FleetInfo
      if (values) {
        const names = ['阿尔弗雷多·奥里亚尼', '花月', '文琴佐·焦贝蒂']
        values.FleetRotation.Enabled = false
        values.FleetRotation.SelectedOnly = false
        values.FleetTraining.CheckIntervalHours = 6
        values.FleetLevelTraining = {Enabled: true, Target: 120}
        values.FleetAffinityTraining = {Enabled: false, Target: 100}
        values.FleetRotation.Rules = JSON.stringify({'1': {slots: [4, 5, 6], sources: [3, 4]}})
        values.FleetInfo.Result = {vanguard: {
          '1': names.map((name, index) => ({name, slot: index + 4, level: 105, emotion: 150})),
        }}
        values.FleetTraining.State = {
          records: Object.fromEntries(names.map((name, index) => [name, {level: 120, display_level: 105,
            exp: [1917866, 1930058, 1919750][index], fleet: 1, slot: index + 4,
            completed_for: {level: 120}, checked_at: '2026-10-27T18:54:56'}])), pending: {},
        }
      }
      socket.send(JSON.stringify(response))
    })
  })
  await page.goto('/#/i/demo-main/task/FleetTraining')
  await expect(page.getByRole('switch', {name: '启用等级调度', exact: true})).toHaveAttribute('aria-checked', 'true')
  for (const title of ['心情调度', '好感调度'])
    await expect(page.getByRole('switch', {name: `启用${title}`, exact: true})).toHaveAttribute('aria-checked', 'false')
  const completed = page.getByRole('region', {name: '完成舰船', exact: true})
  const rows = completed.locator('tbody tr')
  await expect(rows).toHaveCount(3)
  await expect(completed.getByRole('columnheader', {name: '实际等级', exact: true})).toBeVisible()
  await expect(rows.locator('td:nth-child(5)')).toHaveText(['120', '120', '120'])
  for (const cell of await rows.locator('td:nth-child(5)').all())
    await expect(cell).toHaveAttribute('title', /界面等级：105/)
  await expect(rows.locator('td:nth-child(6)')).toHaveText(['1917866', '1930058', '1919750'])
  await expect(rows.locator('td:nth-child(7)')).toHaveText(['未读取', '未读取', '未读取'])
  await expect(rows.locator('td:nth-child(8)')).toHaveText(Array(3).fill('2026-10-27 18:54:56'))
  await completed.screenshot({path: 'test-results/fleet-training-effective-level-records.png', animations: 'disabled'})
  await page.screenshot({path: 'test-results/fleet-training-level-only.png', fullPage: true, animations: 'disabled'})
  for (const method of ['config.patch', 'tasks.run', 'scheduler.start']) expect(methods).not.toContain(method)
})

test('换船装备页签默认关闭并可独立保存舰种码与开关', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.theme', 'light')
  })
  await page.goto('/#/i/demo-main/task/FleetEquipment')
  await expect(page.getByRole('heading', {name: '换船装备', exact: true})).toBeVisible()
  const toggle = page.getByRole('switch', {name: '启用自动换装备'})
  await expect(toggle).toHaveAttribute('aria-checked', 'false')
  await expect(page.locator('.fleet-grid input[type="text"]')).toHaveCount(45)
  const destroyer = page.getByRole('textbox', {name: '驱逐舰 装备码 1', exact: true})
  const second = page.getByRole('textbox', {name: '驱逐舰 装备码 2', exact: true})
  const third = page.getByRole('textbox', {name: '驱逐舰 装备码 3', exact: true})
  const carrier = page.getByRole('textbox', {name: '航空母舰 装备码 1', exact: true})
  const code = 'MTExLzIyMi8zMzMvMC8wXDA='
  await destroyer.fill(code)
  await second.fill('NDQ0LzU1NS82NjYvMC8wXDA=')
  await third.fill('Nzc3Lzg4OC85OTkvMC8wXDA=')
  await page.getByRole('button', {name: '保存装备码', exact: true}).click()
  await expect(page.getByText('换船装备设置已保存', {exact: true})).toBeVisible()
  await expect(page.getByRole('button', {name: '保存装备码', exact: true})).toBeDisabled()
  await page.reload()
  await expect(destroyer).toHaveValue(code)
  await expect(second).toHaveValue('NDQ0LzU1NS82NjYvMC8wXDA=')
  await expect(third).toHaveValue('Nzc3Lzg4OC85OTkvMC8wXDA=')
  await expect(carrier).toHaveValue('')
  await expect(toggle).toHaveAttribute('aria-checked', 'false')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-checked', 'true')
  await page.reload()
  await expect(toggle).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByText(/同舰种依次使用第1、2、3格/)).toBeVisible()
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-checked', 'false')
  await page.screenshot({path: 'test-results/fleet-equipment-desktop.png', fullPage: true, animations: 'disabled'})
})

test('换船装备页签在手机宽度可编辑且不横向溢出', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844})
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.theme', 'light')
  })
  await page.goto('/#/i/demo-main/task/FleetEquipment')
  await expect(page.getByRole('heading', {name: '换船装备', exact: true})).toBeVisible()
  await expect(page.locator('.fleet-grid input[type="text"]')).toHaveCount(45)
  await page.getByRole('textbox', {name: '驱逐舰 装备码 1', exact: true}).fill('MC8wLzAvMC8wXDA=')
  await page.getByRole('textbox', {name: '风帆舰 装备码 3', exact: true}).scrollIntoViewIfNeeded()
  await expect(page.getByRole('textbox', {name: '风帆舰 装备码 3', exact: true})).toBeVisible()
  await page.getByRole('heading', {name: '换船装备', exact: true}).scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({path: 'test-results/fleet-equipment-mobile.png', fullPage: true, animations: 'disabled'})
})

for (const [server, packageName, language] of [
  ['cn', 'com.bilibili.azurlane', 'zh-CN'],
  ['en', 'com.YoStarEN.AzurLane', 'en-US'],
  ['jp', 'com.YoStarJP.AzurLane', 'ja-JP'],
  ['tw', 'com.hkmanjuu.azurlane.gp', 'zh-TW'],
]) {
  test(`活动候选只显示当前服务器并使用有效选择：${server}`, async ({page}) => {
    await page.addInitScript(language => {
      localStorage.setItem('azurpilot.language', language)
      localStorage.setItem('azurpilot.theme', 'light')
    }, language)
    await page.goto('/#/i/demo-main/task/Event')
    // 仅修改内存模拟实例，通过真实 WebSocket 确认保存后重新加载页面。
    await page.evaluate(packageName => new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(`ws://${location.host}/api/v1/ws`)
      const send = (id: string, method: string, params: object) => socket.send(JSON.stringify({v: 1, type: 'request', id, method, params}))
      socket.onopen = () => send('login', 'auth.login', {password: ''})
      socket.onerror = () => {socket.close(); reject(new Error('模拟 WebSocket 连接失败'))}
      socket.onmessage = event => {
        const response = JSON.parse(String(event.data))
        if (response.type !== 'response') return
        if (!response.ok) {socket.close(); reject(new Error(response.error?.message)); return}
        if (response.id === 'login') send('save', 'config.patch', {instance: 'demo-main', changes: [
          {path: 'Alas.Emulator.PackageName', value: packageName},
        ]})
        if (response.id === 'save') {socket.close(); resolve()}
      }
    }), packageName)
    await page.reload()
    const args = JSON.parse(readFileSync(new URL('../../module/config/argument/args.json', import.meta.url), 'utf8'))
    const translations = JSON.parse(readFileSync(new URL(`../../module/config/i18n/${language}.json`, import.meta.url), 'utf8'))
    const candidates: string[] = args.Event.Campaign.Event[`option_${server}`]
    const labels = candidates.map(value => translations.Campaign.Event[value])
    const control = page.locator('[id="Event.Campaign.Event"]')
    await expect(control).toContainText(labels[0])
    await control.click()
    await expect(page.getByRole('listbox').getByRole('option')).toHaveText(labels)
    await page.screenshot({path: test.info().outputPath(`event-options-${server}.png`), animations: 'disabled'})
  })
}

test('侵蚀一资源检查配置位于献祭流下方且通用页不再显示', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.theme', 'light'))
  await page.goto('/#/i/demo-main/task/OpsiHazard1Leveling')
  const group = page.locator('#group-OpsiHazard1Leveling')
  await expect(group).toBeVisible()
  const fields = await group.locator('.field-row label').evaluateAll(labels => labels.map(label => label.getAttribute('for')))
  const hp = fields.indexOf('OpsiHazard1Leveling.OpsiHazard1Leveling.SkipHpCheck')
  expect(hp).toBeGreaterThanOrEqual(0)
  expect(fields.slice(hp + 1, hp + 3)).toEqual([
    'OpsiHazard1Leveling.OpsiHazard1Leveling.ActionPointCheckInterval',
    'OpsiHazard1Leveling.OpsiHazard1Leveling.SkipStrategicSearchCheck',
  ])
  await expect(group).toContainText('其余时候不截图、不识别')
  const moved = group.locator('label[for$=".SkipStrategicSearchCheck"]')
  await moved.scrollIntoViewIfNeeded()
  await expect(group.locator('label[for$=".SkipHpCheck"]')).toBeInViewport()
  await expect(group.locator('label[for$=".ActionPointCheckInterval"]')).toBeInViewport()
  await page.screenshot({path: test.info().outputPath('cl1-resource-settings.png'), animations: 'disabled'})
  await page.goto('/#/i/demo-main/task/OpsiGeneral')
  await expect(page.locator('#group-OpsiGeneral')).toBeVisible()
  await expect(page.locator('label[for$=".ActionPointCheckInterval"]')).toHaveCount(0)
  await expect(page.locator('label[for$=".SkipStrategicSearchCheck"]')).toHaveCount(0)
})

test('舰队科技完整图鉴区分累计里程碑与当前持有', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.language', 'zh-CN'))
  let catalogCount = 0
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer(), methods = new Map<string, string>()
    socket.onMessage(message => {const request = JSON.parse(String(message)); methods.set(request.id, request.method); server.send(message)})
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      if (response.ok && methods.get(response.id) === 'fleetTech.catalog') catalogCount = response.result.ships.filter((ship: any) => ship.technology).length
      if (response.ok && methods.get(response.id) === 'fleetTech.report') {
        response.result.ships = response.result.ships.map((ship: any) => ({...ship,
          owned: ship.group_type === 10102,
          full_star: ship.group_type === 10102, lv120: ship.group_type === 10102,
          current_count: 0, current_level: null, evidence: {owned: [], full_star: [], lv120: []},
          points: ship.group_type === 10102 ? 15 : 0, status: ship.group_type === 10102 ? 'complete' : 'unowned',
        }))
        response.result.milestone_counts = {owned: 1, full_star: 1, lv120: 1}
        response.result.confirmed_points = 15
        response.result.ship_bonuses = {}; response.result.nation_bonuses = {}
      }
      socket.send(JSON.stringify(response))
    })
  })
  await page.goto('/#/i/demo-main/task/FleetAnalysis?tab=technology')
  const table = page.locator('.ft-table-wrap')
  await expect.poll(() => catalogCount).toBeGreaterThan(50)
  await expect(table.locator('tbody tr')).toHaveCount(catalogCount)
  await expect(page.locator('.ft-summary')).toContainText('里程碑独立保存')
  await expect(page.getByRole('button', {name: '舰船底账', exact: true})).toHaveCount(0)
  await expect(page.getByRole('button', {name: '合并记录', exact: true})).toHaveCount(0)
  await page.getByLabel('搜索舰名', {exact: true}).fill('杜威')
  await expect(table.locator('tr[data-group="10102"]')).toHaveCount(1)
  await expect(table.getByRole('link', {name: '杜威', exact: true})).toHaveAttribute('title', /当前持有: 0/)
  await expect(table.getByRole('button', {name: '杜威 · 满星 · 已完成', exact: true})).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', {name: '未获得', exact: true}).click()
  // 搜索是包含匹配：普通杜威已完成，杜威·META 仍未获得。
  await expect(table.locator('tr[data-group="10102"]')).toHaveCount(0)
  await expect(table.locator('tbody tr')).toHaveCount(1)
  await expect(table.locator('tbody tr')).toContainText('杜威·META')
  await page.getByRole('button', {name: '未获得', exact: true}).click()
  await page.locator('.ft-filters').getByRole('button', {name: 'Lv.120', exact: true}).click()
  await expect(table.locator('tr[data-group="10102"]')).toHaveCount(1)
  await page.setViewportSize({width: 412, height: 950})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  expect(await table.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true)
})

test('统计慢请求合并更新且概览事件不重复取数', async ({page}) => {
  const ids = new Set<string>()
  const held: string[] = []
  let overview = ''
  let emit: (topic: string, instance?: string) => void = () => {}
  let release: () => void = () => {}
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    emit = (topic, instance = 'demo-main') => {
      /* 概览事件回放服务端的真实载荷：右栏直接按 Overview 形状消费事件数据，占位载荷会把它渲染崩。 */
      if (topic === 'overview' && overview) socket.send(overview)
      else socket.send(JSON.stringify({v: 1, type: 'event', topic, seq: 100, data: {instance}}))
    }
    release = () => socket.send(held.shift()!)
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      if (request.method === 'statistics.report') ids.add(request.id)
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      if (response.topic === 'overview') overview = String(message)
      if (ids.has(response.id)) held.push(String(message))
      else if (response.topic !== 'statistics') socket.send(message)
    })
  })
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.statistics', JSON.stringify({category: 'opsi'}))
  })
  await page.goto('/#/i/demo-main/statistics')
  await expect.poll(() => held.length).toBe(1)
  await expect.poll(() => overview !== '', {timeout: 15_000}).toBe(true)
  for (let index = 0; index < 20; index++) {emit('overview'); emit('statistics')}
  await page.waitForTimeout(600)
  expect(ids.size).toBe(1)
  release()
  await expect(page.getByText('出击消耗', {exact: true})).toBeVisible()
  await expect.poll(() => held.length).toBe(1)
  expect(ids.size).toBe(2)
  release()
  for (let index = 0; index < 20; index++) {emit('overview'); emit('statistics', 'demo-alt')}
  await page.waitForTimeout(600)
  expect(ids.size).toBe(2)
  await page.screenshot({path: test.info().outputPath('statistics-coalesced.png'), fullPage: true})
})

test('统计切换分类后丢弃旧响应和旧刷新回调', async ({page}) => {
  let held = ''
  let oldId = ''
  let release: () => void = () => {}
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    release = () => socket.send(held)
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      if (request.method === 'statistics.report' && request.params.category === 'opsi') oldId = request.id
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      if (response.id === oldId && oldId) held = String(message)
      else socket.send(message)
    })
  })
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.statistics', JSON.stringify({category: 'opsi'}))
  })
  await page.goto('/#/i/demo-main/statistics')
  await expect.poll(() => held.length).toBeGreaterThan(0)
  await page.getByRole('tab', {name: '舰船经验', exact: true}).click()
  await expect(page.getByText('目标等级', {exact: true})).toBeVisible()
  release()
  await page.waitForTimeout(400)
  await expect(page.getByText('目标等级', {exact: true})).toBeVisible()
  await expect(page.getByText('出击消耗', {exact: true})).toHaveCount(0)
})

test('大世界掉落缺图回退领奖模板并显示月度Boss筛选', async ({page}) => {
  await page.emulateMedia({reducedMotion: 'reduce'})
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.statistics', JSON.stringify({category: 'loot'}))
  })
  await page.goto('/#/i/demo-main/statistics')
  const detail = page.locator('.statistics-table').filter({has: page.getByRole('heading', {name: '大世界掉落明细', exact: true})})
  await expect(detail).toBeVisible()
  const plan = detail.getByRole('row').filter({hasText: '装备研发图纸UR型'})
  await expect(plan).toContainText('1')
  const icons = page.locator('img[src$="opsi-items/GearDesignPlanT5.png"]')
  await expect(icons).toHaveCount(2)
  await expect.poll(() => icons.evaluateAll(images => images.every(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0))).toBe(true)
  await page.getByRole('combobox', {name: '任务', exact: true}).click()
  await expect(page.getByRole('option', {name: '月度Boss（1）', exact: true})).toBeVisible()
  await page.keyboard.press('Escape')
  await page.screenshot({path: 'test-results/opsi-drop-template-fallback.png', fullPage: true, animations: 'disabled'})
})

test('仓库统计显示快照且刷新不会启动游戏扫描', async ({page}) => {
  const requests: string[] = []
  page.on('websocket', socket => socket.on('framesent', event => {
    const payload = JSON.parse(String(event.payload))
    if (payload.method) requests.push(payload.method)
  }))
  await page.emulateMedia({reducedMotion: 'reduce'})
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.statistics', JSON.stringify({category: 'storage'}))
  })
  await page.goto('/#/i/demo-main/statistics')
  const table = page.locator('.statistics-table').filter({has: page.getByRole('heading', {name: '仓库物品', exact: true})})
  await expect(table).toBeVisible()
  await expect(table.locator('tbody tr')).toHaveCount(25)
  await expect(table.getByRole('row').filter({hasText: '特装型突破部件'})).toContainText('153')
  await expect(table.getByRole('row').filter({hasText: '心智单元II'})).toContainText('1,204')
  await expect.poll(() => table.locator('img').evaluateAll(images => images.length > 0 && images.every(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0))).toBe(true)
  await page.getByRole('button', {name: '刷新统计', exact: true}).first().click()
  expect(requests.filter(method => method === 'tasks.run')).toHaveLength(0)
  await page.screenshot({path: test.info().outputPath('storage-statistics.png'), fullPage: true})
  await page.getByRole('button', {name: '运行仓库统计', exact: true}).first().click()
  await expect.poll(() => requests.filter(method => method === 'tasks.run').length).toBe(1)
  await page.getByRole('button', {name: '运行仓库统计', exact: true}).first().click()
  await expect(page.getByRole('alert')).toContainText('实例已在运行')
  await page.reload()
  await expect(table).toBeVisible()
  await page.goto('/#/i/demo-alt/statistics')
  await expect(table).toBeVisible()
  await expect(table.getByRole('cell', {name: '未扫描', exact: true})).toHaveCount(25)
  await expect(table.getByRole('cell', {name: '—', exact: true})).toHaveCount(25)
})

test('仓库趋势复用时间窗口、物品选择和原始记录', async ({page}) => {
  await page.setViewportSize({width: 1731, height: 1547})
  const requests: Array<{method: string, params: Record<string, unknown>}> = []
  page.on('websocket', socket => socket.on('framesent', event => {
    const payload = JSON.parse(String(event.payload))
    if (payload.method) requests.push(payload)
  }))
  await page.emulateMedia({reducedMotion: 'reduce'})
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.statistics', JSON.stringify({category: 'storage', days: 7}))
  })
  await page.goto('/#/i/demo-main/statistics')
  const chart = page.locator('.statistics-chart')
  await expect(chart.locator('.stat-chip')).toHaveCount(25)
  await expect.poll(() => chart.locator('.stat-chip img').evaluateAll(images => images.length === 25 && images.every(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0))).toBe(true)
  await chart.getByRole('button', {name: '心智单元II', exact: true}).dblclick()
  await expect(chart.getByRole('img', {name: '心智单元II交互趋势图', exact: true})).toBeVisible()
  const raw = page.locator('.statistics-table').filter({has: page.getByRole('heading', {name: '心智单元II原始记录', exact: true})})
  await expect(raw.locator('tbody tr')).toHaveCount(3)
  await expect(raw.locator('tbody tr').first()).toContainText('1,204')
  await expect(chart.getByRole('combobox', {name: '图表类型', exact: true})).toContainText('折线')
  await expect(chart.getByRole('combobox', {name: '采样粒度', exact: true})).toContainText('每次记录')
  await page.getByRole('combobox', {name: '统计天数', exact: true}).first().click()
  await page.getByRole('option', {name: '最近 30 天', exact: true}).click()
  await expect(raw.locator('tbody tr')).toHaveCount(4)
  await expect.poll(() => requests.filter(request => request.method === 'statistics.report').at(-1)?.params.days).toBe(30)
  const firstTime = await raw.locator('tbody tr').first().locator('td').first().innerText()
  await chart.getByLabel('起始时间', {exact: true}).fill(firstTime.replace(' ', 'T').slice(0, 16))
  await expect(raw.locator('tbody tr')).toHaveCount(1)
  await chart.getByRole('button', {name: '全部时间', exact: true}).click()
  await expect(raw.locator('tbody tr')).toHaveCount(4)
  await page.getByRole('heading', {name: '资源统计', exact: true}).scrollIntoViewIfNeeded()
  await page.screenshot({path: test.info().outputPath('storage-trends.png'), fullPage: true})
  expect(requests.some(request => request.method === 'tasks.run')).toBe(false)
})

test('任务分组目录重复点击保持在同一栏目', async ({page}) => {
  await page.emulateMedia({reducedMotion: 'reduce'})
  await page.addInitScript(() => localStorage.setItem('azurpilot.theme', 'light'))
  await page.setViewportSize({width: 1440, height: 600})
  await page.goto('/#/i/demo-main/task/Main')
  const links = page.locator('.config-layout .group-nav a')
  await expect(links.nth(1)).toBeVisible()
  await links.nth(1).click()
  await expect.poll(() => page.evaluate(() => document.scrollingElement!.scrollTop)).toBeGreaterThan(0)
  const firstPosition = await page.evaluate(() => document.scrollingElement!.scrollTop)
  await links.nth(1).click()
  await expect.poll(() => page.evaluate(() => document.scrollingElement!.scrollTop)).toBeCloseTo(firstPosition, 0)
})

test('玻璃装饰不阻挡导航，背景失败降级并尊重减少动态效果', async ({page}) => {
  let backgrounds = 0
  await page.route('https://api.yppp.net/api.php', async route => {
    backgrounds += 1
    await route.fulfill({contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#9acbff"/></svg>'})
  })
  await page.goto('/')
  await expect(page.locator('.wallpaper img')).toBeVisible()
  await expect(page.locator('.glass-material-lens')).toHaveCount(1)
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', {name: '跳转到内容'})).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('main')).toBeFocused()
  await page.locator('.instance-card').first().click()
  await page.getByRole('button', {name: '切换实例'}).click()
  await expect(page.getByRole('menuitemradio').first()).toBeVisible()
  await page.keyboard.press('Escape')
  expect(backgrounds).toBe(1)
  await page.emulateMedia({reducedMotion: 'reduce'})
  await expect(page.locator('.glass-material-lens')).toHaveCount(0)
  await expect(page.getByRole('button', {name: '切换实例'})).toBeVisible()
  await page.unroute('https://api.yppp.net/api.php')
  await page.route('https://api.yppp.net/api.php', route => route.abort())
  await page.reload()
  await expect(page.locator('.wallpaper img')).toHaveCount(0)
  await expect(page.getByRole('heading', {name: 'demo-main', exact: true})).toBeVisible()
})

test('总览三态、资源搭配记忆、日志与被动截图切换', async ({page}) => {
  const methods: string[] = []
  page.on('websocket', socket => socket.on('framesent', frame => { methods.push(JSON.parse(String(frame.payload)).method) }))
  await page.goto('/#/i/demo-main/overview')
  await expect(page.getByLabel('搜索日志')).toHaveCount(0)
  await expect(page.locator('.primary-nav').getByRole('link', {name: '运行日志'})).toHaveCount(0)
  await page.getByRole('button', {name: '仪表盘设置', exact: true}).click()
  const settings = page.getByRole('dialog')
  await settings.getByRole('button', {name: '添加卡片', exact: true}).click()
  await settings.getByRole('button', {name: '行动力', exact: true}).click()
  const editorCards = settings.locator('.resource-editor-card:not(.resource-editor-add)')
  const source = await editorCards.last().boundingBox()
  const target = await editorCards.first().boundingBox()
  expect(source).not.toBeNull()
  expect(target).not.toBeNull()
  await page.mouse.move(source!.x + source!.width / 2, source!.y + source!.height / 2)
  await page.mouse.down()
  await page.mouse.move(target!.x + target!.width / 2, target!.y + target!.height / 2, {steps: 5})
  await page.mouse.up()
  await expect(editorCards.first()).toContainText('行动力')
  await settings.getByRole('button', {name: '关闭', exact: true}).click()
  await expect(page.locator('.resource-card')).toHaveCount(5)
  await expect(page.locator('.resource-card').first()).toContainText('行动力')
  const actionPoint = page.locator('.resource-card').filter({hasText: '行动力'})
  await expect(actionPoint.locator('.resource-heading')).toHaveText('行动力')
  await expect(actionPoint.locator('.resource-value')).toHaveText('101/ 5,301')
  await expect(actionPoint.locator('.resource-value small')).toHaveText('/ 5,301')
  await expect(actionPoint.locator('.resource-icon-image')).toHaveAttribute('src', /guild_coin\.webp/)
  await page.reload()
  await expect(page.locator('.resource-card')).toHaveCount(5)
  await page.getByRole('button', {name: '启动调度器', exact: true}).click()
  await expect(page.locator('.task-state.running')).toHaveCount(1)
  await expect(page.locator('.task-state.pending').first()).toBeVisible()
  await expect(page.locator('.task-state.waiting').first()).toBeVisible()
  await page.getByRole('tab', {name: '截图', exact: true}).click()
  await expect(page.getByAltText('任务最近一次截图')).toBeVisible({timeout: 10000})
  expect(methods).not.toContain('preview.capture')
  await page.screenshot({path: 'test-results/overview-preview-new.png', fullPage: true})
  await page.getByRole('tab', {name: '日志', exact: true}).click()
  const logContent = page.getByLabel('日志内容')
  await logContent.evaluate(element => { element.setAttribute('style', 'flex: 0 0 24px; height: 24px; min-height: 0') })
  await expect.poll(() => logContent.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true)
  await logContent.evaluate(element => { element.scrollTop = 0 })
  await expect.poll(() => logContent.evaluate(element => element.scrollTop + element.clientHeight >= element.scrollHeight - 1), {timeout: 5000}).toBe(true)
  await page.getByRole('button', {name: '展开日志筛选'}).click()
  await page.getByLabel('搜索日志').fill('模拟调度器已启动')
  await expect(page.locator('.log-line')).toHaveCount(1)
  await page.getByRole('button', {name: '停止运行', exact: true}).click()
  await page.getByLabel('搜索日志').fill('')
  await page.screenshot({path: 'test-results/overview-logs-new.png', fullPage: true})
  await page.goto('/#/i/demo-main/task/Main')
  await expect(page.locator('[id="Main.Emotion.Fleet1Record"]')).toHaveValue('2026-09-12 23:45:12.123456')
  await expect(page.locator('[id="Main.Emotion.Fleet1Record"]')).toHaveAttribute('readonly', '')
})

test('资源数值按可用宽度缩放并保持当前值与上限在同一行', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.resources.demo-main', JSON.stringify(['Oil', 'Coin', 'Gem', 'Cube', 'Pt', 'ActionPoint', 'YellowCoin', 'PurpleCoin', 'Core', 'Medal', 'Merit', 'GuildCoin']))
    if (!localStorage.getItem('azurpilot.theme')) localStorage.setItem('azurpilot.theme', 'legacy-light')
  })
  await page.setViewportSize({width: 1996, height: 900})
  await page.goto('/#/i/demo-main/overview')
  const values = page.locator('.resource-value')
  await expect(values).toHaveCount(12)
  const coin = page.locator('.resource-card').filter({hasText: '物资'}).locator('.resource-value-content')
  await expect(coin).toHaveText('186,420/ 600,000')
  const assertFits = async () => {
    await expect.poll(() => values.evaluateAll(elements => elements.every(element => {
      const content = element.querySelector('.resource-value-content')!
      const primary = content.querySelector('span')!
      const suffix = content.querySelector('small')
      const box = content.getBoundingClientRect()
      return box.width <= element.clientWidth + .5
        && (!suffix || (suffix.getClientRects().length === 1
          && suffix.getBoundingClientRect().top < primary.getBoundingClientRect().bottom
          && parseFloat(getComputedStyle(suffix).fontSize) < parseFloat(getComputedStyle(primary).fontSize)))
    }))).toBe(true)
  }
  await assertFits()
  await expect.poll(() => coin.evaluate(element => parseFloat(getComputedStyle(element).fontSize) < parseFloat(getComputedStyle(element.parentElement!).fontSize))).toBe(true)
  await page.locator('.resource-grid').screenshot({path: 'test-results/resource-values-desktop.png'})
  await page.setViewportSize({width: 390, height: 844})
  await page.evaluate(() => localStorage.setItem('azurpilot.theme', 'light'))
  await page.reload()
  await expect(values).toHaveCount(12)
  await assertFits()
  await page.locator('.resource-grid').screenshot({path: 'test-results/resource-values-mobile.png'})
  // 宽度恢复后应还原主题字号，避免只缩小不放大。
  await page.setViewportSize({width: 3000, height: 1000})
  await assertFits()
  await expect.poll(() => coin.evaluate(element => getComputedStyle(element).fontSize === getComputedStyle(element.parentElement!).fontSize)).toBe(true)
  expect(errors).toEqual([])
})

for (const theme of ['minimal', 'legacy-light', 'legacy-dark', 'extreme'] as const) {
  test(`${theme} 窄屏总览与统计内容完整可访问`, async ({page}) => {
    test.setTimeout(60000)
    await page.addInitScript(value => localStorage.setItem('azurpilot.theme', value), theme)
    await page.setViewportSize({width: 550, height: 1000})
    await page.goto('/#/i/demo-main/overview')
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    const legacy = theme.startsWith('legacy-')
    await expect(page.locator('.resource-card')).toHaveCount(4)
    await expect.poll(() => page.locator('main').evaluate(element => element.clientHeight)).toBeGreaterThan(500)
    if (!legacy) await page.getByRole('button', {name: '打开调度与任务', exact: true}).click()
    await page.getByRole('button', {name: '启动调度器', exact: true}).click()
    if (!legacy) await page.locator('.right-rail').getByRole('button', {name: '关闭调度与任务', exact: true}).click()
    try {
      await page.getByRole('tab', {name: '截图', exact: true}).click()
      const preview = page.getByAltText('任务最近一次截图')
      await expect(preview).toBeVisible({timeout: 10000})
      for (const width of [900, 550, 390]) {
        await page.setViewportSize({width, height: 1000})
        await preview.scrollIntoViewIfNeeded()
        await expect(preview).toBeInViewport({ratio: .95})
        expect((await preview.boundingBox())!.height).toBeGreaterThan(100)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      }
      await page.screenshot({path: `test-results/narrow-${theme}-overview.png`, fullPage: true})
    } finally {
      if (!legacy) await page.getByRole('button', {name: '打开调度与任务', exact: true}).click()
      await page.getByRole('button', {name: '停止运行', exact: true}).click()
      if (!legacy) await page.locator('.right-rail').getByRole('button', {name: '关闭调度与任务', exact: true}).click()
    }

    await page.goto('/#/i/demo-main/statistics')
    for (const width of [900, 550, 390]) {
      await page.setViewportSize({width, height: 1000})
      await page.getByRole('button', {name: '打开导航', exact: true}).click()
      await expect(page.locator('.sidebar')).toBeInViewport({ratio: .95})
      await page.getByRole('button', {name: '关闭导航', exact: true}).click()
      if (!legacy) {
        await page.getByRole('button', {name: '打开调度与任务', exact: true}).click()
        await expect(page.locator('.right-rail')).toBeInViewport({ratio: .95})
        await page.locator('.right-rail').getByRole('button', {name: '关闭调度与任务', exact: true}).click()
      }
      for (const category of ['资源趋势', '大世界趋势', '短猫掉落']) {
        const picker = page.getByRole('combobox', {name: '统计分类', exact: true})
        if (await picker.isVisible()) {
          await picker.click()
          await page.getByRole('option', {name: category, exact: true}).click()
        } else {
          await page.getByRole('tab', {name: category, exact: true}).click()
        }
        const content = page.locator(category === '短猫掉落' ? '.statistics-table' : '.chart-canvas').first()
        await expect(content).toBeVisible()
        await content.scrollIntoViewIfNeeded()
        await expect(content).toBeInViewport({ratio: .95})
        await expect.poll(() => page.locator('.statistics-sections').evaluate(element => element.clientHeight)).toBeGreaterThan(200)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      }
    }
    await page.screenshot({path: `test-results/narrow-${theme}-statistics.png`, fullPage: true})
  })
}

test('任务二级菜单通过顶层浮层覆盖资源卡片', async ({page}) => {
  await page.setViewportSize({width: 1134, height: 669})
  await page.addInitScript(() => localStorage.setItem('azurpilot.resources.demo-main', JSON.stringify(['Oil', 'ActionPoint'])))
  await page.goto('/#/i/demo-main/overview')
  await page.locator('.task-group-button').filter({hasText: '系统'}).click()
  const flyout = page.locator('.task-submenu-flyout')
  await expect(flyout).toBeVisible()
  await expect(flyout).toHaveCSS('position', 'fixed')
  await expect(flyout).toHaveCSS('z-index', '100')
  await expect(flyout).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await expect(flyout).toHaveCSS('backdrop-filter', 'none')
  expect(await flyout.evaluate(element => element.parentElement === document.body)).toBe(true)

  const overlap = await flyout.evaluate(element => {
    const flyoutRect = element.getBoundingClientRect()
    const card = [...document.querySelectorAll<HTMLElement>('.resource-card')].find(candidate => {
      const rect = candidate.getBoundingClientRect()
      return Math.max(flyoutRect.left, rect.left) < Math.min(flyoutRect.right, rect.right) && Math.max(flyoutRect.top, rect.top) < Math.min(flyoutRect.bottom, rect.bottom)
    })
    if (!card) return {found: false, onTop: false}
    const cardRect = card.getBoundingClientRect()
    const x = (Math.max(flyoutRect.left, cardRect.left) + Math.min(flyoutRect.right, cardRect.right)) / 2
    const y = (Math.max(flyoutRect.top, cardRect.top) + Math.min(flyoutRect.bottom, cardRect.bottom)) / 2
    return {found: true, onTop: !!document.elementFromPoint(x, y) && element.contains(document.elementFromPoint(x, y))}
  })
  expect(overlap).toEqual({found: true, onTop: true})
  await page.screenshot({path: 'test-results/task-submenu-resource-overlay.png', fullPage: true, animations: 'disabled'})
})

test('舰队扫描和半自动工具在当前页面显示运行日志', async ({page}) => {
  for (const {instance, task, title} of [
    {instance: 'demo-main', task: 'FleetScan', title: '舰队扫描'},
    {instance: 'demo-alt', task: 'Daemon', title: '半自动点击'},
  ]) {
    const path = `/#/i/${instance}/task/${task}`
    await page.goto(path)

    const heading = page.locator('.page-title h1')
    const logs = page.getByLabel('日志内容')
    await expect(heading).toHaveAccessibleName(title)
    await expect(logs).toBeVisible()
    expect((await logs.boundingBox())!.y).toBeGreaterThan((await heading.boundingBox())!.y)

    await page.getByRole('button', {name: '运行工具', exact: true}).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    let running = false
    try {
      await dialog.getByRole('button', {name: '确认运行', exact: true}).click()
      running = true
      await expect(page).toHaveURL(new RegExp(`/i/${instance}/task/${task}$`))
      await expect(logs).toContainText('模拟调度器已启动')
      if (task === 'FleetScan') await page.screenshot({path: 'test-results/tool-run-log.png', fullPage: true})
    } finally {
      if (running) {
        const stop = page.getByRole('button', {name: '停止运行', exact: true})
        await expect(stop).toBeVisible()
        await stop.click()
        await expect(page.getByRole('button', {name: '启动调度器', exact: true})).toBeVisible()
      }
    }
  }
})

test('分段滑块首屏静止，交互后平移并尊重减少动态效果', async ({page}) => {
  await page.addInitScript(() => {
    document.addEventListener('transitionrun', event => {
      if (event.target instanceof Element && event.target.matches('.segmented-indicator')) {
        const root = document.documentElement
        root.dataset.segmentTransitions = String(Number(root.dataset.segmentTransitions ?? 0) + 1)
      }
    })
  })
  await page.goto('/#/i/demo-main/statistics')
  await expect(page.getByRole('img', {name: '石油交互趋势图'})).toBeVisible()
  const tabs = page.getByRole('tablist', {name: '统计分类'})
  const transitions = () => page.evaluate(() => Number(document.documentElement.dataset.segmentTransitions ?? 0))
  expect(await transitions()).toBe(0)
  await tabs.screenshot({path: 'test-results/segmented-statistics-light.png'})
  await tabs.getByRole('tab', {name: '委托收益', exact: true}).click()
  await expect.poll(transitions).toBeGreaterThan(0)
  await expect(page.locator('.period-controls strong')).toHaveText('委托收益')
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'))
  await expect(tabs).toHaveCSS('background-color', 'rgba(37, 37, 41, 0.78)')
  await expect(tabs.getByRole('tab', {name: '委托收益', exact: true})).toHaveCSS('color', 'rgb(245, 245, 247)')
  await tabs.screenshot({path: 'test-results/segmented-statistics-dark.png'})
  await page.emulateMedia({reducedMotion: 'reduce'})
  const before = await transitions()
  await tabs.getByRole('tab', {name: '大世界总结', exact: true}).click()
  await expect(page.locator('.period-controls strong')).toHaveText('大世界总结')
  expect(await transitions()).toBe(before)
  await expect(tabs.locator('.segmented-indicator')).toHaveCSS('transition-duration', '0s')
})

test('统计与监控复用分段控件的样式及键盘切换', async ({page}) => {
  await page.goto('/#/i/demo-main/overview')
  const monitor = page.getByRole('tablist', {name: '监控视图'})
  await expect(monitor).toBeVisible()
  await monitor.screenshot({path: 'test-results/segmented-monitor-light.png'})
  const appearance = await monitor.evaluate(control => {
    const style = getComputedStyle(control)
    return [style.backgroundColor, style.borderColor, style.borderRadius, control.querySelector('button')!.getBoundingClientRect().height]
  })
  await monitor.getByRole('tab', {name: '日志', exact: true}).focus()
  await page.keyboard.press('ArrowRight')
  await expect(monitor.getByRole('tab', {name: '截图', exact: true})).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.preview-screen')).toBeVisible()
  await page.keyboard.press('ArrowLeft')
  await expect(monitor.getByRole('tab', {name: '日志', exact: true})).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.preview-screen')).toBeHidden()
  await page.goto('/#/i/demo-main/statistics')
  const statistics = page.getByRole('tablist', {name: '统计分类'})
  await expect(statistics).toBeVisible()
  expect(await statistics.evaluate(control => {
    // 分类栏的控件面绘制在伪元素上，元素本体为透明背景。
    const style = getComputedStyle(control, '::after')
    return [style.backgroundColor, style.borderColor, style.borderRadius, control.querySelector('button')!.getBoundingClientRect().height]
  })).toEqual(appearance)
})

test('大世界掉落展示新增研发材料、实验计划与突破部件', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.language', 'zh-CN'))
  await page.goto('/#/i/demo-main/statistics')
  await page.getByRole('tablist', {name: '统计分类'}).getByRole('tab', {name: '大世界掉落', exact: true}).click()
  const items = [
    ['GearDesignPlanGunT4', '舰炮研发图纸SSR型'],
    ['GearDesignPlanTorpedoT4', '鱼雷研发图纸SSR型'],
    ['GearDesignPlanAntiAirT4', '防空炮研发图纸SSR型'],
    ['GearDesignPlanPlaneT4', '舰载机研发图纸SSR型'],
    ['Ultra_High_Purity_Metals', '特种钢材'],
    ['Military_Grade_Electronic_Components', '军工级电子元件'],
    ['HBX_Blend_Gunpowder', 'HBX炸药'],
    ['High_Durability_Elastomers', '氟橡胶'],
    ['Superconductive_Metals', '超导铜'],
    ['Corrosion_Resistant_Alloys', '钛合金'],
    ['OrdnanceTestingReportT4', '机密实验计划'],
    ['OrdnanceTestingReportT5', '绝密实验计划'],
    ['PrototypeGearPartsT5', '特装型突破部件'],
  ]
  for (const [key, name] of items) {
    const card = page.locator('.summary-metrics').getByText(name, {exact: true})
    await expect(card).toBeVisible()
    const response = await page.request.get(`/opsi-items/${key}.png`)
    expect(response.ok(), key).toBe(true)
    const icon = page.locator(`.summary-metrics img[src="/opsi-items/${key}.png"]`)
    await expect.poll(() => icon.evaluate(image => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  }
  const detail = page.locator('.statistics-table').filter({has: page.getByRole('heading', {name: '大世界掉落明细', exact: true})})
  await expect(detail).toContainText('六种金色研发材料')
  await page.screenshot({path: 'test-results/opsi-requested-items.png', fullPage: true})
  await page.setViewportSize({width: 390, height: 844})
  await page.getByRole('button', {name: '打开导航', exact: true}).waitFor()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({path: 'test-results/opsi-requested-items-mobile.png', fullPage: true})
})

test('统计分类、K 线、时间过滤、表格导出与移动端布局', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/#/i/demo-main/statistics')
  await expect(page.getByRole('img', {name: '石油交互趋势图'})).toBeVisible()
  const rawTable = page.locator('[data-card-key="resources:raw"] .statistics-table')
  const rawRecords = rawTable.locator('tbody tr')
  const recordTime = async (row: ReturnType<typeof rawRecords.first>) => Date.parse((await row.locator('td').first().innerText()).replace(' ', 'T'))
  await expect(rawRecords).toHaveCount(24)
  expect(await recordTime(rawRecords.first())).toBeGreaterThan(await recordTime(rawRecords.last()))
  const timeColumn = rawTable.locator('th').first()
  await expect(timeColumn).toHaveAttribute('aria-sort', 'descending')
  await timeColumn.getByRole('button').click()
  await expect(timeColumn).toHaveAttribute('aria-sort', 'ascending')
  expect(await recordTime(rawRecords.first())).toBeLessThan(await recordTime(rawRecords.last()))
  await page.getByRole('combobox', {name: '图表类型', exact: true}).click()
  await page.getByRole('option', {name: 'K 线（开高低收）', exact: true}).click()
  await page.getByRole('combobox', {name: '采样粒度', exact: true}).click()
  await page.getByRole('option', {name: '每小时', exact: true}).last().click()
  await page.screenshot({path: 'test-results/statistics-candlestick.png', fullPage: true})
  const download = page.waitForEvent('download')
  await page.getByRole('button', {name: '导出本类数据'}).click()
  expect((await download).suggestedFilename()).toMatch(/\.csv$/)
  for (const label of ['大世界趋势', '大世界总结', '委托收益', '舰船经验', '大世界掉落']) {
    await page.getByRole('tablist', {name: '统计分类'}).getByRole('tab', {name: label, exact: true}).click()
    await expect(page.locator('.period-controls strong')).toHaveText(label)
  }
  await page.getByRole('tab', {name: '资源趋势', exact: true}).click()
  await page.getByLabel('起始时间').fill('2099-01-01T00:00')
  await expect(page.getByText('这段时间没有有效记录')).toBeVisible()
  await page.getByRole('button', {name: '全部时间', exact: true}).click()
  await page.getByRole('combobox', {name: '图表类型', exact: true}).click()
  await page.getByRole('option', {name: 'K 线（开高低收）', exact: true}).click()
  await page.screenshot({path: 'test-results/statistics-resources-new.png', fullPage: true})
  await page.setViewportSize({width: 390, height: 844})
  const picker = page.getByRole('combobox', {name: '统计分类', exact: true})
  await expect(picker).toBeVisible()
  await picker.focus()
  await page.keyboard.press('End')
  await page.keyboard.press('Enter')
  await expect(picker).toHaveText('仓库物品')
  await picker.click()
  await page.getByRole('option', {name: '科研掉落', exact: true}).click()
  await expect(page.locator('.period-controls strong')).toHaveText('科研掉落')
  await picker.focus()
  await page.keyboard.press('Home')
  await page.keyboard.press('Enter')
  await expect(picker).toHaveText('资源趋势')
  await expect(page.getByRole('img', {name: '石油交互趋势图'})).toBeVisible()
  await page.screenshot({path: 'test-results/statistics-mobile-new.png', fullPage: true})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(errors).toEqual([])
})

test('下拉切换实例、创建入口与实例隔离', async ({page}) => {
  await page.goto('/#/i/demo-main/task/Alas')
  const serial = page.locator('[id="Alas.Emulator.Serial"]')
  await expect(serial).toHaveValue('127.0.0.1:5555')
  await expect(page.locator('.rail')).toHaveCount(0)
  await expect(page.locator('.primary-nav').getByRole('link', {name: '系统设置'})).toHaveCount(0)
  await expect(page.getByRole('button', {name: /保存/})).toHaveCount(0)
  await expect(page.getByRole('button', {name: '撤销修改'})).toHaveCount(0)
  await page.getByRole('button', {name: '切换实例'}).click()
  await page.getByRole('menuitemradio', {name: 'demo-alt', exact: true}).click()
  await expect(page).toHaveURL(/demo-alt\/task\/Alas/)
  await page.goto('/#/i/demo-alt/task/Alas')
  await expect(serial).toHaveValue('127.0.0.1:5557')
  await page.getByRole('button', {name: '切换实例'}).click()
  await page.keyboard.press('End')
  await expect(page.getByRole('menuitem', {name: '创建实例'})).toBeFocused()
  await page.keyboard.press('Enter')
  const name = `mock_${Date.now()}`
  await page.getByRole('dialog').getByLabel('实例名称', {exact: true}).fill(name)
  await page.getByRole('dialog').getByRole('button', {name: '创建实例', exact: true}).click()
  await expect(page).toHaveURL(new RegExp(`${name}/task/Alas`))
  await expect(serial).toBeVisible()
})

test('配置字体、多行输入与 YAML 编辑实时保存及主题颜色', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/#/i/demo-main/task/Alas')
  const editor = page.locator('[id="Alas.Error.OnePushConfig"]')
  await expect(editor).toBeVisible()
  await expect(page.locator('.field-label small')).toHaveCount(0)
  expect(await page.locator('.field-label label').first().evaluate(node => parseFloat(getComputedStyle(node).fontSize))).toBeGreaterThanOrEqual(14)
  expect(await page.locator('html').evaluate(node => getComputedStyle(node).zoom || '1')).toBe('1')
  const row = editor.locator('xpath=ancestor::div[contains(@class,"field-row")]')
  const label = await row.locator('.field-label').boundingBox()
  const input = await row.locator('.field-control').boundingBox()
  expect(input!.y).toBeGreaterThan(label!.y + label!.height)
  expect(input!.width).toBeGreaterThan(500)
  const yaml = '# 通知配置\nprovider: null\nretry: 3\nenabled: true\nmessage: "测试颜色"'
  await editor.fill(yaml)
  await page.waitForTimeout(500)
  await page.reload()
  await expect(editor).toHaveText(yaml.replaceAll('\n', ''))
  const token = editor.locator('span').filter({hasText: /^provider$/}).first()
  const lightColor = await token.evaluate(node => getComputedStyle(node).color)
  await row.scrollIntoViewIfNeeded()
  await page.screenshot({path: 'test-results/yaml-light.png'})
  await page.goto('/#/interface')
  await page.getByRole('combobox', {name: '界面主题', exact: true}).click()
  await page.getByRole('option', {name: '深色', exact: true}).click()
  await page.goto('/#/i/demo-main/task/Alas')
  await expect(editor).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  expect(await token.evaluate(node => getComputedStyle(node).color)).not.toBe(lightColor)
  await row.scrollIntoViewIfNeeded()
  await page.screenshot({path: 'test-results/yaml-dark.png'})
  const textarea = page.locator('textarea').first()
  await expect(textarea).toBeVisible()
  expect((await textarea.boundingBox())!.height).toBeLessThan(80)
  expect(errors).toEqual([])
})


test('输入框随内容和宽度变化增高，删除后缩回单行', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/#/i/demo-alt/task/Alas')
  const input = page.locator('textarea').first()
  await expect(input).toBeVisible()
  await input.fill('单行')
  const single = (await input.boundingBox())!.height
  expect(single).toBeLessThan(80)
  await input.fill('第一行\n第二行\n第三行\n第四行')
  expect((await input.boundingBox())!.height).toBeGreaterThan(single + 70)
  await input.fill('单行')
  expect((await input.boundingBox())!.height).toBeCloseTo(single, 0)
  await input.fill('宽度变化会触发重新计算高度。'.repeat(25))
  const wide = (await input.boundingBox())!.height
  await page.setViewportSize({width: 390, height: 844})
  await expect.poll(async () => (await input.boundingBox())!.height).toBeGreaterThan(wide)
  await input.fill('单行')
  const mobileSingle = (await input.boundingBox())!.height
  expect(mobileSingle).toBeLessThan(80)
  await input.fill('')
  expect((await input.boundingBox())!.height).toBeCloseTo(mobileSingle, 0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.setViewportSize({width: 1440, height: 1100})
  const yaml = page.locator('[id="Alas.Error.OnePushConfig"]')
  const scroller = yaml.locator('xpath=ancestor::div[contains(@class,"cm-scroller")]')
  const yamlSingle = (await scroller.boundingBox())!.height
  expect(yamlSingle).toBeLessThan(80)
  await yaml.fill('provider: null\nretry: 3\nenabled: true\nmessage: 测试')
  expect((await scroller.boundingBox())!.height).toBeGreaterThan(yamlSingle + 70)
  await yaml.fill('provider: null')
  expect((await scroller.boundingBox())!.height).toBeCloseTo(yamlSingle, 0)
  expect(errors).toEqual([])
})

test('存储空间为空时隐藏，有状态时显示完整 JSON 并可清除', async ({page}) => {
  await page.goto('/#/i/demo-alt/task/Alas')
  await expect(page.locator('textarea').first()).toBeVisible()
  await expect(page.locator('#group-Storage')).toHaveCount(0)
  await expect(page.locator('.group-nav').getByRole('link', {name: '任务状态'})).toHaveCount(0)
  await page.getByRole('textbox', {name: '搜索配置项', exact: true}).fill('Storage.Storage')
  await expect(page.getByText('没有找到配置项')).toBeVisible()
  await page.goto('/#/i/demo-error/task/Alas')
  await page.getByRole('textbox', {name: '搜索配置项', exact: true}).fill('')
  const storage = page.getByLabel('存储空间内容')
  await expect(storage).toBeVisible()
  expect(JSON.parse(await storage.innerText())).toEqual({failureCount: 3, lastError: '模拟器连接失败', retry: {enabled: false, remaining: 0}, tasks: ['Commission', 'Research']})
  await expect(storage).not.toContainText('[object Object]')
  const serial = page.locator('[id="Alas.Emulator.Serial"]')
  await serial.fill('保留其他字段的更改')
  await page.locator('#group-Storage').scrollIntoViewIfNeeded()
  await page.screenshot({path: 'test-results/storage-state.png', animations: 'disabled'})
  await page.getByRole('button', {name: '清除存储空间'}).click()
  await expect(page.locator('#group-Storage')).toHaveCount(0)
  await expect(page.locator('.group-nav').getByRole('link', {name: '任务状态'})).toHaveCount(0)
  await expect(serial).toHaveValue('保留其他字段的更改')
  await page.reload()
  await expect(page.locator('textarea').first()).toBeVisible()
  await expect(page.locator('#group-Storage')).toHaveCount(0)
})

test('侧栏任务计划随界面语言切换', async ({page}) => {
  await page.goto('/#/interface')
  await page.locator('#ui-language').click()
  await page.getByRole('option', {name: 'English', exact: true}).click()
  await page.goto('/#/i/demo-main/overview')
  await expect(page.locator('.rail-task-item[href$="/task/Commission"]')).toContainText('Commission')
  await expect(page.locator('.rail-task-item[href$="/task/Research"]')).toContainText('Research Lab')
})

test('语言偏好持久化，模拟启停、预览、统计和部署设置', async ({page}) => {
  await page.goto('/#/interface')
  await page.locator('#ui-language').click()
  await page.getByRole('option', {name: 'English', exact: true}).click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
  await page.reload()
  await expect(page.locator('#ui-language')).toHaveText('English')
  await expect(page.getByRole('heading', {name: 'Interface', exact: true})).toBeVisible()
  await expect(page.locator('.primary-nav').getByRole('link', {name: 'Updater', exact: true})).toBeVisible()
  await page.goto('/#/i/demo-main/task/Alas')
  await expect(page.locator('label[for="Alas.Emulator.Serial"]')).toContainText(/serial/i)
  await page.goto('/#/interface')
  await page.locator('#ui-language').click()
  await page.getByRole('option', {name: '简体中文', exact: true}).click()
  await page.goto('/#/remote')
  await page.getByLabel('监听端口').fill('23456')
  await page.waitForTimeout(500)
  await page.reload()
  await expect(page.getByLabel('监听端口')).toHaveValue('23456')
  await page.goto('/#/i/demo-main/overview')
  await page.getByRole('button', {name: '启动调度器'}).click()
  await expect(page.getByRole('button', {name: '停止运行'})).toBeVisible()
  await expect(page.locator('.log-content')).toContainText('模拟调度器已启动')
  await page.getByRole('tab', {name: '截图', exact: true}).click()
  await expect(page.getByRole('img', {name: '任务最近一次截图'})).toBeVisible()
  await page.screenshot({path: 'test-results/mock-overview.png', fullPage: true})
  await page.getByRole('button', {name: '停止运行'}).click()
  await page.locator('.primary-nav').getByRole('link', {name: '资源统计'}).click()
  await expect(page.getByRole('img', {name: /交互趋势图/})).toBeVisible()
})

test('移动端放大布局无横向溢出，单栏导航可以收起', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844})
  await page.goto('/#/i/demo-main/overview')
  await page.getByRole('button', {name: '切换实例'}).click()
  await page.getByRole('menuitemradio', {name: 'demo-alt', exact: true}).click()
  await expect(page.locator('.app-shell')).not.toHaveClass(/mobile-open/)
  await page.getByRole('button', {name: '打开导航'}).click()
  await page.getByRole('link', {name: 'AzurPilot 主页'}).click()
  await page.getByRole('button', {name: '打开导航'}).click()
  await page.locator('.primary-nav').getByRole('link', {name: '界面设置'}).click()
  await expect(page.getByLabel('界面主题')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({path: 'test-results/mock-mobile.png', fullPage: true, animations: 'disabled'})
})

test('窄窗口调度器入口位于左侧标题栏且可展开右栏', async ({page}) => {
  await page.setViewportSize({width: 950, height: 844})
  await page.goto('/#/i/demo-main/overview')
  const topbar = page.locator('.topbar')
  const toggle = page.getByRole('button', {name: '打开调度与任务'})
  await expect(toggle).toBeVisible()
  const [toggleBox, topbarBox] = await Promise.all([toggle.boundingBox(), topbar.boundingBox()])
  expect(toggleBox!.y).toBeGreaterThanOrEqual(topbarBox!.y)
  expect(toggleBox!.y + toggleBox!.height).toBeLessThanOrEqual(topbarBox!.y + topbarBox!.height)
  expect(toggleBox!.x + toggleBox!.width).toBeLessThanOrEqual(topbarBox!.x + topbarBox!.width / 2)
  await toggle.click()
  await expect(page.locator('.app-shell')).toHaveClass(/rail-open/)
  await expect(page.locator('.right-rail')).toBeVisible()
  await page.locator('.mobile-rail-toggle').click()
  await expect(page.locator('.app-shell')).not.toHaveClass(/rail-open/)
  await page.setViewportSize({width: 213, height: 500})
  await expect(page.locator('.breadcrumb')).toBeHidden()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.locator('.mobile-rail-toggle').click()
  await expect(page.locator('.right-rail')).toBeVisible()
  await page.locator('.right-rail').getByRole('button', {name: '关闭调度与任务'}).click()
  await expect(page.locator('.app-shell')).not.toHaveClass(/rail-open/)
  await page.setViewportSize({width: 951, height: 844})
  await expect(page.locator('.mobile-rail-toggle')).toBeHidden()
})


test('主页实例状态、任务搜索收起与导航固定', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByRole('heading', {name: /好，指挥官/})).toBeVisible()
  await expect(page.locator('.home-stats')).toContainText('全部实例')
  await expect(page.locator('.instance-card').filter({hasText: 'demo-main'})).toContainText('未运行')
  await expect(page.locator('.sidebar .instance-picker')).toHaveCount(0)
  await expect(page.locator('.sidebar-footer')).toHaveCount(0)
  await expect(page.locator('a.home-deck-link')).toHaveAttribute('href', 'https://github.com/wess09/AzurPilot')
  await expect(page.locator('.primary-nav .nav-open-source')).toHaveAttribute('href', 'https://github.com/wess09/AzurPilot')
  await page.locator('.home-legacy-toggle').click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'legacy-light')
  await page.locator('.home-legacy-toggle').click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.screenshot({path: 'test-results/home-desktop.png', fullPage: true})
  await page.locator('.instance-card').filter({hasText: 'demo-main'}).click()
  await expect(page.getByRole('heading', {name: 'demo-main', exact: true})).toBeVisible()
  await expect(page.getByLabel('搜索任务', {exact: true})).toHaveCount(0)
  await page.getByRole('button', {name: '展开任务搜索'}).click()
  await page.getByLabel('搜索任务', {exact: true}).fill('Alas')
  await expect(page.locator('.task-group-button')).toHaveCount(1)
  await page.getByRole('button', {name: '收起任务搜索'}).click()
  await expect(page.getByLabel('搜索任务', {exact: true})).toHaveCount(0)
  expect(await page.locator('.task-group-button').count()).toBeGreaterThan(1)
  await page.getByRole('button', {name: '启动调度器'}).click()
  await page.getByRole('link', {name: 'AzurPilot 主页'}).click()
  await expect(page.locator('.instance-card').filter({hasText: 'demo-main'})).toContainText('运行中')
  await expect(page.locator('.instance-card').filter({hasText: 'demo-main'})).toContainText('委托')
  await page.locator('.instance-card').filter({hasText: 'demo-main'}).click()
  await page.getByRole('button', {name: '停止运行'}).click()
  await page.goto('/#/i/demo-main/task/Alas')
  await expect(page.locator('[id="Alas.Emulator.Serial"]')).toBeVisible()
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
  // 顶栏吸顶：滚到底后仍贴住视口顶部且可见。
  const topbar = (await page.locator('.topbar').boundingBox())!
  expect(topbar.y).toBeLessThan(1)
  expect(topbar.y + topbar.height).toBeGreaterThan(0)
  await page.locator('.breadcrumb').getByRole('button', {name: '切换实例'}).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', {name: '切换实例'})).toBeFocused()
  expect(errors).toEqual([])
})

test('空实例主页仍可访问全局设置，系统设置不请求实例数据', async ({page}) => {
  const methods: string[] = []
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    const ids = new Set<string>()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      methods.push(request.method)
      if (request.method === 'instances.list') ids.add(request.id)
      server.send(message)
    })
    server.onMessage(message => {
      const result = JSON.parse(String(message))
      if (ids.has(result.id)) result.result = []
      if (result.topic === 'instances') result.data = []
      socket.send(JSON.stringify(result))
    })
  })
  await page.goto('/')
  await expect(page.getByRole('button', {name: '创建第一个实例'})).toBeVisible()
  await page.locator('.primary-nav').getByRole('link', {name: '系统设置'}).click()
  await expect(page.getByText('删除当前实例')).toHaveCount(0)
  await page.locator('.primary-nav').getByRole('link', {name: '界面设置'}).click()
  await expect(page.getByLabel('界面主题')).toBeVisible()
  expect(methods).not.toContain('startup.get')
  expect(methods).not.toContain('config.get')
  await page.setViewportSize({width: 390, height: 844})
  await page.goto('/')
  await page.screenshot({path: 'test-results/home-empty-mobile.png', fullPage: true})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('实例列表读取失败不阻塞全局设置', async ({page}) => {
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      if (request.method === 'instances.list') socket.send(JSON.stringify({v: 1, type: 'response', id: request.id, ok: false, error: {code: 'INTERNAL_ERROR', message: '测试实例读取失败'}}))
      else server.send(message)
    })
  })
  await page.goto('/#/interface')
  await expect(page.getByLabel('界面主题')).toBeVisible()
  await page.goto('/#/remote')
  await expect(page.getByLabel('监听端口')).toBeVisible()
})

test('启动开关在系统设置页保存，点名称不切换且保存后不回弹', async ({page}) => {
  await page.goto('/#/i/demo-main/task/Alas')
  const autoRun = page.getByLabel('启动时自动运行', {exact: true})
  const remember = page.getByLabel('启动时记忆运行', {exact: true})
  const before = await remember.getAttribute('aria-checked')
  await page.locator('.config-groups .field-name').nth(1).click()
  await expect(remember).toHaveAttribute('aria-checked', before!)
  await remember.check()
  await expect(page.locator('#instance-remember-status')).toHaveText('已保存')
  // 状态标记消失即队列已丢弃该条目，此后开关仍须显示服务端的值。
  await expect(page.locator('#instance-remember-status')).toHaveCount(0)
  await expect(remember).toHaveAttribute('aria-checked', 'true')
  await autoRun.check()
  await expect(page.locator('#instance-startup-status')).toHaveText('已保存')
})

test('仪表盘设置只含仪表盘项：无启动开关、无删除实例', async ({page}) => {
  await page.goto('/')
  await page.getByRole('button', {name: '新建实例'}).click()
  const name = `home_${Date.now()}`
  await page.getByLabel('实例名称').fill(name)
  await page.getByRole('dialog').getByRole('button', {name: '创建实例', exact: true}).click()
  await page.locator('.primary-nav').getByRole('link', {name: '运行总览', exact: true}).click()
  await page.getByRole('button', {name: '仪表盘设置'}).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('switch', {name: '卡片适应'})).toBeVisible()
  await expect(dialog.getByLabel('启动时自动运行', {exact: true})).toHaveCount(0)
  await expect(dialog.getByRole('button', {name: '删除实例', exact: true})).toHaveCount(0)
})

test('Logo 旁更新提示、完整提交分页、获取和应用更新', async ({page}) => {
  await page.goto('/')
  await expect(page.locator('.topbar-right').getByText('新版本可用')).toHaveCount(0)
  const updateNotice = page.locator('.sidebar-brand').getByRole('link', {name: '新版本可用'})
  await expect(updateNotice).toBeVisible()
  await expect(updateNotice).toHaveText('新')
  await updateNotice.click()
  await expect(page.getByRole('heading', {name: /^更新器/})).toBeVisible()
  await expect(page.locator('.head-card')).toHaveCount(2)
  await expect(page.locator('.commit-row')).toHaveCount(50)
  await expect(page.locator('.commit-ref')).toHaveCount(2)
  await page.getByText('展开详情', {exact: true}).click()
  await expect(page.locator('.commit-detail pre')).toContainText('统一全局设置和更新入口')
  await page.screenshot({path: 'test-results/updater-desktop.png', fullPage: true})
  await page.getByRole('button', {name: '下一页'}).click()
  await expect(page.locator('.commit-pagination')).toContainText('51–100 / 123')
  await page.getByRole('button', {name: '下一页'}).click()
  await expect(page.locator('.commit-row')).toHaveCount(23)
  await expect(page.getByRole('button', {name: '下一页'})).toBeDisabled()
  await page.getByRole('button', {name: '获取更新', exact: true}).click()
  await page.getByRole('button', {name: '更新', exact: true}).click()
  await expect(page.locator('.primary-nav .tiny-dot')).toHaveCount(0)
  await expect(page.locator('.update-summary')).toContainText('已是最新')
  await expect(page.locator('.commit-pagination')).toContainText('1–50 / 123')
  await page.setViewportSize({width: 390, height: 844})
  await page.screenshot({path: 'test-results/updater-mobile.png', fullPage: true})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.goto('/#/interface')
  await page.getByRole('combobox', {name: '界面主题', exact: true}).click()
  await page.getByRole('option', {name: '深色', exact: true}).click()
  await page.goto('/#/updater')
  await page.screenshot({path: 'test-results/updater-dark.png'})
})

test('SHA 不匹配警告与更新确认弹窗', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  // mock 服务切到分叉场景：本地 HEAD 不在更新源历史上，模拟镜像重写历史后的 SHA 分离。
  await fetch('http://127.0.0.1:22492/__mock/updater?mode=diverged')
  await page.goto('/#/updater')
  await expect(page.locator('.mismatch-note')).toContainText('SHA 不匹配')
  await page.getByRole('button', {name: '更新', exact: true}).click()
  await expect(page.locator('.modal h2')).toHaveText('SHA 不匹配')
  await expect(page.locator('.modal')).toContainText('GitCode')
  // 取消不更新：弹窗关闭且状态保持有更新可用。
  await page.locator('.modal').getByRole('button', {name: '取消', exact: true}).click()
  await expect(page.locator('.modal')).toHaveCount(0)
  await expect(page.locator('.update-summary')).toContainText('新版本可用')
  // 确认更新：本地对齐到更新源历史，状态回到已是最新。
  await page.getByRole('button', {name: '更新', exact: true}).click()
  await page.locator('.modal').getByRole('button', {name: '仍然更新'}).click()
  await expect(page.locator('.modal')).toHaveCount(0)
  await expect(page.locator('.update-summary')).toContainText('已是最新')
  await expect(page.locator('.mismatch-note')).toHaveCount(0)
  expect(errors).toEqual([])
  await fetch('http://127.0.0.1:22492/__mock/updater?mode=default')
})

test('指挥喵评分报告面板展示、刷新与空状态', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/#/i/demo-main/task/MeowfficerScore')
  const panel = page.locator('.meow-panel')
  await expect(panel).toBeVisible()
  await expect(panel.locator('.meow-summary')).toContainText('共 2 只')
  await expect(panel).toContainText('克雷喵')
  await expect(panel.locator('.meow-card').first().locator('.meow-tier').first()).toHaveText('准毕业')
  await expect(panel).toContainText('x + y = 1 + 6.0')
  await expect(panel.locator('.meow-talent.is-special').first()).toBeVisible()
  await expect(panel.locator('.meow-talent.is-inferred').first()).toBeVisible()
  await expect(panel).toContainText('评分口径来自公开攻略')
  await expect(panel.locator('details.meow-others').first()).toBeVisible()
  // 加权点制的雷暴口径不给 x/y：不渲染公式，改用后端给的 yLabel 说明命中行。
  const weighted = panel.locator('.meow-card').nth(1)
  await expect(weighted).toContainText('雷暴猫')
  await expect(weighted).toContainText('加权命中')
  await expect(weighted.locator('.meow-formula')).toHaveCount(0)
  // 自定义 yLabel 不能折行，且要与命中标签同一基线。
  const weightedAxis = weighted.locator('.meow-axis').last()
  expect(await weightedAxis.locator('.meow-axis-label').evaluate(node => node.getClientRects().length)).toBe(1)
  expect(await weightedAxis.evaluate(node => getComputedStyle(node).alignItems)).toBe('baseline')
  // 报告面板排在参数卡**下方**、日志**上方**：先看参数与运行入口，再看结果。
  await expect(page.locator('[id="MeowfficerScore.MeowfficerScore.Source"]')).toBeVisible()
  await expect(page.locator('.config-groups')).toContainText('评分来源')
  await expect(page.getByRole('button', {name: '运行工具', exact: true})).toBeVisible()
  await expect(page.getByLabel('日志内容')).toBeVisible()
  const configBox = await page.locator('.config-groups').boundingBox()
  const panelBox = await panel.boundingBox()
  const logBox = await page.locator('.tool-log-panel').boundingBox()
  expect(panelBox!.y).toBeGreaterThan(configBox!.y)
  expect(panelBox!.y + panelBox!.height).toBeLessThanOrEqual(logBox!.y + 1)
  // HTML 报告入口：有数据时给出新窗口链接。
  const reportLink = panel.getByRole('link', {name: '查看完整报告', exact: true})
  await expect(reportLink).toHaveAttribute('href', '/reports/meowfficer_score')
  await expect(reportLink).toHaveAttribute('target', '_blank')
  await panel.getByRole('button', {name: '刷新', exact: true}).click()
  await expect(panel).toContainText('克雷喵')
  await page.screenshot({path: 'test-results/meowfficer-score.png', fullPage: true, animations: 'disabled'})
  // 未跑过任务时后端返回 NOT_FOUND，页面显示空状态而不是错误，也不给报告入口（会 404）。
  await page.goto('/#/i/demo-alt/task/MeowfficerScore')
  await expect(page.locator('.meow-panel')).toContainText('还没跑过评分任务')
  await expect(page.locator('.meow-panel').getByRole('link', {name: '查看完整报告', exact: true})).toHaveCount(0)
  expect(errors).toEqual([])
})

/* 材质细节按画布叠加层分四档：切层只列该层的旋钮，滑块只认真实变化。 */
test('材质细节四层接线：逐层可调，重复值不落盘', async ({page}) => {
  await page.emulateMedia({reducedMotion: 'reduce'})
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'glass')
    localStorage.removeItem('azurpilot.custom.new')
  })
  await page.goto('/#/i/demo-main/statistics')
  await page.locator('.material-quick-button').click()
  const scopes = page.locator('.material-detail-scope button')
  await expect(scopes).toHaveCount(4)
  await expect(scopes.nth(3)).toHaveText('控件')

  const stored = () => page.evaluate(() => localStorage.getItem('azurpilot.custom.new'))

  /* 一级面：页标题动作区里那份通用玻璃取 --theme-surface-filter。 */
  const surfaceFilter = () => page.locator('.title-actions .glass-material').first().evaluate(el => getComputedStyle(el).backdropFilter)
  const surfaceToken = () => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--theme-surface-filter'))
  await scopes.nth(0).click()
  const blur = page.locator('[id="ui-knob-surface.blur"]')
  await blur.focus()
  const before = await surfaceFilter()
  const tokenBefore = await surfaceToken()
  await page.keyboard.press('ArrowRight')
  await expect.poll(stored).toContain('surface.blur')
  expect(await surfaceFilter()).not.toBe(before)
  expect(await surfaceToken()).not.toBe(tokenBefore)

  /* 值没变就不落盘：合成事件带相同值应被忽略，带新值才写入。 */
  const unchanged = await stored()
  const dispatch = (value: string) => page.evaluate(next => {
    const el = document.getElementById('ui-knob-surface.blur') as HTMLInputElement
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    setter.call(el, next)
    el.dispatchEvent(new Event('change', {bubbles: true}))
  }, value)
  await dispatch(await blur.inputValue())
  await page.waitForTimeout(200)
  expect(await stored()).toBe(unchanged)
  await dispatch(String(Number(await blur.inputValue()) + 2))
  await expect.poll(stored).not.toBe(unchanged)

  /* 只有二级贴片带圆角旋钮；切到别层它不再渲染。 */
  await scopes.nth(1).click()
  await expect(page.locator('[id="ui-knob-surface.blur"]')).toHaveCount(0)
  const plateRadius = page.locator('[id="ui-knob-plate.radius"]')
  await expect(plateRadius).toBeVisible()
  const controlsRadius = () => page.locator('.statistics-controls').first().evaluate(el => getComputedStyle(el).borderRadius)
  const radiusBefore = await controlsRadius()
  await plateRadius.focus()
  await page.keyboard.press('ArrowRight')
  await expect.poll(stored).toContain('plate.radius')
  expect(await controlsRadius()).not.toBe(radiusBefore)

  /* 作用域那一行整宽：四层的按钮不得溢出弹窗。 */
  const overflow = await page.evaluate(() => {
    const modal = document.querySelector('.material-detail-modal')!
    const scope = modal.querySelector('.material-detail-scope')!
    return Math.round(scope.getBoundingClientRect().right - modal.getBoundingClientRect().right)
  })
  expect(overflow).toBeLessThanOrEqual(0)
})


for (const category of ['opsi', 'action', 'ships', 'loot', 'resources']) {
  test(`统计 ${category} 保持展示并提供文件导出入口`, async ({page}) => {
    await page.emulateMedia({reducedMotion: 'reduce'})
    await page.addInitScript(category => {
      localStorage.setItem('azurpilot.theme', 'light')
      localStorage.setItem('azurpilot.statistics', JSON.stringify({category}))
    }, category)
    await page.goto('/#/i/demo-main/statistics')
    await expect(page.getByRole('button', {name: '刷新统计', exact: true}).first()).toBeVisible()
    await expect(page.getByRole('button', {name: /导出/}).first()).toBeVisible()
    await expect(page.locator('.statistics-metrics, .statistics-table, .statistics-chart').first()).toBeVisible()
    if (category === 'opsi') await page.screenshot({path: test.info().outputPath('opsi-v2-page.png'), fullPage: true})
  })
}

test('仓库分类继续提供原有文件导出', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.statistics', JSON.stringify({category: 'storage'})))
  await page.goto('/#/i/demo-main/statistics')
  await expect(page.getByRole('button', {name: /导出/}).first()).toBeVisible()
})


test('商店配置只显示官源购买设置并保留普通过滤器保存', async ({page}) => {
  for (const task of ['EventShop', 'ShopFrequent', 'ShopOnce', 'PrivateQuarters', 'OpsiShop', 'OpsiVoucher']) {
    await page.goto(`/#/i/demo-main/task/${task}`)
    await expect(page.locator('.config-group').first()).toBeVisible()
    await expect(page.locator('[id="group-ShopAdvanced"]')).toHaveCount(0)
    await expect(page.locator('.restricted-lua-editor')).toHaveCount(0)
  }
  await page.goto('/#/i/demo-main/task/EventShop')
  const filter = page.locator('[id="EventShop.EventShop.CustomFilter"]')
  await filter.fill('Cube > Oil')
  await filter.blur()
  await expect(page.locator('[id="EventShop.EventShop.CustomFilter-status"]')).toContainText('已保存')
  await page.reload()
  await expect(filter).toHaveValue('Cube > Oil')
  await page.setViewportSize({width: 390, height: 844})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  const close = page.locator('.mobile-close')
  if (await close.isVisible()) await close.click()
  await filter.scrollIntoViewIfNeeded()
  await expect(filter).toBeInViewport()
  await page.screenshot({path: 'test-results/shop-upstream-mobile.png', fullPage: true})
})

test('关闭背景后切回填写 URL 直接铺上，不必再点应用背景', async ({page}) => {
  await page.route('https://api.yppp.net/api.php', route => route.fulfill({
    contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#9acbff"/></svg>',
  }))
  /* 「关闭背景」档只在普通材质出现。 */
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'plain')
  })
  await page.goto('/#/interface')
  const source = page.locator('#ui-background-source')
  await source.click()
  await page.getByRole('option', {name: '填写 URL', exact: true}).click()
  await expect(page.locator('.wallpaper img')).toBeVisible()
  await source.click()
  await page.getByRole('option', {name: '关闭背景', exact: true}).click()
  await expect(page.locator('.wallpaper img')).toHaveCount(0)
  await source.click()
  await page.getByRole('option', {name: '填写 URL', exact: true}).click()
  await expect(page.locator('.wallpaper img')).toBeVisible()
})

test('舰船数据四页直接导航，扫描控件只在扫描更新页', async ({page}) => {
  const requests: string[] = [], tasks: string[] = []
  page.on('websocket', socket => socket.on('framesent', ({payload}) => {
    const request = JSON.parse(String(payload)); if (request.type !== 'request') return
    requests.push(request.method); if (request.method === 'tasks.run') tasks.push(request.params.task)
  }))
  await page.addInitScript(() => {localStorage.setItem('azurpilot.language', 'zh-CN'); localStorage.setItem('azurpilot.theme', 'light')})
  await page.goto('/#/i/demo-main/task/FleetAnalysis?tab=mind')
  await expect(page).toHaveURL(/task\/FleetAnalysis\?tab=mind/)
  await expect(page.getByRole('tab')).toHaveCount(4)
  await expect(page.getByRole('tab', {name: '养成计算', exact: true})).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('button', {name: '扫描船坞', exact: true})).toHaveCount(0)
  await expect(page.locator('input[type=file]')).toHaveCount(0)
  await page.getByRole('tab', {name: '舰队科技', exact: true}).click()
  await expect(page).toHaveURL(/task\/FleetAnalysis\?tab=technology/)
  await expect(page.getByRole('button', {name: '扫描船坞', exact: true})).toHaveCount(0)
  await expect(page.getByRole('button', {name: '同步已有心智数据'})).toHaveCount(0)
  expect(requests).not.toContain('tasks.run'); expect(requests).not.toContain('dock.configure')
  await page.getByRole('tab', {name: '扫描更新', exact: true}).click()
  const source = page.getByRole('tabpanel')
  await expect(source.getByLabel('最低扫描等级')).toHaveValue('1')
  await expect(source.getByLabel('最高扫描等级')).toHaveValue('125')
  await expect(source.getByRole('button', {name: '扫描船坞', exact: true})).toBeVisible()
  await page.screenshot({path: test.info().outputPath('fleet-analysis-desktop.png'), fullPage: true, animations: 'disabled'})
  await page.setViewportSize({width: 412, height: 950})
  expect(await page.evaluate(() => document.body.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({path: test.info().outputPath('fleet-analysis-mobile.png'), fullPage: true, animations: 'disabled'})
  await source.getByLabel('最低扫描等级').fill('90')
  await source.getByRole('button', {name: '扫描船坞', exact: true}).click()
  await expect.poll(() => tasks).toEqual(['DockScan'])
  expect(requests).toContain('dock.configure')
})

test('舰队科技直达路由刷新保持科技标签', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.language', 'zh-CN'))
  await page.goto('/#/i/demo-main/task/FleetAnalysis?tab=technology')
  await expect(page).toHaveURL(/task\/FleetAnalysis\?tab=technology/)
  await expect(page.getByRole('tab', {name: '舰队科技', exact: true})).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.fleet-technology table')).toBeVisible()
  await page.reload()
  await expect(page.getByRole('tab', {name: '舰队科技', exact: true})).toHaveAttribute('aria-selected', 'true')
})

import {expect, test} from '@playwright/test'

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => {localStorage.setItem('azurpilot.theme', 'light'); localStorage.setItem('azurpilot.language', 'zh-CN')})
})

test('资源管理位于资源趋势旁边，旧入口跳转且刷新保持选择', async ({page}) => {
  await page.goto('/#/i/demo-main/resources')
  await expect(page).toHaveURL(/statistics\?view=management$/)
  const tabs = page.locator('.statistics-category-control').getByRole('tab')
  await expect(tabs.nth(0)).toHaveText('资源趋势')
  await expect(tabs.nth(1)).toHaveText('资源管理')
  await expect(page.getByRole('link', {name: '资源管理', exact: true})).toHaveCount(0)
  await expect(page.getByRole('heading', {name: '资源管理', exact: true})).toBeVisible()
  await page.reload()
  await expect(page.getByRole('tab', {name: '资源管理', exact: true})).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('tab', {name: '资源趋势', exact: true}).click()
  await expect(page).toHaveURL(/\/statistics$/)
  await expect(page.locator('.resource-management')).toHaveCount(0)
  await expect(page.locator('.statistics-page-sections')).toBeVisible()
  await page.getByRole('tab', {name: '资源管理', exact: true}).click()
  await page.screenshot({path: test.info().outputPath('statistics-management-tabs.png'), fullPage: true})
})

test('舰队管理下并列打开计算器与舰队信息，扫描开关只运行工具并在结束后刷新结果', async ({page}) => {
  const requests: string[] = []
  let finished = false
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer(), methods = new Map<string, string>()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      methods.set(request.id, request.method); requests.push(request.method)
      if (request.method === 'scheduler.stop') finished = true
      if (request.method === 'tasks.run') expect(request.params).toEqual({instance: 'demo-alt', task: 'FleetScan'})
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      if (response.ok && methods.get(response.id) === 'config.get') response.result.values.FleetInfo = {FleetInfo: {Result: {vanguard: {1: [{name: finished ? '新扫描舰' : '原有舰船', level: 100, emotion: 119}]}}}}
      socket.send(JSON.stringify(response))
    })
  })
  await page.goto('/#/i/demo-alt/mind-calculator')
  await expect(page).toHaveURL(/task\/MindCalculator$/)
  await expect(page.getByRole('heading', {name: '心智单元计算器', exact: true})).toBeVisible()
  await expect(page.locator('.primary-nav').getByRole('link', {name: '心智单元计算器', exact: true})).toHaveCount(0)
  await page.getByRole('button', {name: '舰队管理', exact: true}).hover()
  const menu = page.getByRole('menu', {name: '舰队管理', exact: true})
  await expect(menu.getByRole('menuitem', {name: '心智单元计算器', exact: true})).toHaveAttribute('href', /\/task\/MindCalculator$/)
  await menu.getByRole('menuitem', {name: '舰队信息', exact: true}).click()
  await expect(page).toHaveURL(/task\/FleetInfo$/)
  await expect(page.getByRole('tab', {name: '心智单元计算器', exact: true})).toHaveCount(0)
  await expect(page.locator('.fleet-grid')).toContainText('原有舰船')
  const scan = page.getByRole('switch', {name: '舰队扫描', exact: true})
  await expect(scan).not.toBeChecked()
  await scan.click()
  await expect(scan).toBeChecked()
  await expect(scan).toHaveClass(/\bon\b/)
  await expect(page.getByRole('heading', {name: '日志', exact: true})).toBeVisible()
  await scan.click()
  await expect(scan).not.toBeChecked()
  await expect(scan).not.toHaveClass(/\bon\b/)
  await expect(page.locator('.fleet-grid')).toContainText('新扫描舰')
  expect(requests.filter(method => method === 'tasks.run')).toHaveLength(1)
  expect(requests.filter(method => method === 'scheduler.stop')).toHaveLength(1)
  expect(requests.some(method => method === 'startup.set' || method === 'scheduler.start')).toBe(false)
  await page.screenshot({path: test.info().outputPath('fleet-info-scan-switch.png'), fullPage: true, animations: 'disabled'})
  await page.getByRole('button', {name: '舰队管理', exact: true}).hover()
  await menu.getByRole('menuitem', {name: '心智单元计算器', exact: true}).click()
  await expect(page).toHaveURL(/task\/MindCalculator$/)
  await page.reload()
  await expect(page.getByRole('heading', {name: '心智单元计算器', exact: true})).toBeVisible()
  await expect(page.locator('.mind-add')).toBeVisible()
  await expect(page.locator('.breadcrumb-current')).toHaveText('心智单元计算器')
  await page.getByRole('button', {name: '舰队管理', exact: true}).hover()
  await expect(menu.getByRole('menuitem', {name: '心智单元计算器', exact: true})).toBeVisible()
  await page.screenshot({path: test.info().outputPath('fleet-management-calculator.png'), fullPage: true, animations: 'disabled'})
})

test('舰队扫描开关遇到其他运行任务或更新时禁用，不发送停止请求', async ({page}) => {
  let status = 'running'
  const sent: string[] = []
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer(), methods = new Map<string, string>()
    socket.onMessage(message => {
      const request = JSON.parse(String(message)); methods.set(request.id, request.method); sent.push(request.method); server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      const instances = response.type === 'event' && response.topic === 'instances' ? response.data : response.ok && methods.get(response.id) === 'instances.list' ? response.result : null
      const current = instances?.find((item: {name: string}) => item.name === 'demo-alt')
      if (current) Object.assign(current, {status, currentTask: status === 'running' ? 'Commission' : null})
      socket.send(JSON.stringify(response))
    })
  })
  await page.goto('/#/i/demo-alt/task/FleetInfo')
  await expect(page.getByRole('switch', {name: '舰队扫描'})).toBeDisabled()
  await expect(page.getByRole('status').filter({hasText: '请先停止当前任务'})).toBeVisible()
  status = 'updating'
  await page.reload()
  await expect(page.getByRole('switch', {name: '舰队扫描'})).toBeDisabled()
  await expect(page.getByRole('status').filter({hasText: '请等待更新完成'})).toBeVisible()
  expect(sent.some(method => method === 'tasks.run' || method === 'scheduler.stop')).toBe(false)
  await page.setViewportSize({width: 390, height: 844})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

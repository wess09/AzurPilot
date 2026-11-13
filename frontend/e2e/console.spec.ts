/**
 * @fileoverview 控制台主流程用例：总览与配置的实时更新、刷新持久化、新建实例、断线恢复与预览订阅。
 */

import { expect, test, type WebSocketRoute } from '@playwright/test'

test('总览、配置实时更新与刷新持久化', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/#/i/testpilot/overview')
  await expect(page.getByRole('heading', {name: 'testpilot', exact: true})).toBeVisible()
  await expect(page.getByText('14,200')).toBeVisible()
  await page.screenshot({path: 'test-results/overview-desktop.png', fullPage: true, animations: 'disabled'})
  await page.getByRole('textbox', {name: '搜索任务', exact: true}).fill('Alas')
  await page.locator('#task-group-Alas a[href$="/task/Alas"]').click()
  const serial = page.locator('[id="Alas.Emulator.Serial"]')
  await expect(serial).toBeVisible()
  // 配置页此刻不该有未保存修改：只在内容区里查这两个按钮。
  const configPane = page.locator('main')
  await expect(configPane.getByRole('button', {name: /保存/})).toHaveCount(0)
  await expect(configPane.getByRole('button', {name: '撤销修改'})).toHaveCount(0)
  await expect(page.locator('.save-bar')).toHaveCount(0)
  await serial.fill('127.0.0.1:5557')
  // 输入框失焦才提交：键入期间不写配置。
  await serial.blur()
  await page.waitForTimeout(500)
  await page.reload()
  await expect(serial).toHaveValue('127.0.0.1:5557')
  await page.screenshot({path: 'test-results/config-desktop.png', fullPage: true, animations: 'disabled'})
  await page.locator('.primary-nav').getByRole('link', {name: '资源统计', exact: true}).click()
  await expect(page.getByRole('heading', {name: '资源统计', exact: true})).toBeVisible()
  await expect(page.getByText('这段时间没有有效记录')).toBeVisible()
  await page.locator('.primary-nav').getByRole('link', {name: '运行总览', exact: true}).click()
  await expect(page).toHaveURL(/testpilot\/overview/)
  await expect(page.getByRole('tab', {name: 'testpilot', exact: true})).toHaveAttribute('aria-selected', 'true')
  expect(errors).toEqual([])
})

test('新建实例使用真实 API，移动端无横向溢出', async ({page}) => {
  await page.goto('/#/i/testpilot/overview')
  await expect(page.getByRole('heading', {name: 'testpilot', exact: true})).toBeVisible()
  await page.locator('.instance-tabs').getByRole('button', {name: '创建实例', exact: true}).click()
  const name = `ui_${Date.now()}`
  await page.getByLabel('实例名称').fill(name)
  await page.getByRole('dialog').getByRole('button', {name: '创建实例', exact: true}).click()
  await expect(page).toHaveURL(new RegExp(`/i/${name}/overview$`))
  await expect(page.locator('.instance-page-grid')).toBeVisible()
  await page.setViewportSize({width: 390, height: 844})
  await page.getByRole('button', {name: '打开导航'}).click()
  await page.locator('.primary-nav a[href$="/overview"]').click()
  await expect(page.getByRole('heading', {name, exact: true})).toBeVisible()
  await expect(page.locator('.app-shell')).not.toHaveClass(/mobile-open/)
  await page.screenshot({path: 'test-results/overview-mobile.png', fullPage: true, animations: 'disabled'})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('断线后自动恢复，保留未保存草稿', async ({page}) => {
  const sockets: WebSocketRoute[] = []
  await page.routeWebSocket(/\/api\/v1\/ws(?:\?channel=control)?$/, socket => {
    socket.connectToServer()
    sockets.push(socket)
  })
  await page.goto('/#/i/testpilot/task/Alas')
  const serial = page.locator('[id="Alas.Emulator.Serial"]')
  await expect(serial).toBeVisible()
  await serial.fill('keep-draft')
  await sockets[0].close({code: 1012, reason: '验证服务重启后的恢复'})
  await expect(page.locator('.connection-banner')).toBeVisible()
  await expect(page.locator('.connection-banner')).toBeHidden()
  expect(sockets.length).toBeGreaterThan(1)
  await expect(serial).toHaveValue('keep-draft')
  await page.locator('.breadcrumb').getByRole('link', {name: '系统设置', exact: true}).click()
  await page.locator('.primary-nav').getByRole('link', {name: '界面设置'}).click()
  await page.getByRole('tablist', {name: '明暗', exact: true})
    .getByRole('tab', {name: '深色', exact: true}).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'legacy-dark')
  await page.goto('/#/i/testpilot/task/Alas')
  await expect(serial).toBeVisible()
  await page.screenshot({path: 'test-results/config-dark.png', fullPage: true, animations: 'disabled'})
})

test('自动预览在重连后恢复订阅，离开总览后取消', async ({page}) => {
  const sockets: WebSocketRoute[] = []
  const subscriptions: string[][] = []
  page.on('websocket', socket => {
    if (new URL(socket.url()).searchParams.get('channel') !== 'data') return
    socket.on('framesent', frame => {
      if (typeof frame.payload !== 'string') return
      const message = JSON.parse(frame.payload)
      if (message.method === 'events.subscribe') subscriptions.push(message.params.topics)
    })
  })
  await page.routeWebSocket(/\/api\/v1\/ws(?:\?channel=control)?$/, socket => {
    socket.connectToServer()
    sockets.push(socket)
  })
  await page.goto('/#/i/testpilot/overview')
  await page.getByRole('tab', {name: '截图', exact: true}).click()
  await expect.poll(() => subscriptions.at(-1)).toContain('preview')
  await sockets[0].close({code: 1012})
  await expect(page.locator('.connection-banner')).toBeVisible()
  await expect(page.locator('.connection-banner')).toBeHidden()
  await expect.poll(() => subscriptions.at(-1)).toContain('preview')
  expect(sockets.length).toBeGreaterThan(1)
  await page.locator('.primary-nav').getByRole('link', {name: '资源统计', exact: true}).click()
  await expect.poll(() => subscriptions.at(-1)).not.toContain('preview')
})

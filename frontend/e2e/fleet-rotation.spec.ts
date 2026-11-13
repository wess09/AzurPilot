/**
 * @fileoverview 换船配置页用例：六队舰位与候补舰队的保存独立于调度开关，页面导航不触发扫描调度。
 */

import {routeRpc} from './rpc-route'
import {expect, test} from '@playwright/test'

test('换船配置保存六队舰位与多选候补，并与调度开关分开保存', async ({page}) => {
  const requests: string[] = []
  await routeRpc(page, socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {requests.push(JSON.parse(String(message)).method); server.send(message)})
    server.onMessage(message => socket.send(message))
  })
  await page.goto('/#/i/testpilot/task/FleetRotation')
  await expect(page.getByRole('heading', {name: '换船配置', exact: true})).toBeVisible()
  await expect(page.getByRole('switch')).toHaveCount(0)
  const fleet = page.getByRole('region', {name: '第 1 舰队', exact: true})
  await expect(page.locator('.fleet-grid .panel')).toHaveCount(6)
  await expect(fleet.getByRole('checkbox', {name: /不变/})).toHaveCount(6)
  for (const number of [3, 4, 5]) await fleet.getByRole('checkbox', {name: `舰位 ${number} · 不变`, exact: true}).check()
  for (const number of [3, 4, 5, 6]) await fleet.getByRole('checkbox', {name: `候补舰队 ${number}`, exact: true}).check()
  await page.getByRole('button', {name: '保存规则', exact: true}).click()
  await expect(page.getByRole('button', {name: '保存规则', exact: true})).toBeDisabled()
  await page.locator('main').getByRole('link', {name: '换船调度', exact: true}).click()
  const enable = page.getByRole('switch', {name: '启用心情调度', exact: true})
  await expect(enable).toHaveAttribute('aria-checked', 'false')
  await enable.click()
  await expect(enable).toHaveAttribute('aria-checked', 'true')
  await page.reload()
  await expect(enable).toHaveAttribute('aria-checked', 'true')
  await page.locator('main').getByRole('link', {name: '换船配置：设置舰位与候补舰队'}).click()
  for (const number of [3, 4, 5]) await expect(fleet.getByRole('checkbox', {name: `舰位 ${number} · 换船`, exact: true})).toBeChecked()
  for (const number of [3, 4, 5, 6]) await expect(fleet.getByRole('checkbox', {name: `候补舰队 ${number}`, exact: true})).toBeChecked()
  expect(requests).not.toContain('tasks.run')
  expect(requests).not.toContain('scheduler.start')
  await expect(page.locator('.right-rail')).toHaveCount(0)
  await page.screenshot({path: test.info().outputPath('fleet-rotation-desktop.png'), fullPage: true, animations: 'disabled'})
  await page.setViewportSize({width: 390, height: 844})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({path: test.info().outputPath('fleet-rotation-mobile.png'), fullPage: true, animations: 'disabled'})
})

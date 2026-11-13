/**
 * @fileoverview 舰队信息页用例：兼容旧版记录格式并正确展示心情与未知值，扫描启动前先保存心情选项。
 */

import {routeRpc} from './rpc-route'
import { expect, test } from '@playwright/test'

test('舰队信息兼容旧记录并展示心情与未知值', async ({page}) => {
  const requests = new Map<string, string>()
  await routeRpc(page, socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      requests.set(request.id, request.method)
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      if (response.ok && requests.get(response.id) === 'config.get') {
        response.result.values.FleetInfo = {FleetInfo: {Result: {
          vanguard: {1: [{name: '测试先锋', slot: 4, level: 125, emotion: 150}, {name: '测试零心情', slot: 5, level: 100, emotion: 0}]},
          main: {1: [{name: '测试未知', level: 70, emotion: null}, {name: '旧对象', level: 10}]},
          submarine: {1: ['旧字符串']},
        }}}
      }
      socket.send(JSON.stringify(response))
    })
  })
  await page.goto('/#/i/testpilot/task/FleetInfo')
  const fleet = page.locator('.fleet-grid .panel').first()
  await expect(fleet).toContainText('测试先锋')
  await expect(fleet).toContainText('舰位 4 · 测试先锋')
  await expect(fleet).toContainText('舰位 5 · 测试零心情')
  await expect(fleet).toContainText('Lv.125 · 心情 150')
  await expect(fleet).toContainText('Lv.100 · 心情 0')
  await expect(fleet).toContainText('Lv.70 · 心情 未知')
  await expect(fleet).toContainText('Lv.10 · 心情 未知')
  await expect(fleet).toContainText('旧字符串')
  await page.screenshot({path: test.info().outputPath('fleet-info-desktop.png'), fullPage: true, animations: 'disabled'})
  await page.setViewportSize({width: 390, height: 844})
  await expect(fleet).toContainText('心情 150')
  const overflow = await page.locator('.fleet-grid').evaluate(element => element.scrollWidth > element.clientWidth)
  expect(overflow).toBe(false)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({path: test.info().outputPath('fleet-info-mobile.png'), fullPage: true, animations: 'disabled'})
})

test('扫描启动前先保存本次心情更新选项', async ({page}) => {
  const sent: Array<{method: string; params?: {changes?: Array<{path: string; value: unknown}>}}> = []
  await routeRpc(page, socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      sent.push(request)
      if (request.method === 'tasks.run') {
        socket.send(JSON.stringify({type: 'response', id: request.id, ok: true, result: {}}))
      } else server.send(message)
    })
    server.onMessage(message => socket.send(message))
  })
  await page.goto('/#/i/testpilot/task/FleetInfo')
  const update = page.getByRole('checkbox', {name: '扫描时更新心情'})
  await expect(update).toBeEnabled()
  await update.uncheck()
  await page.getByRole('switch', {name: '舰队扫描', exact: true}).click()
  await expect.poll(() => sent.some(request => request.method === 'tasks.run')).toBe(true)
  const save = sent.findIndex(request => request.method === 'config.patch' && request.params?.changes?.some(
    change => change.path === 'FleetInfo.FleetInfo.UpdateEmotion' && change.value === false))
  const run = sent.findIndex(request => request.method === 'tasks.run')
  expect(save).toBeGreaterThanOrEqual(0)
  expect(save).toBeLessThan(run)
})

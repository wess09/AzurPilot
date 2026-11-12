/**
 * @fileoverview 大世界模拟器用例（串行执行）：绘图模式运行与结果持久、长模拟中断重跑与窄屏布局可用性。
 */

import {routeRpc} from './rpc-route'
import { expect, test, type Page } from '@playwright/test'

test.describe.configure({mode: 'serial'})
test.beforeEach(async ({page}) => {
  await page.emulateMedia({reducedMotion: 'reduce'})
})

const panelSelector = '.opsi-simulator-panel'

async function setNumber(page: Page, name: string, value: number) {
  const field = page.locator(`[id="OpsiSimulator.OpsiSimulatorParameters.${name}"]`)
  await field.fill(String(value))
  await field.blur()
}

async function setDrawing(page: Page, index: number) {
  const field = page.locator('[id="OpsiSimulator.OpsiSimulatorParameters.Draw"]')
  await field.click()
  await page.getByRole('option').nth(index).click()
}

test('三种绘图模式均可从页面运行，结果和独立日志在刷新后保留', async ({page}, testInfo) => {
  const methods: string[] = []
  let holdStatus = false
  let heldId = ''
  let startId = ''
  let heldResponse: string | Buffer | undefined
  let sendData: (message: string | Buffer) => void
  await routeRpc(page, socket => {
    const server = socket.connectToServer()
    if (socket.channel === 'data') sendData = socket.send
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      methods.push(request.method)
      if (holdStatus && request.method === 'opsi.simulator.status' && !heldId) heldId = request.id
      if (request.method === 'opsi.simulator.start') startId = request.id
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      if (holdStatus && response.id === heldId) { heldResponse = message; return }
      socket.send(message)
      if (response.id === startId && heldResponse) {
        const stale = heldResponse
        holdStatus = false; heldResponse = undefined; heldId = ''
        // 模拟启动前的状态响应比启动响应更晚到达。
        setTimeout(() => sendData(stale), 100)
      }
    })
  })
  await page.goto('/#/i/testpilot/task/OpsiSimulator')
  const panel = page.locator(panelSelector)
  await expect(panel.getByRole('button', {name: '开始模拟', exact: true})).toBeEnabled()
  for (const [name, value] of Object.entries({Samples: 3, TotalTime: 180, TimeUseRatio: 1,
    InitialAp: 500, InitialCoin: 100000, Cl1Time: 60, Meow5Time: 120, AkashiProbability: 0})) {
    await setNumber(page, name, value)
  }
  const deterministic = page.locator('[id="OpsiSimulator.OpsiSimulatorParameters.Deterministic"]')
  if (await deterministic.getAttribute('aria-checked') === 'false') await deterministic.click()

  for (let mode = 0; mode < 3; mode++) {
    await setDrawing(page, mode)
    const runId = Number(await panel.getAttribute('data-run-id'))
    if (mode === 2) {
      holdStatus = true
      await expect.poll(() => Boolean(heldResponse)).toBe(true)
    }
    // 紧接参数修改点击启动，验证启动会等配置队列保存完成。
    await panel.getByRole('button', {name: '开始模拟', exact: true}).click()
    await expect(panel).toHaveAttribute('data-run-id', String(runId + 1))
    await expect(panel.getByRole('status')).toContainText('模拟完成', {timeout: 30000})
    await expect(panel.getByRole('status')).toContainText('1 / 1')
    await expect(panel.locator('.simulator-results')).toContainText('485.3')
    await expect(panel.locator('.simulator-results')).toContainText('100,510')
    await expect(panel).toContainText('[模拟结果]')
    const figure = panel.getByRole('img', {name: '大世界模拟轨迹图'})
    if (mode === 0) await expect(figure).toHaveCount(0)
    else {
      await expect(figure).toBeVisible()
      await expect.poll(() => figure.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true)
    }
    if (mode === 2) {
      await panel.locator('.simulator-results').scrollIntoViewIfNeeded()
      await page.screenshot({path: testInfo.outputPath('opsi-simulator-results.png'), animations: 'disabled'})
    }
  }
  await page.reload()
  await expect(panel.getByRole('status')).toContainText('模拟完成')
  await expect(panel.getByRole('img', {name: '大世界模拟轨迹图'})).toBeVisible()
  await expect(panel).toContainText('[模拟结果]')
  expect(methods).not.toContain('tasks.run')
  expect(methods).not.toContain('scheduler.start')
  expect(methods).not.toContain('scheduler.stop')
  expect(methods).not.toContain('logs.get')
})

test('长模拟可在刷新后中断，并可重新运行', async ({page}) => {
  await page.goto('/#/i/testpilot/task/OpsiSimulator')
  const panel = page.locator(panelSelector)
  const deterministic = page.locator('[id="OpsiSimulator.OpsiSimulatorParameters.Deterministic"]')
  await expect(deterministic).toHaveAttribute('aria-checked', 'true')
  await deterministic.click()
  await setDrawing(page, 0)
  for (const [name, value] of Object.entries({Samples: 1000000, TotalTime: 2592000, InitialAp: 100000000})) {
    await setNumber(page, name, value)
  }
  await panel.getByRole('button', {name: '开始模拟', exact: true}).click()
  await expect(panel.getByRole('button', {name: '中断模拟', exact: true})).toBeEnabled()
  await page.reload()
  await expect(panel.getByRole('button', {name: '中断模拟', exact: true})).toBeEnabled()
  await panel.getByRole('button', {name: '中断模拟', exact: true}).click()
  await expect(panel.getByRole('status')).toContainText('模拟已中断', {timeout: 30000})
  await expect(panel.getByRole('button', {name: '开始模拟', exact: true})).toBeEnabled()
  for (const [name, value] of Object.entries({Samples: 3, TotalTime: 180, InitialAp: 500})) {
    await setNumber(page, name, value)
  }
  await panel.getByRole('button', {name: '开始模拟', exact: true}).click()
  await expect(panel.getByRole('status')).toContainText('模拟完成')
  await expect(panel.getByRole('status')).toContainText('3 / 3')
  await expect(panel.locator('.simulator-results')).toContainText('485.3')
})

test('非法利用率显示失败，修正后能重跑，旧版与窄屏布局可操作', async ({page}, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.theme', 'legacy-light'))
  await page.goto('/#/i/testpilot/task/OpsiSimulator')
  const panel = page.locator(panelSelector)
  await setNumber(page, 'TimeUseRatio', 0)
  await panel.getByRole('button', {name: '开始模拟', exact: true}).click()
  await expect(panel.getByRole('status')).toContainText('模拟失败')
  await expect(panel).toContainText('时间利用率必须大于 0')
  await setNumber(page, 'TimeUseRatio', 1)
  await panel.getByRole('button', {name: '开始模拟', exact: true}).click()
  await expect(panel.getByRole('status')).toContainText('模拟完成')
  await panel.locator('.simulator-results').scrollIntoViewIfNeeded()
  await page.screenshot({path: testInfo.outputPath('opsi-simulator-legacy.png'), animations: 'disabled'})
  await page.setViewportSize({width: 390, height: 844})
  await panel.scrollIntoViewIfNeeded()
  await expect(panel.getByRole('button', {name: '开始模拟', exact: true})).toBeVisible()
  const box = await panel.boundingBox()
  expect(box!.x).toBeGreaterThanOrEqual(0)
  expect(box!.x + box!.width).toBeLessThanOrEqual(391)
  await panel.locator('.panel-heading').first().scrollIntoViewIfNeeded()
  await page.mouse.move(380, 820)
  await page.screenshot({path: testInfo.outputPath('opsi-simulator-mobile.png'), animations: 'disabled'})
})

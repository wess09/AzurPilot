/**
 * @fileoverview 智能开荒用例：分组位于智能调度末尾并显示前置条件，独立开关与只读进度的清空保存。
 */

import {routeRpc} from './rpc-route'
import { expect, test } from '@playwright/test'

test('智能开荒位于智能调度末尾，显示前置条件并持久化独立开关', async ({page}, testInfo) => {
  await page.goto('/#/i/testpilot/task/OpsiScheduling')
  const group = page.locator('#group-OpsiSmartExplore')
  await expect(group.getByRole('heading', {name: '智能开荒', exact: true})).toBeVisible()
  await group.scrollIntoViewIfNeeded()
  const enable = page.locator('[id="OpsiScheduling.OpsiSmartExplore.Enable"]')
  const purchase = page.locator('[id="OpsiScheduling.OpsiScheduling.BuyActionPoint"]')
  const cleanup = page.locator('[id="OpsiScheduling.OpsiSmartExplore.EventCleanup"]')
  const force = page.locator('[id="OpsiScheduling.OpsiSmartExplore.ForceRun"]')
  for (const control of [enable, purchase, cleanup, force]) await expect(control).toHaveAttribute('aria-checked', 'false')
  await expect(group).toContainText('仅默认黄币')
  await expect(group).toContainText('1360')
  await expect(group).toContainText('不能同时启用')
  await expect(page.locator('#group-OpsiScheduling .field-row').first()).toContainText('行动力不足时购买港口行动力')
  await expect(page.locator('#group-OpsiScheduling')).toContainText('每月仅一次')
  await expect(page.locator('.config-group').last()).toHaveAttribute('id', 'group-OpsiSmartExplore')
  const progress = page.locator('[id="OpsiScheduling.OpsiSmartExplore.Progress"]')
  await expect(progress).toBeDisabled()
  // 购买开关可以独立启用，智能开荒仍保持关闭。
  await purchase.click()
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
  await page.reload()
  await expect(purchase).toHaveAttribute('aria-checked', 'true')
  await expect(enable).toHaveAttribute('aria-checked', 'false')
  for (const control of [enable, cleanup, force]) {
    await control.click()
    await expect(control).toHaveAttribute('aria-checked', 'true')
  }
  // 刷新并读取服务端状态，确认不是仅在浏览器内切换。
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
  await page.reload()
  for (const control of [enable, purchase, cleanup, force]) await expect(control).toHaveAttribute('aria-checked', 'true')
  await page.locator('#group-OpsiScheduling').screenshot({path: testInfo.outputPath('action-point-purchase-settings.png')})
  await group.scrollIntoViewIfNeeded()
  await group.screenshot({path: testInfo.outputPath('smart-explore-settings.png')})
})

test('两处只读开荒进度可通过清空按钮保存为空', async ({page}) => {
  let seed: {task: string; group: string; arg: string} | undefined
  await routeRpc(page, socket => {
    const server = socket.connectToServer()
    let getId: string | undefined
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      if (request.method === 'config.get') getId = request.id
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      // 模拟读取到旧进度，清空和刷新仍走真实隔离服务。
      if (seed && response.id === getId && response.ok) {
        response.result.values[seed.task][seed.group][seed.arg] = '已开荒 34/72'
        seed = undefined
        socket.send(JSON.stringify(response))
      } else socket.send(message)
    })
  })
  for (const [task, group, arg] of [
    ['OpsiScheduling', 'OpsiSmartExplore', 'Progress'],
    ['OpsiExplore', 'OpsiExplore', 'ExploreProgress'],
  ]) {
    seed = {task, group, arg}
    await page.goto(`/#/i/testpilot/task/${task}`)
    const progress = page.locator(`[id="${task}.${group}.${arg}"]`)
    await expect(progress).toHaveValue('已开荒 34/72')
    await expect(progress).toBeDisabled()
    const clear = page.getByRole('button', {name: '清空开荒进度', exact: true})
    await clear.click()
    await expect(progress).toHaveValue('')
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
    await page.reload()
    await expect(progress).toHaveValue('')
    if (task === 'OpsiExplore') await expect(page.locator('[id="OpsiExplore.OpsiExplore.ForceRun"]')).toHaveAttribute('aria-checked', 'false')
  }
})

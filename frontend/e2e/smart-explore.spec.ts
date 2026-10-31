import { expect, test } from '@playwright/test'

test('大世界开荒统一模式和进度，互斥开关与共用间隔可持久化', async ({page}, testInfo) => {
  await page.goto('/#/i/testpilot/task/OpsiScheduling')
  await expect(page.locator('#group-OpsiSmartExplore')).toHaveCount(0)
  const purchase = page.locator('[id="OpsiScheduling.OpsiScheduling.BuyActionPoint"]')
  await expect(purchase).toHaveAttribute('aria-checked', 'false')
  await purchase.click()
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
  await page.goto('/#/i/testpilot/task/OpsiExplore')
  const group = page.locator('#group-OpsiExplore')
  await expect(group.getByRole('heading', {name: '大世界开荒', exact: true})).toBeVisible()
  const traditional = page.locator('[id="OpsiExplore.OpsiExplore.TraditionalEnable"]')
  const smart = page.locator('[id="OpsiExplore.OpsiExplore.SmartEnable"]')
  const force = page.locator('[id="OpsiExplore.OpsiExplore.ForceRun"]')
  const progress = page.locator('[id="OpsiExplore.OpsiExplore.Progress"]')
  await expect(traditional).toHaveAttribute('aria-checked', 'true')
  await expect(smart).toHaveAttribute('aria-checked', 'false')
  await expect(force).toHaveAttribute('aria-checked', 'false')
  await expect(progress).toBeDisabled()
  await expect(group).toContainText('切换模式会清除')
  await expect(group).toContainText('1360')
  await expect(group.locator('label[for="OpsiExplore.OpsiExplore.Progress"]')).toContainText('开荒进度')
  await expect(group.getByText('普通海域事件补扫', {exact: true})).toHaveCount(0)
  await expect(group.getByText('每月开荒进度', {exact: true})).toHaveCount(0)
  await expect(page.locator('[id="OpsiExplore.OpsiExplore.ExploreProgress"]')).toHaveCount(0)
  await smart.click()
  await expect(smart).toHaveAttribute('aria-checked', 'true')
  await expect(traditional).toHaveAttribute('aria-checked', 'false')
  // 紧接着切回，确认已保存的旧开关值不会盖住服务端自动关闭的结果。
  await traditional.click()
  await expect(traditional).toHaveAttribute('aria-checked', 'true')
  await expect(smart).toHaveAttribute('aria-checked', 'false')
  await force.click()
  await smart.click()
  await expect(traditional).toHaveAttribute('aria-checked', 'false')
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
  await page.reload()
  await expect(smart).toHaveAttribute('aria-checked', 'true')
  await expect(traditional).toHaveAttribute('aria-checked', 'false')
  await expect(force).toHaveAttribute('aria-checked', 'true')
  await group.screenshot({path: testInfo.outputPath('exploration-settings.png')})
  await page.goto('/#/i/testpilot/task/OpsiScheduling')
  await expect(purchase).toHaveAttribute('aria-checked', 'true')
  await expect(page.locator('#group-OpsiSmartExplore')).toHaveCount(0)
})

test('共用开荒进度在两种模式下均可清空，换模式也清空显示', async ({page}) => {
  let seed = false
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    let getId: string | undefined
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      if (request.method === 'config.get') getId = request.id
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      // 读取时注入进度，清空和切换仍走真实隔离后端；断点事务由后端测试覆盖。
      if (seed && response.id === getId && response.ok) {
        response.result.values.OpsiExplore.OpsiExplore.Progress = '已开荒 34/72'
        seed = false
        socket.send(JSON.stringify(response))
      } else socket.send(message)
    })
  })
  await page.goto('/#/i/testpilot/task/OpsiExplore')
  const progress = page.locator('[id="OpsiExplore.OpsiExplore.Progress"]')
  for (const mode of ['TraditionalEnable', 'SmartEnable']) {
    const control = page.locator(`[id="OpsiExplore.OpsiExplore.${mode}"]`)
    if (await control.getAttribute('aria-checked') === 'false') await control.click()
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
    seed = true
    await page.reload()
    await expect(progress).toHaveValue('已开荒 34/72')
    await expect(progress).toBeDisabled()
    await page.getByRole('button', {name: '清空开荒进度', exact: true}).click()
    await expect(progress).toHaveValue('')
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
    await page.reload()
    await expect(progress).toHaveValue('')
    seed = true
    await page.reload()
    await expect(progress).toHaveValue('已开荒 34/72')
    const other = mode === 'TraditionalEnable' ? 'SmartEnable' : 'TraditionalEnable'
    await page.locator(`[id="OpsiExplore.OpsiExplore.${other}"]`).click()
    await expect(progress).toHaveValue('')
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
    await page.reload()
    await expect(progress).toHaveValue('')
  }
})

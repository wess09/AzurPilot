import { expect, test } from '@playwright/test'

const serialSelector = '[id="Alas.Emulator.Serial"]'
const serialStatus = '[id="Alas.Emulator.Serial-status"]'
// 字段为草稿式提交：键入期间不写配置，失焦或回车才提交，故断言保存前先 blur。

for (const [task, stage] of [['EventA', 'a3'], ['EventB', 'B3'], ['EventC', 'c3'], ['EventD', 'D3']]) {
  test(`${task} 活动日常断点从旧数字 0 改成关卡名，刷新后保留并可重置`, async ({page}) => {
    await page.goto(`/#/i/testpilot/task/${task}`)
    const value = page.locator(`[id="${task}.EventDaily.LastStage"]`)
    const status = page.locator(`[id="${task}.EventDaily.LastStage-status"]`)
    await expect(value).toBeVisible({timeout: 15000})
    await expect(value).toHaveValue('0')
    await expect(value).toHaveAttribute('type', 'text')
    await expect(value).not.toHaveAttribute('inputmode', 'decimal')
    await value.fill(stage)
    await value.blur()
    await expect(status).toHaveText('已保存')
    await expect(value).not.toHaveAttribute('aria-invalid', 'true')
    await page.reload()
    await expect(value).toHaveValue(stage)
    await value.fill('0')
    await value.press('Enter')
    await expect(status).toHaveText('已保存')
    await page.reload()
    await expect(value).toHaveValue('0')
  })
}

test('两个页面的旧快照均能保存，字段更新互不覆盖', async ({page, context}) => {
  const second = await context.newPage()
  await page.goto('/#/i/testpilot/task/Alas')
  await second.goto('/#/i/testpilot/task/Alas')
  await expect(page.locator(serialSelector)).toBeVisible()
  const threshold = second.locator('[id="Alas.Error.GameStuckThreshold"]')
  await expect(threshold).toBeVisible()
  await page.locator(serialSelector).fill('parallel-page-edit')
  await page.locator(serialSelector).blur()
  // “已保存”提示会延迟出现并自动消失，不能把瞬时 UI 当作提交屏障；
  // 从另一页面重新读取服务端快照，才能真正证明旧快照的字段已经合并保存。
  /* 切走再切回同一实例的任务页：组件重新挂载即重新向服务端取快照。 */
  const reread = async (target: typeof page) => {
    await target.evaluate(() => { location.hash = '#/i/testpilot/overview' })
    await target.evaluate(() => { location.hash = '#/i/testpilot/task/Alas' })
  }
  await expect.poll(async () => {
    await reread(second)
    return second.locator(serialSelector).inputValue()
  }).toBe('parallel-page-edit')
  await threshold.fill('7')
  await threshold.blur()
  await expect.poll(async () => {
    await reread(page)
    return page.locator('[id="Alas.Error.GameStuckThreshold"]').inputValue()
  }).toBe('7')
  await expect(second.locator(serialSelector)).toHaveValue('parallel-page-edit')
  await expect(page.locator('[id="Alas.Error.GameStuckThreshold"]')).toHaveValue('7')
})

test('旧响应延迟期间连续输入并切页，最终值继续保存', async ({page}) => {
  let release: (() => void) | undefined
  let firstId: string | undefined
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      if (!firstId && request.method === 'config.patch') firstId = request.id
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      if (firstId && response.id === firstId) release = () => socket.send(message)
      else socket.send(message)
    })
  })
  await page.goto('/#/i/testpilot/task/Alas')
  const serial = page.locator(serialSelector)
  await serial.fill('first-in-flight')
  await serial.blur()
  await expect.poll(() => !!release).toBe(true)
  await serial.fill('latest-user-input')
  await serial.blur()
  await expect(serial).toHaveValue('latest-user-input')
  await page.locator('.breadcrumb .instance-caption').click()
  release!()
  await page.goto('/#/i/testpilot/task/Alas')
  await expect(serial).toHaveValue('latest-user-input')
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
  await page.reload()
  await expect(serial).toHaveValue('latest-user-input')
})

test('请求尚未送达就断线并刷新，恢复后自动保存原输入', async ({page}) => {
  let drop = true
  let dropped = false
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      if (JSON.parse(String(message)).method === 'config.patch' && drop) {
        dropped = true
        void socket.close({code: 1012})
      } else server.send(message)
    })
  })
  await page.goto('/#/i/testpilot/task/Alas')
  const serial = page.locator(serialSelector)
  await serial.fill('survives-disconnect-and-reload')
  await serial.blur()
  await expect.poll(() => dropped).toBe(true)
  drop = false
  await page.reload()
  await expect(serial).toHaveValue('survives-disconnect-and-reload')
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
  await page.reload()
  await expect(serial).toHaveValue('survives-disconnect-and-reload')
})

test('非法数字、日期和 YAML 保留草稿，其他字段失焦后保存', async ({page}) => {
  await page.goto('/#/i/testpilot/task/Alas')
  const threshold = page.locator('[id="Alas.Error.GameStuckThreshold"]')
  await threshold.fill('-')
  await expect(threshold).toHaveValue('-')
  await threshold.blur()
  await expect(threshold).toHaveAttribute('aria-invalid', 'true')
  const yaml = page.locator('[id="Alas.Error.OnePushConfig"]')
  await yaml.fill('provider: [')
  await expect(page.locator('[id="Alas.Error.OnePushConfig-status"]')).toContainText('YAML 格式不正确')
  await page.locator(serialSelector).fill('valid-despite-invalid-fields')
  await page.locator(serialSelector).blur()
  await expect(page.locator(serialStatus)).toHaveText('已保存')
  await page.reload()
  await expect(threshold).toHaveValue('-')
  await expect(yaml).toHaveText('provider: [')
  await expect(page.locator(serialSelector)).toHaveValue('valid-despite-invalid-fields')
  await threshold.fill('3')
  await threshold.blur()
  await yaml.fill('provider: null')
  await expect(page.locator('[id="Alas.Error.GameStuckThreshold-status"]')).toHaveText('已保存')
  await expect(page.locator('[id="Alas.Error.OnePushConfig-status"]')).toHaveText('已保存')
  await page.goto('/#/i/testpilot/task/Main')
  const date = page.locator('[id="Main.Scheduler.NextRun"]')
  await date.fill('2026-02-30 12:00:00')
  await date.blur()
  await expect(page.locator('[id="Main.Scheduler.NextRun-status"]')).toContainText('日期格式')
  await expect(date).toHaveValue('2026-02-30 12:00:00')
  await date.fill('2099-01-01 12:00:00')
  await date.blur()
  await expect(page.locator('[id="Main.Scheduler.NextRun-status"]')).toHaveText('已保存')
  // 清空时间要回落到参数默认值：它落在过去，调度器下一轮就把任务当作待运行。
  await date.fill('')
  await date.blur()
  await expect(date).toHaveValue('2020-01-01 00:00:00')
  await expect(page.locator('[id="Main.Scheduler.NextRun-status"]')).toHaveText('已保存')
  await page.reload()
  await expect(date).toHaveValue('2020-01-01 00:00:00')
})

test('遗留的空时间草稿在恢复时被丢弃，字段回到配置里的值', async ({page}) => {
  // 旧版本拒绝空时间后把空值留在草稿里：字段已空时再清空不会触发输入事件，
  // 草稿永远换不掉。恢复草稿时丢弃它，字段回到配置里的值。
  await page.addInitScript(() => sessionStorage.setItem('azurpilot.edits.config:testpilot', JSON.stringify({
    'Main.Scheduler.NextRun': {
      value: '', payload: '', sequence: 1, status: 'error', retryable: false,
      error: '日期格式应为 YYYY-MM-DD HH:mm:ss：Main.Scheduler.NextRun',
    },
  })))
  await page.goto('/#/i/testpilot/task/Main')
  await expect(page.locator('[id="Main.Scheduler.NextRun"]')).toHaveValue('2020-01-01 00:00:00')
  await expect(page.locator('[id="Main.Scheduler.NextRun-status"]')).toHaveCount(0)
})

test('立刻运行按钮把调度时间改成可立即运行', async ({page}) => {
  await page.goto('/#/i/testpilot/task/Main')
  const date = page.locator('[id="Main.Scheduler.NextRun"]')
  const status = page.locator('[id="Main.Scheduler.NextRun-status"]')
  await date.fill('2099-01-01 12:00:00')
  await date.blur()
  await expect(status).toHaveText('已保存')
  // 按钮等同清空该字段：提交参数默认值，它落在过去，调度器下一轮即运行。
  await page.getByRole('button', {name: '立刻运行', exact: true}).click()
  await expect(date).toHaveValue('2020-01-01 00:00:00')
  await expect(status).toHaveText('已保存')
  await page.reload()
  await expect(date).toHaveValue('2020-01-01 00:00:00')
})

test('清空数字字段回落到参数默认值，不再提示格式错误', async ({page}) => {
  await page.goto('/#/i/testpilot/task/Main')
  const value = page.locator('[id="Main.Emotion.Fleet1Value"]')
  const status = page.locator('[id="Main.Emotion.Fleet1Value-status"]')
  await value.fill('95')
  await value.blur()
  await expect(status).toHaveText('已保存')
  await value.fill('')
  await value.blur()
  await expect(value).toHaveValue('119')
  await expect(status).toHaveText('已保存')
  await page.reload()
  await expect(value).toHaveValue('119')
})

test('清空文本字段回落到参数默认值，便于后续修改', async ({page}) => {
  await page.goto('/#/i/testpilot/task/Alas')
  const serial = page.locator(serialSelector)
  const status = page.locator(serialStatus)
  await serial.fill('custom-serial-for-test')
  await serial.blur()
  await expect(status).toHaveText('已保存')
  await serial.fill('')
  await serial.blur()
  await expect(serial).toHaveValue('auto')
  await expect(status).toHaveText('已保存')
  await page.reload()
  await expect(serial).toHaveValue('auto')
})

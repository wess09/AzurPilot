import { expect, test } from '@playwright/test'

for (const task of ['ThreeOilLowCost', 'GemsFarming']) {
  test(`${task} 无合适舰船时的推迟开关可切换并保存`, async ({page}) => {
    await page.goto(`/#/i/testpilot/task/${task}`)
    const toggle = page.getByRole('switch', {name: '没有合适舰船时推迟任务', exact: true})
    await expect(toggle).toHaveAttribute('aria-checked', 'false')
    await expect(page.getByText('关闭：使用当前舰队继续出击', {exact: false})).toBeVisible()

    for (const enabled of [true, false]) {
      await toggle.click()
      await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
      await page.reload()
      await expect(toggle).toHaveAttribute('aria-checked', String(enabled))
    }
  })
}

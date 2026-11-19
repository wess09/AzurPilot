/** @fileoverview 响应式回归：页面在实际可用的 CSS 视口内换行、滚动和操作。 */

import {expect, test, type Locator, type Page} from '@playwright/test'

async function expectContentFits(page: Page) {
  await expect.poll(() => page.locator('main').evaluate(main => Math.max(
    main.scrollWidth - main.clientWidth,
    document.documentElement.scrollWidth - innerWidth,
  ))).toBeLessThanOrEqual(1)
}

async function expectHorizontallyVisible(control: Locator) {
  await expect.poll(() => control.evaluate(element => {
    const {left, right, width} = element.getBoundingClientRect()
    return width > 0 && left >= -1 && right <= innerWidth + 1
  })).toBe(true)
}

test('narrow view keeps navigation, fleet tabs and settings operable', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.language', 'en-US'))
  await page.setViewportSize({width: 320, height: 568})
  await page.goto('/#/i/testpilot/task/FleetSwitch?tab=training')
  const tabs = page.locator('.fleet-switch').getByRole('tablist')
  await expect(tabs.getByRole('tab')).toHaveCount(4)
  for (const tab of await tabs.getByRole('tab').all()) await expectHorizontallyVisible(tab)
  await tabs.getByRole('tab', {name: 'Rotation equipment'}).click()
  await expect(page).toHaveURL(/tab=equipment/)
  await expectContentFits(page)

  await page.locator('.mobile-toggle').click()
  await expect(page.locator('.sidebar')).toBeInViewport()
  await page.locator('.sidebar').locator('a[href="#/i/testpilot/statistics"]').click()
  await expect(page.locator('.statistics-toolbar-row')).toBeVisible()
  await expectContentFits(page)
  await page.goto('/#/i/testpilot/statistics?view=management')
  await expect(page.locator('.resource-management')).toBeVisible()
  await expectContentFits(page)

  await page.goto('/#/interface')
  await expect(page.locator('#ui-theme')).toBeVisible()
  await expectHorizontallyVisible(page.locator('#ui-theme'))
  await expectContentFits(page)
})

for (const position of ['left', 'right']) {
  test(`short desktop can reach both the dashboard and settings with a saved ${position} rail`, async ({page}) => {
    await page.addInitScript(side => {
      localStorage.setItem('azurpilot.layout.scheduler-position', side)
      localStorage.setItem('azurpilot.layout.rail-width', '500')
      localStorage.setItem('azurpilot.layout.sidebar-width', '350')
    }, position)
    await page.setViewportSize({width: 960, height: 480})
    await page.goto('/#/i/testpilot/overview')
    const dashboard = page.locator('.instance-page-grid')
    await expect(dashboard).toHaveAttribute('data-scheduler-position', position)
    await expect.poll(() => dashboard.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
    const monitor = dashboard.locator('.monitor-panel')
    await monitor.scrollIntoViewIfNeeded()
    await expect(monitor).toBeInViewport()
    await expectContentFits(page)

    await page.goto('/#/i/testpilot/task/Guild')
    const threshold = page.locator('[id="Guild.GuildOperation.JoinThreshold"]')
    await expect(threshold).toBeEditable()
    await threshold.scrollIntoViewIfNeeded()
    await expect(threshold).toBeInViewport()
    await expectHorizontallyVisible(threshold)
    await expectContentFits(page)
  })
}

test('task settings folds the directory when the sidebar takes more of the same viewport', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.layout.sidebar-width', '240')
    localStorage.setItem('azurpilot.layout.rail-width', '440')
  })
  await page.setViewportSize({width: 1320, height: 900})
  await page.goto('/#/i/testpilot/task/Guild')
  const config = page.locator('.task-config-modern')
  const directory = config.locator('.task-config-directory')
  const toggle = config.locator('.rail-fold-chip-directory')
  await expect(directory).toBeVisible()
  const handle = page.locator('.sidebar-resize-handle')
  await expect(handle).toBeVisible()
  const {x, y, width, height} = (await handle.boundingBox())!
  await page.mouse.move(x + width / 2, y + height / 2)
  await page.mouse.down()
  await page.mouse.move(x + width / 2 + 110, y + height / 2)
  await page.mouse.up()
  await expect(toggle).toBeVisible()
  await expect(directory).toBeHidden()
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(directory).toBeInViewport()
  await page.keyboard.press('Tab')
  await expect.poll(() => directory.evaluate(element => element.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(toggle).toBeFocused()
  await expectContentFits(page)
})

test('keyboard resizing starts at the visible scheduler width', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.layout.scheduler-position', 'left')
    localStorage.setItem('azurpilot.layout.sidebar-width', '350')
    localStorage.setItem('azurpilot.layout.rail-width', '500')
  })
  await page.setViewportSize({width: 1120, height: 810})
  await page.goto('/#/i/testpilot/overview')
  const rail = page.locator('.instance-page-grid .instance-page-rail-wrap')
  const handle = rail.getByRole('separator')
  await expect(handle).toBeVisible()
  const width = (await rail.boundingBox())!.width
  expect(width).toBeLessThan(500)
  await expect(handle).toHaveAttribute('aria-valuenow', String(Math.round(width)))
  await handle.press('ArrowLeft')
  await expect.poll(async () => (await rail.boundingBox())!.width).toBeLessThan(width)
})

test('short viewport scrolls shared dialogs to their last action', async ({page}) => {
  await page.setViewportSize({width: 640, height: 240})
  await page.goto('/#/configs')
  await page.getByRole('button', {name: '新建配置', exact: true}).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect.poll(() => dialog.evaluate(element => {
    const {top, bottom} = element.getBoundingClientRect()
    return top >= 0 && bottom <= innerHeight && element.scrollHeight > element.clientHeight
  })).toBe(true)

  const name = dialog.getByRole('textbox', {name: '实例名称', exact: true})
  await name.fill('responsive-draft')
  const submit = dialog.getByRole('button', {name: '创建实例', exact: true})
  await submit.scrollIntoViewIfNeeded()
  await expect(submit).toBeInViewport()
  await expect(submit).toBeEnabled()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

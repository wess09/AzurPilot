import { expect, test, type Page } from '@playwright/test'

test.use({viewport: {width: 375, height: 812}, isMobile: true, hasTouch: true})

test.beforeEach(async ({page}) => {
  await page.route('https://**/*', route => route.abort())
})

async function preferences(page: Page, theme: string, material = 'glass') {
  await page.addInitScript(({theme, material}) => {
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.theme', theme)
    localStorage.setItem('azurpilot.material', material)
    localStorage.removeItem('azurpilot.last-path')
  }, {theme, material})
}

async function expectNoPageOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(await page.locator('main').evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
}

for (const theme of ['legacy-light', 'legacy-dark']) {
  test(`移动端 ${theme} 统计分类完整显示，搜索与导出可用`, async ({page}, testInfo) => {
    await preferences(page, theme)
    await page.goto('/#/i/demo-main/statistics')
    const categories = page.locator('.statistics-category-control')
    const select = page.getByRole('combobox', {name: '统计分类', exact: true})
    await expect(select).toBeInViewport()
    await expect(categories).toBeHidden()
    const search = page.locator('.statistics-table .table-search').first()
    const heading = page.locator('.statistics-table .panel-heading').first()
    await expect(search).toBeVisible()
    const title = (await heading.locator('h3').boundingBox())!
    const input = (await search.locator('input').boundingBox())!
    const exportButton = (await heading.getByRole('button', {name: '导出明细', exact: true}).boundingBox())!
    expect(input.y).toBeGreaterThanOrEqual(title.y + title.height)
    expect(exportButton.width).toBeGreaterThan(40)
    await expectNoPageOverflow(page)

    await page.getByRole('button', {name: '样式编辑', exact: true}).click()
    const merge = page.locator('.statistics-category-picker').getByRole('button', {name: '合并单页', exact: true})
    await expect(merge).toBeVisible()
    await expectNoPageOverflow(page)
    await page.locator('.statistics-category-picker').screenshot({path: testInfo.outputPath('statistics-category-edit.png'), animations: 'disabled'})
    await page.getByRole('button', {name: '样式编辑', exact: true}).click()

    for (const width of [320, 375, 390, 950]) {
      await page.setViewportSize({width, height: 844})
      await select.scrollIntoViewIfNeeded()
      await expect(select).toBeInViewport({ratio: 1})
      const box = (await select.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
      expect(await select.locator('span').evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
      await expectNoPageOverflow(page)
    }
    await page.setViewportSize({width: 375, height: 812})
    await select.scrollIntoViewIfNeeded()
    await page.screenshot({path: testInfo.outputPath('statistics-mobile.png'), animations: 'disabled'})
    await page.locator('.statistics-category-picker').screenshot({path: testInfo.outputPath('statistics-category-picker.png'), animations: 'disabled'})
    await select.click()
    const labels = await page.getByRole('option').allTextContents()
    expect(labels.length).toBeGreaterThan(0)
    await page.keyboard.press('Escape')
    for (const label of labels) {
      await select.click()
      const option = page.getByRole('option', {name: label, exact: true})
      await option.scrollIntoViewIfNeeded()
      await expect(option).toBeInViewport({ratio: 1})
      expect(await option.locator('span[id]').evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
      await option.click()
      await expect(select).toHaveText(label)
    }
    await expectNoPageOverflow(page)
    await select.click()
    await page.getByRole('listbox').evaluate(element => {element.scrollTop = 0})
    await page.getByRole('listbox').screenshot({path: testInfo.outputPath('statistics-category-menu.png'), animations: 'disabled'})
    await page.keyboard.press('Escape')
    await page.setViewportSize({width: 1920, height: 1080})
    await expect(categories).toBeVisible()
    await expect(select).toBeHidden()
    await categories.screenshot({path: testInfo.outputPath('statistics-category-desktop.png'), animations: 'disabled'})
  })
}

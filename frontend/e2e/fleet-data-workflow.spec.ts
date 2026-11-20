/**
 * @fileoverview 舰船数据工作流用例：导入的重复舰船待确认后才生效，自动培养跟随已确认副本而草稿独立丢弃。
 */

import {expect, test} from '@playwright/test'
import {fleetAnalysisHash, rpc} from './fleet-helpers'

test.beforeEach(async ({page}, info) => {
  await page.addInitScript(language => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.language', language)
  }, info.title.endsWith('(en-US)') ? 'en-US' : 'zh-CN')
})

test('import keeps duplicate cards pending until confirmation', async ({page}, info) => {
  const instance = `import-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  await page.goto('/'); await rpc(page, 'instances.create', {name: instance}); await page.goto('about:blank'); await page.goto('/')
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=scan`)
  const file = page.locator('input[type=file][accept=".json,.csv,.xlsx"]')
  await expect(file).toBeEnabled()
  await file.setInputFiles({name: 'ships.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify([
    {name: '杜威', level: 100, rarity: 'R'}, {name: '杜威', level: 110, rarity: 'R'},
  ]))})
  await expect(page.getByRole('button', {name: /确认无歧义的新增和更新/})).toBeEnabled()
  const pending = await rpc(page, 'dock.report', {instance})
  expect(pending.ships).toHaveLength(0)
  expect(pending.pending_changes.filter(row => row.kind === 'ship')).toHaveLength(2)
  await expect(file).toBeDisabled()
  await page.getByRole('tab', {name: '我的舰船', exact: true}).click()
  await expect(page.getByRole('button', {name: /确认无歧义/})).toHaveCount(0)
  await page.getByRole('tab', {name: '扫描更新', exact: true}).click()
  await page.getByRole('button', {name: /确认无歧义的新增和更新/}).click()
  await expect(page.getByText('没有待确认差异', {exact: true})).toBeVisible()
  const saved = await rpc(page, 'dock.report', {instance})
  expect(saved.ships.map(row => row.level).sort()).toEqual([100, 110])
  expect(new Set(saved.ships.map(row => row.id)).size).toBe(2)
})

test('automatic cultivation follows committed copies while inline drafts persist and discard independently', async ({page}, info) => {
  const instance = `plan-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  await page.goto('/'); await rpc(page, 'instances.create', {name: instance}); await page.goto('about:blank'); await page.goto('/')
  const empty = await rpc(page, 'dock.report', {instance})
  const saved = await rpc(page, 'dock.patch', {instance, revision: empty.revision, changes: [
    {name: '杜威', group_type: 10102, level: 100, rarity: 'R', base_rarity: 'R', extra_exp: 0},
    {name: '杜威', group_type: 10102, level: 110, rarity: 'R', base_rarity: 'R', extra_exp: 0},
  ]})
  const [first, second] = saved.ships
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=mind`)
  const selected = page.getByRole('link', {name: '杜威', exact: true})
  await expect(page.getByText('计入 1 种舰船', {exact: false})).toBeVisible()
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await expect(selected).toHaveAttribute('href', fleetAnalysisHash(instance, 'data', second.id))
  await page.getByRole('tab', {name: '我的舰船', exact: true}).click()
  const level = page.getByLabel(`等级 · 杜威 #${first.id}`, {exact: true})
  await level.fill('112')
  expect((await rpc(page, 'dock.report', {instance})).ships).toEqual(saved.ships)
  await page.getByRole('tab', {name: '养成计算', exact: true}).click()
  await expect(selected).toHaveAttribute('href', fleetAnalysisHash(instance, 'data', second.id))
  await page.getByRole('tab', {name: '我的舰船', exact: true}).click()
  await expect(level).toHaveValue('112')
  await page.getByRole('button', {name: '放弃草稿', exact: true}).click()
  await expect(level).toHaveValue('100')
  await level.fill('112')
  await page.getByRole('button', {name: '保存', exact: true}).click()
  await expect(page.getByText('舰船数据已保存', {exact: true})).toBeVisible()
  const committed = await rpc(page, 'dock.report', {instance})
  expect(committed.ships.find(card => card.id === first.id)?.level).toBe(112)
  expect(committed.ships.find(card => card.id === second.id)?.level).toBe(110)
  await page.getByRole('tab', {name: '养成计算', exact: true}).click()
  await expect(selected).toHaveAttribute('href', fleetAnalysisHash(instance, 'data', first.id))
  await selected.click()
  await expect(page).toHaveURL(url => url.hash === fleetAnalysisHash(instance, 'data', first.id))
  await expect(page.getByRole('tab', {name: '我的舰船', exact: true})).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator(`#ledger-ship-${first.id}`)).toHaveClass(/ledger-highlight/)
  await expect(level).toHaveValue('112')
})

// CSS viewport sizes model the space available after browser zoom/reflow; they do
// not change Chromium's actual zoom level or device pixel ratio.
for (const language of ['zh-CN', 'en-US'] as const) {
  test(`fleet data remains operable at constrained viewport sizes (${language})`, async ({page}, info) => {
    const labels = language === 'zh-CN'
      ? {data: '我的舰船', technology: '舰队科技', mind: '养成计算', scan: '扫描更新', filters: '记录筛选'}
      : {data: 'My ships', technology: 'Fleet technology analysis', mind: 'Training calculator', scan: 'Scan update', filters: 'Filter records'}
    const instance = `reflow-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
    await page.goto('/')
    await rpc(page, 'instances.create', {name: instance})
    const empty = await rpc(page, 'dock.report', {instance})
    const saved = await rpc(page, 'dock.patch', {instance, revision: empty.revision, changes: Array.from({length: 24}, (_, index) =>
      ({name: '杜威', group_type: 10102, level: 90 + index, rarity: 'R', base_rarity: 'R', extra_exp: 0}))})
    await page.goto('about:blank')

    for (const viewport of [{width: 320, height: 800}, {width: 320, height: 568}, {width: 768, height: 640}, {width: 1024, height: 460}, {width: 1720, height: 440}]) {
      await page.setViewportSize(viewport)
      await page.goto(`/${fleetAnalysisHash(instance, 'data')}`)
      const panel = page.getByRole('tabpanel', {name: labels.data})
      const region = panel.getByRole('region', {name: labels.data, exact: true})
      await expect(region.locator('tbody tr')).toHaveCount(24)
      if (viewport.height <= 600) {
        // A short viewport should reach the first row within one viewport of scrolling.
        const firstRowBox = await region.locator('tbody tr').first().boundingBox()
        expect(firstRowBox!.y).toBeLessThan(viewport.height * 2)
      }
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
      await expect.poll(() => page.locator('main').evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
      const tablist = page.getByRole('tablist', {name: language === 'zh-CN' ? '舰船数据' : 'Ship data'})
      for (const tab of await tablist.getByRole('tab').all()) {
        const rect = await tab.boundingBox()
        expect(rect).not.toBeNull()
        expect(rect!.x).toBeGreaterThanOrEqual(0)
        expect(rect!.x + rect!.width).toBeLessThanOrEqual(viewport.width + 1)
      }
      const filters = panel.locator('summary').filter({hasText: labels.filters})
      const disclosure = filters.locator('..')
      const compact = viewport.width <= 480 || viewport.height <= 600
      if (compact) {
        await expect(disclosure).not.toHaveAttribute('open', '')
        await filters.click()
        await expect(disclosure).toHaveAttribute('open', '')
      }
      // All filter choices must fit their row after wrapping, including long translations.
      for (const row of await panel.locator('.ft-filter-row').all()) {
        const widths = await row.evaluate(element => ({client: element.clientWidth, scroll: element.scrollWidth}))
        expect(widths.scroll, `filter row: ${await row.innerText()}`).toBeLessThanOrEqual(widths.client + 1)
      }
      if (compact) await filters.click()
      const action = panel.getByRole('button', {name: labels.scan, exact: true})
      await action.scrollIntoViewIfNeeded()
      const actionBox = await action.boundingBox()
      expect(actionBox!.x).toBeGreaterThanOrEqual(0)
      expect(actionBox!.x + actionBox!.width).toBeLessThanOrEqual(viewport.width + 1)
      await expect(action).toBeEnabled()
      const firstRow = region.locator(`#ledger-ship-${saved.ships[0]!.id}`)
      await firstRow.scrollIntoViewIfNeeded()
      await expect(firstRow).toBeInViewport()
      await region.focus()
      await expect(region).toBeFocused()
      const horizontalOverflow = await region.evaluate(element => element.scrollWidth > element.clientWidth + 1)
      const horizontalControl = panel.locator('[data-slot="table-scroll-control"]')
      if (viewport.width === 320) expect(horizontalOverflow).toBe(true)
      if (horizontalOverflow) {
        await expect(horizontalControl).toBeVisible()
        await page.keyboard.press('ArrowRight')
        await expect.poll(() => region.evaluate(element => element.scrollLeft)).toBeGreaterThan(0)
        if (viewport.width === 320 && viewport.height === 800) {
          // A mouse can drag the visible thumb even when the OS hides its native scrollbar.
          await expect(horizontalControl).toHaveCSS('cursor', 'ew-resize')
          await horizontalControl.press('Home')
          await horizontalControl.scrollIntoViewIfNeeded()
          const {x, y, width, height} = (await horizontalControl.boundingBox())!
          await page.mouse.move(x + 12, y + height / 2)
          await page.mouse.down()
          await page.mouse.move(x + width * 0.8, y + height / 2, {steps: 8})
          await page.mouse.up()
          await expect.poll(() => region.evaluate(element => element.scrollLeft)).toBeGreaterThan(100)
          await horizontalControl.press('End')
          await expect.poll(() => region.evaluate(element => element.scrollWidth - element.clientWidth - element.scrollLeft)).toBeLessThanOrEqual(1)
          await region.evaluate(element => {element.scrollLeft = 0})
          await expect(horizontalControl).toHaveValue('0')
        }
      } else {
        await expect(horizontalControl).toHaveCount(0)
      }
      // At the top of the table, an upward wheel gesture continues to its ancestor.
      await region.evaluate(element => {element.scrollTop = 0})
      await region.hover()
      const before = await page.evaluate(() => Array.from(document.querySelectorAll('*'), el => el.scrollTop).reduce((a, b) => a + b, 0))
      expect(before).toBeGreaterThan(0)
      await page.mouse.wheel(0, -500)
      await expect.poll(() => page.evaluate(() => Array.from(document.querySelectorAll('*'), el => el.scrollTop).reduce((a, b) => a + b, 0))).toBeLessThan(before)
      await page.getByRole('tab', {name: labels.scan, exact: true}).click()
      const scan = page.getByRole('tabpanel', {name: labels.scan})
      await expect(scan).toBeVisible()
      await expect.poll(() => scan.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
      await expect.poll(() => page.locator('main').evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
    }

    // Radix's arrow-key navigation must still work when tabs wrap at narrow widths.
    await page.setViewportSize({width: 320, height: 800})
    await page.goto(`/${fleetAnalysisHash(instance, 'technology')}`)
    const technology = page.getByRole('tab', {name: labels.technology, exact: true})
    await technology.focus()
    await page.keyboard.press('ArrowRight')
    await expect(page.getByRole('tab', {name: labels.mind, exact: true})).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('tabpanel', {name: labels.mind}).getByRole('region', {name: labels.mind, exact: true})).toBeVisible()
    await page.keyboard.press('ArrowRight')
    await expect(page.getByRole('tab', {name: labels.scan, exact: true})).toHaveAttribute('aria-selected', 'true')
    await page.keyboard.press('ArrowRight')
    await expect(page.getByRole('tab', {name: labels.data, exact: true})).toHaveAttribute('aria-selected', 'true')
  })
}

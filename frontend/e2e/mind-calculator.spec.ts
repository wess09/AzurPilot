/**
 * @fileoverview 养成计算页用例：最高副本选取、边界费用、副本去重与分组排除，及移动端表格不溢出。
 */

import {expect as baseExpect, test, type Page} from '@playwright/test'
import {fleetAnalysisHash, rpc} from './fleet-helpers'
import type {Parameters} from '../src/api/generated'

// 隔离服务逐次运行真实 Python，等待完整数据就绪，不依赖定时刷新补齐。
const expect = baseExpect.configure({timeout: 15000})
test.setTimeout(60000)

async function seed(page: Page, name: string, ships: Parameters['dock.patch']['changes']) {
  await page.goto('/')
  await rpc(page, 'instances.create', {name})
  await page.goto('about:blank')
  await page.goto('/')
  const empty = await rpc(page, 'dock.report', {instance: name})
  return rpc(page, 'dock.patch', {instance: name, revision: empty.revision, changes: ships})
}
const ship = (level: number): Parameters['dock.patch']['changes'][number] => ({name: '企业', group_type: 10706, level, rarity: 'SSR', base_rarity: 'SSR', extra_exp: null})
test.beforeEach(async ({page}) => {
  await page.addInitScript(() => {localStorage.setItem('azurpilot.theme', 'light'); localStorage.setItem('azurpilot.language', 'zh-CN')})
})

test('cultivation automatically selects the highest copy and only shows mind and supplies', async ({page}, info) => {
  const instance = `calc-copies-${info.retry}`
  const saved = await seed(page, instance, [ship(110), ship(100)])
  await page.evaluate(instance => localStorage.setItem(`azurpilot.cultivation-plan.${instance}`, JSON.stringify({target: 125, ids: [], assumptions: []})), instance)
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=mind`)
  await expect(page.getByText('计入 1 种舰船', {exact: false})).toBeVisible()
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await expect(page.getByRole('link', {name: '企业', exact: true})).toHaveAttribute('href', fleetAnalysisHash(instance, 'data', saved.ships[0].id))
  await expect(page.locator('.cultivation-totals')).toContainText('心智单元')
  await expect(page.locator('.cultivation-totals')).toContainText('物资')
  await expect(page.getByRole('button', {name: '选择全部舰船', exact: true})).toHaveCount(0)
  await expect(page.getByLabel('目标等级', {exact: true})).toHaveCount(0)
  await expect(page.locator('.cultivation-calculator')).not.toContainText('经验')
  await expect(page.locator('input[type=file]')).toHaveCount(0)
  expect((await rpc(page, 'dock.report', {instance})).ships).toEqual(saved.ships)
})

test('fixed boundary fees ignore legacy trials and optional exclusions persist without changing facts', async ({page}, info) => {
  const instance = `calc-trial-${info.retry}`
  const saved = await seed(page, instance, [ship(100)])
  const id = saved.ships[0].id
  await page.evaluate(({instance, id}) => localStorage.setItem(`azurpilot.cultivation-auto.${instance}`, JSON.stringify({excluded_groups: [], assumptions: [{ship_id: id, level: 119, awakened_to: 120}]})), {instance, id})
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=mind&ships=${id}`)
  await expect(page.getByText('计入 1 种舰船', {exact: false})).toBeVisible()
  await expect(page.locator('.cultivation-totals strong')).toHaveText(['2,200', '22,000'])
  await expect(page.locator('.cultivation-calculator input[type=number], .cultivation-calculator select, .cultivation-calculator details')).toHaveCount(0)
  await page.reload()
  await expect(page.locator('.cultivation-totals strong')).toHaveText(['2,200', '22,000'])
  await page.getByLabel('参与计算 企业', {exact: true}).uncheck()
  await expect(page.getByText('计入 0 种舰船', {exact: false})).toBeVisible()
  await page.reload()
  await expect(page.getByText('计入 0 种舰船', {exact: false})).toBeVisible()
  await page.getByRole('checkbox', {name: '全选当前筛选'}).check()
  await expect(page.getByText('计入 1 种舰船', {exact: false})).toBeVisible()
  expect((await rpc(page, 'dock.report', {instance})).ships).toEqual(saved.ships)
})

for (const [level, mind, gold] of [[105, '2,000', '20,000'], [110, '1,600', '16,000'], [115, '1,000', '10,000']] as const) {
  test(`level ${level} includes its unpaid awakening boundary`, async ({page}, info) => {
    const instance = `calc-boundary-${level}-${info.retry}`
    const saved = await seed(page, instance, [ship(level)])
    await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=mind`)
    await expect(page.getByText('计入 1 种舰船', {exact: false})).toBeVisible()
    await expect(page.locator('.cultivation-totals strong')).toHaveText([mind, gold])
    expect((await rpc(page, 'dock.report', {instance})).ships).toEqual(saved.ships)
  })
}

test('current level120 copies suppress duplicates but only explicit merge preserves completion after retirement', async ({page}, info) => {
  const instance = `calc-revision-${info.retry}`
  let saved = await seed(page, instance, [ship(100)])
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=mind`)
  await expect(page.getByText('计入 1 种舰船', {exact: false})).toBeVisible()
  saved = await rpc(page, 'dock.patch', {instance, revision: saved.revision, changes: [ship(110)]})
  await page.getByRole('button', {name: '重新载入', exact: true}).click()
  await expect(page.getByRole('link', {name: '企业', exact: true})).toHaveAttribute('href', fleetAnalysisHash(instance, 'data', saved.ships[1].id))
  await expect(page.locator('tbody tr')).toHaveCount(1)
  saved = await rpc(page, 'dock.patch', {instance, revision: saved.revision, changes: [ship(120)]})
  await page.getByRole('button', {name: '重新载入', exact: true}).click()
  await expect(page.getByText('计入 0 种舰船', {exact: false})).toBeVisible()
  saved = await rpc(page, 'dock.patch', {instance, revision: saved.revision, changes: [{id: saved.ships[2].id, delete: true}]})
  await page.reload()
  await expect(page.getByText('计入 1 种舰船', {exact: false})).toBeVisible()
  await expect(page.getByRole('link', {name: '企业', exact: true})).toHaveAttribute('href', fleetAnalysisHash(instance, 'data', saved.ships[1].id))
  saved = await rpc(page, 'dock.patch', {instance, revision: saved.revision, changes: [ship(120)]})
  const completed = saved.ships.find(card => card.level === 120)
  expect(completed).toBeDefined()
  const tech = await rpc(page, 'fleetTech.report', {instance})
  await rpc(page, 'fleetTech.mergeShips', {instance, revision: tech.revision})
  const merged = await rpc(page, 'dock.report', {instance})
  await rpc(page, 'dock.patch', {instance, revision: merged.revision, changes: [{id: completed!.id, delete: true}]})
  await page.reload()
  await expect(page.getByText('计入 0 种舰船', {exact: false})).toBeVisible()
  await expect(page.getByText('当前没有需要计算120级养成费用的舰船。', {exact: true})).toBeVisible()
})

test('group exclusions follow the highest copy and remain isolated between instances', async ({page}, info) => {
  const instance = `calc-excluded-${info.retry}`, other = `calc-isolated-${info.retry}`
  const saved = await seed(page, instance, [ship(100)])
  await seed(page, other, [ship(110)])
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=mind`)
  await expect(page.getByLabel('参与计算 企业', {exact: true})).toBeChecked()
  await page.getByLabel('参与计算 企业', {exact: true}).uncheck()
  await expect(page.getByText('计入 0 种舰船', {exact: false})).toBeVisible()
  const updated = await rpc(page, 'dock.patch', {instance, revision: saved.revision, changes: [ship(110)]})
  await page.getByRole('button', {name: '重新载入', exact: true}).click()
  await expect(page.getByRole('link', {name: '企业', exact: true})).toHaveAttribute('href', fleetAnalysisHash(instance, 'data', updated.ships[1].id))
  await expect(page.getByLabel('参与计算 企业', {exact: true})).not.toBeChecked()
  await page.goto(`/#/i/${other}/task/FleetAnalysis?tab=mind`)
  await expect(page.getByText('计入 1 种舰船', {exact: false})).toBeVisible()
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=mind`)
  await expect(page.getByText('计入 0 种舰船', {exact: false})).toBeVisible()
  expect((await rpc(page, 'dock.report', {instance})).ships).toEqual(updated.ships)
  expect(await page.evaluate(instance => JSON.parse(localStorage.getItem(`azurpilot.cultivation-auto.${instance}`)!), instance)).toEqual({excluded_groups: [10706]})
})

test('cultivation mobile page contains horizontal tables without overflowing viewport', async ({page}, info) => {
  const instance = `calc-mobile-${info.retry}`
  await seed(page, instance, [ship(100)])
  await page.setViewportSize({width: 390, height: 844})
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=mind`)
  await expect(page.getByText('计入 1 种舰船', {exact: false})).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await page.screenshot({path: info.outputPath('cultivation-mobile.png'), fullPage: true})
})

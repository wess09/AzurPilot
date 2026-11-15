/**
 * @fileoverview 舰队科技页用例：Tempesta 舰船前后排约束、里程碑依赖预览与手动记录显式合并的留存行为。
 */

import {expect as baseExpect, test} from '@playwright/test'
import {rpc} from './fleet-helpers'

const expect = baseExpect.configure({timeout: 15000})
test.setTimeout(60000)

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => {localStorage.setItem('azurpilot.theme', 'light'); localStorage.setItem('azurpilot.language', 'zh-CN')})
})

test('Tempesta sailing ships respect front and back positions', async ({page}, info) => {
  const instance = `tech-position-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  await page.goto('/'); await rpc(page, 'instances.create', {name: instance}); await page.goto('about:blank'); await page.goto('/')
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=technology`)
  await page.getByRole('button', {name: '飓风', exact: true}).click()
  const type = page.locator('.ft-filter-row').first()
  const rows = page.locator('.ft-table-wrap tbody tr[data-group]')
  const sailingS = ['960001:皇家财富号', '960004:玛丽·西莱斯特号', '960005:维达号', '960009:和睦号', '960011:海豚号', '960016:冒险号', '960018:铁角号']
  const sailingV = ['960003:金鹿号', '960006:加里冒险号', '960008:幻想号', '960010:朴茨茅斯冒险号', '960013:莱姆号', '960015:皇家詹姆斯号', '960017:水星号', '960020:长蛇号']
  const sailingM = ['960002:圣马丁号', '960007:冈依沙瓦号', '960012:安妮女王复仇号', '960014:珍珠号', '960019:塞利米耶号', '960021:雷伊尔·贝号']
  async function expectShips(expected: string[]) {
    await expect.poll(() => rows.evaluateAll(elements => elements.map(element => `${element.getAttribute('data-group')}:${element.querySelector('.ft-name')?.textContent?.trim()}`).sort())).toEqual([...expected].sort())
  }
  await type.getByRole('button', {name: '前排先锋', exact: true}).click()
  await expectShips(sailingV)
  await type.getByRole('button', {name: '前排先锋', exact: true}).click()
  await type.getByRole('button', {name: '后排主力', exact: true}).click()
  await expectShips(sailingM)
  await type.getByRole('button', {name: '后排主力', exact: true}).click()
  await type.getByRole('button', {name: '风帆', exact: true}).click()
  await expectShips([...sailingS, ...sailingV, ...sailingM])
})

test('inline milestones preview dependency changes and save together independently of holdings', async ({page}, info) => {
  const instance = `tech-facts-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  await page.goto('/'); await rpc(page, 'instances.create', {name: instance}); await page.goto('about:blank'); await page.goto('/')
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=technology&group=10102`)
  await page.getByLabel('搜索舰名', {exact: true}).fill('杜威')
  const row = page.locator('.ft-table-wrap tbody tr[data-group="10102"]')
  const milestone = (stage: string, state: string) => row.getByRole('button', {name: `杜威 · ${stage} · ${state}`, exact: true})
  await expect(milestone('Lv.120', '未完成')).toBeDisabled()
  await page.getByRole('button', {name: '记录编辑模式', exact: true}).click()
  await milestone('Lv.120', '未完成').click()
  for (const stage of ['获得', '满星', 'Lv.120']) await expect(milestone(stage, '已完成')).toHaveAttribute('aria-pressed', 'true')
  const before = await rpc(page, 'fleetTech.report', {instance})
  expect(before.ships.find(ship => ship.group_type === 10102)).toMatchObject({owned: false, full_star: false, lv120: false})
  await expect(page.getByRole('button', {name: '合并舰船数据', exact: true})).toBeDisabled()
  await page.getByRole('button', {name: '保存', exact: true}).click()
  await expect(page.locator('.ft-modified')).toHaveCount(0)
  await expect(page.getByRole('button', {name: '保存', exact: true})).toBeDisabled()
  const saved = await rpc(page, 'fleetTech.report', {instance})
  expect(saved.ships.find(ship => ship.group_type === 10102)).toMatchObject({owned: true, full_star: true, lv120: true, current_count: 0, points: 15})
  await milestone('满星', '已完成').click()
  await expect(milestone('Lv.120', '未完成')).toHaveAttribute('aria-pressed', 'false')
  await expect(milestone('获得', '已完成')).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', {name: '放弃草稿', exact: true}).click()
  await expect(milestone('Lv.120', '已完成')).toBeVisible()
  await milestone('获得', '已完成').click()
  for (const stage of ['获得', '满星', 'Lv.120']) await expect(milestone(stage, '未完成')).toHaveAttribute('aria-pressed', 'false')
  await page.getByRole('button', {name: '保存', exact: true}).click()
  await expect(page.locator('.ft-modified')).toHaveCount(0)
  await expect(page.getByRole('button', {name: '保存', exact: true})).toBeDisabled()
  await page.reload()
  await expect(milestone('Lv.120', '未完成')).toBeVisible()
  const cleared = await rpc(page, 'fleetTech.report', {instance})
  expect(cleared.ships.find(ship => ship.group_type === 10102)).toMatchObject({owned: false, full_star: false, lv120: false, points: 0})
})

test('manual milestones survive current copies until explicit merge and remain after retirement', async ({page}, info) => {
  const instance = `tech-retire-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  await page.goto('/'); await rpc(page, 'instances.create', {name: instance}); await page.goto('about:blank'); await page.goto('/')
  const empty = await rpc(page, 'dock.report', {instance})
  const dock = await rpc(page, 'dock.patch', {instance, revision: empty.revision, changes: [
    {name: '杜威', group_type: 10102, level: 120, full_star: true, rarity: 'R', base_rarity: 'R', extra_exp: 0},
  ]})
  const card = dock.ships[0]
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=technology&group=10102`)
  await page.getByLabel('搜索舰名', {exact: true}).fill('杜威')
  const row = page.locator('.ft-table-wrap tbody tr[data-group="10102"]')
  const milestone = (stage: string, state: string) => row.getByRole('button', {name: `杜威 · ${stage} · ${state}`, exact: true})
  await expect(milestone('Lv.120', '已完成')).toBeVisible()
  await page.getByRole('button', {name: '记录编辑模式', exact: true}).click()
  await milestone('获得', '已完成').click()
  await page.getByRole('button', {name: '保存', exact: true}).click()
  await expect(page.locator('.ft-modified')).toHaveCount(0)
  await expect(page.getByRole('button', {name: '保存', exact: true})).toBeDisabled()
  await page.reload()
  await expect(milestone('Lv.120', '未完成')).toBeVisible()
  const corrected = await rpc(page, 'fleetTech.report', {instance})
  expect(corrected.ships.find(ship => ship.group_type === 10102)).toMatchObject({owned: false, full_star: false, lv120: false, current_count: 1, current_level: 120})
  await page.getByRole('button', {name: '合并舰船数据', exact: true}).click()
  await expect(milestone('Lv.120', '已完成')).toBeVisible()
  // 用刷新验证 mock 持久化了这次显式合并，而不只是返回一次预览。
  await page.reload()
  await expect(milestone('Lv.120', '已完成')).toBeVisible()
  const current = await rpc(page, 'dock.report', {instance})
  await rpc(page, 'dock.patch', {instance, revision: current.revision, changes: [{id: card.id, delete: true}]})
  await page.reload()
  const retired = await rpc(page, 'fleetTech.report', {instance})
  expect(retired.ships.find(ship => ship.group_type === 10102)).toMatchObject({owned: true, full_star: true, lv120: true, current_count: 0, points: 15})
  await expect(page.getByRole('button', {name: '记录编辑模式', exact: true})).toHaveAttribute('aria-pressed', 'true')
  await milestone('Lv.120', '已完成').click()
  await expect(milestone('获得', '已完成')).toBeVisible()
  await expect(milestone('满星', '已完成')).toBeVisible()
  await page.getByRole('button', {name: '保存', exact: true}).click()
  await expect(page.locator('.ft-modified')).toHaveCount(0)
  await expect(page.getByRole('button', {name: '保存', exact: true})).toBeDisabled()
  await page.getByRole('button', {name: '合并舰船数据', exact: true}).click()
  await page.reload()
  const after = await rpc(page, 'fleetTech.report', {instance})
  expect(after.ships.find(ship => ship.group_type === 10102)).toMatchObject({owned: true, full_star: true, lv120: false, points: 10})
})

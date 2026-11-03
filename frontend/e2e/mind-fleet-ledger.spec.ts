import {expect, test} from '@playwright/test'
import {readFile} from 'node:fs/promises'
import {rpc} from './fleet-helpers'
import type {Parameters} from '../src/api/generated'
import type {DockReport} from '../src/api/types'

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'plain')
    localStorage.setItem('azurpilot.language', 'zh-CN')
  })
})

test('scan page exports the latest ship JSON without accepting pending changes', async ({page}, info) => {
  const instance = `export-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  await page.goto('/'); await rpc(page, 'instances.create', {name: instance}); await page.goto('about:blank')
  const latest: DockReport = {instance, revision: 'latest', updated_at: '2026-11-03T12:00:00',
    min_level: 1, max_level: 125, complete: false, review_count: 1, source: 'ledger', scan_range: {min_level: 1, max_level: 125},
    ships: [
      {id: 11, name: '杜威', group_type: 10102, level: 110, rarity: 'R', base_rarity: 'R', extra_exp: null, full_star: false, form: 'base', review: true, source: '扫描待核对'},
      {id: 12, name: '杜威', group_type: 10102, level: 100, rarity: 'R', base_rarity: 'R', extra_exp: 0, full_star: true, form: null, review: false, source: 'manual'},
    ], pending_revision: 'pending', pending_changes: [
      {id: 'ship:1', kind: 'ship', operation: 'add', ship_id: null, group_type: 10103, name: '卡辛', before: null,
        after: {name: '卡辛', level: 90, extra_exp: null, review: true}, fields: ['name', 'level'], candidates: []},
    ], pending_read: {source: 'scan', updated_at: '2026-11-03T12:00:00', observed_count: 3, review_count: 2, complete: false}}
  const initial = {...latest, revision: 'old', ships: [{...latest.ships[0]!, level: 100}]}
  const methods: string[] = []
  let reads = 0
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      if (request.type === 'request') methods.push(request.method)
      if (request.method !== 'dock.report') {server.send(message); return}
      socket.send(JSON.stringify({v: 1, type: 'response', id: request.id, ok: true, result: ++reads === 1 ? initial : latest}))
    })
    server.onMessage(message => socket.send(message))
  })
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=scan`)
  const button = page.getByRole('button', {name: '导出舰船 JSON', exact: true})
  await expect(button).toBeEnabled()
  const start = methods.length
  const downloadPromise = page.waitForEvent('download')
  await button.click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(new RegExp(`^${instance}-ships-.*\\.json$`))
  const payload = JSON.parse(await readFile((await download.path())!, 'utf8'))
  expect(payload).toEqual({version: 1, exported_at: expect.any(String), ...latest})
  expect(Number.isNaN(Date.parse(payload.exported_at))).toBe(false)
  expect(payload.ships).toHaveLength(2)
  expect(payload.pending_changes).toHaveLength(1)
  expect(methods.slice(start)).toEqual(['dock.report'])
  await expect(page.getByText('已确认舰船: 2 · 待确认差异: 1', {exact: true})).toBeVisible()
  await expect(page.getByRole('button', {name: '接受 ship:1', exact: true})).toBeVisible()
  await page.screenshot({path: info.outputPath('ship-json-export.png'), fullPage: true})
})

test('four flat pages preserve per-copy edits and never start a scan on navigation', async ({page}, info) => {
  const instance = `four-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  const methods: string[] = []
  page.on('websocket', socket => socket.on('framesent', ({payload}) => {const request = JSON.parse(String(payload)); if (request.type === 'request') methods.push(request.method)}))
  await page.goto('/')
  await rpc(page, 'instances.create', {name: instance})
  const empty = await rpc(page, 'dock.report', {instance})
  const saved = await rpc(page, 'dock.patch', {instance, revision: empty.revision, changes: [
    {name: '杜威', group_type: 10102, level: 100, rarity: 'R', base_rarity: 'R', extra_exp: null},
    {name: '杜威', group_type: 10102, level: 100, rarity: 'R', base_rarity: 'R', extra_exp: 0},
  ]})
  const [first, second] = saved.ships
  // Fixtures are seeded through an external socket; reload the app's instance list.
  await page.goto('about:blank')
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=data&ship=${second.id}`)
  await expect(page.getByRole('tab')).toHaveCount(4)
  await expect(page.locator(`#ledger-ship-${second.id}`)).toHaveClass(/ledger-highlight/)
  await expect(page.getByLabel(`等级 · 杜威 #${second.id}`, {exact: true})).toHaveValue('100')
  await expect(page.getByRole('button', {name: '保存', exact: true})).toHaveCount(1)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const level = page.getByLabel(`等级 · 杜威 #${first.id}`, {exact: true})
  await expect(level).toHaveValue('100')
  await level.fill('110')
  await page.getByRole('button', {name: '保存', exact: true}).click()
  await expect(page.getByText('舰船数据已保存', {exact: true})).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.reload()
  const reloaded = await rpc(page, 'dock.report', {instance})
  expect(reloaded.ships.find(row => row.id === first.id)).toMatchObject({level: 110, extra_exp: null})
  expect(reloaded.ships.find(row => row.id === second.id)).toMatchObject({level: 100, extra_exp: 0})
  const navigationStart = methods.length
  for (const tab of ['舰队科技', '养成计算', '我的舰船']) {
    await page.getByRole('tab', {name: tab, exact: true}).click()
    await expect(page.getByRole('button', {name: '扫描船坞', exact: true})).toHaveCount(0)
    await expect(page.locator('input[type=file]')).toHaveCount(0)
    await expect(page.getByRole('tabpanel')).toHaveCount(1)
  }
  await page.getByRole('tab', {name: '扫描更新', exact: true}).click()
  await expect(page.getByRole('button', {name: '扫描船坞', exact: true})).toBeVisible()
  expect(methods.slice(navigationStart).filter(method => ['tasks.run', 'dock.importLegacy', 'dock.patch', 'dock.review', 'fleetTech.patch', 'fleetTech.mergeShips'].includes(method))).toEqual([])
})

test('safe batch excludes removals and unresolved duplicates', async ({page}, info) => {
  const instance = `safe-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  await page.goto('/'); await rpc(page, 'instances.create', {name: instance}); await page.goto('about:blank')
  const card = (id: number, level: number) => ({id, name: '杜威', level, group_type: 10102, rarity: 'R', base_rarity: 'R', extra_exp: null, review: false, source: 'manual'})
  const decisions: Parameters['dock.review']['decisions'][] = []
  const report: DockReport = {instance, revision: 'a'.repeat(64), ships: [card(10, 100), card(11, 100)], legacy_imported: false, min_level: 1, max_level: 125, updated_at: '', complete: true, review_count: 0, source: 'manual', pending_revision: 'b'.repeat(64), pending_changes: [
    {id: 'update', kind: 'ship', operation: 'update', ship_id: 10, name: '杜威', before: card(10, 100), after: card(10, 110), candidates: [], group_type: 10102, fields: ['level']},
    {id: 'remove', kind: 'ship', operation: 'remove', ship_id: 11, name: '杜威', before: card(11, 100), after: null, candidates: [], group_type: 10102, fields: []},
    {id: 'resolve', kind: 'ship', operation: 'resolve', ship_id: null, name: '杜威', before: null, after: card(0, 120), candidates: [card(10, 100), card(11, 100)], group_type: 10102, fields: ['level']},
  ]}
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      if (!['dock.report', 'dock.review'].includes(request.method)) {server.send(message); return}
      if (request.method === 'dock.review') {
        const review = request.params as Parameters['dock.review']
        decisions.push(review.decisions)
        for (const decision of review.decisions) report.pending_changes = report.pending_changes.filter(row => row.id !== decision.id)
      }
      socket.send(JSON.stringify({v: 1, type: 'response', id: request.id, ok: true, result: report}))
    })
    server.onMessage(message => socket.send(message))
  })
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=data`)
  await expect(page.getByRole('button', {name: '接受 remove', exact: true})).toHaveCount(0)
  await page.getByRole('tab', {name: '扫描更新', exact: true}).click()
  await expect(page.getByRole('button', {name: '接受 resolve', exact: true})).toBeDisabled()
  await page.getByRole('button', {name: /确认无歧义的新增和更新/}).click()
  await expect(page.getByRole('button', {name: /确认无歧义的新增和更新/})).toBeDisabled()
  expect(decisions).toEqual([[{id: 'update', accept: true}]])
  await page.getByRole('button', {name: '接受 remove', exact: true}).click()
  expect(decisions).toHaveLength(1)
  await page.getByRole('button', {name: '接受 remove', exact: true}).click()
  await expect(page.getByRole('button', {name: '接受 remove', exact: true})).toHaveCount(0)
  expect(decisions[1]).toEqual([{id: 'remove', accept: true}])
  await page.getByLabel('目标卡片 resolve', {exact: true}).selectOption('11')
  await page.getByRole('button', {name: '接受 resolve', exact: true}).click()
  expect(decisions[2]).toEqual([{id: 'resolve', accept: true, ship_id: 11}])
})

test('unique view and page choices persist while data only refreshes on request', async ({page}, info) => {
  test.setTimeout(60000)
  const instance = `prefs-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  const reports: string[] = []
  page.on('websocket', socket => socket.on('framesent', ({payload}) => {const request = JSON.parse(String(payload)); if (request.type === 'request' && request.method === 'dock.report') reports.push(request.method)}))
  await page.goto('/'); await rpc(page, 'instances.create', {name: instance})
  const empty = await rpc(page, 'dock.report', {instance})
  const saved = await rpc(page, 'dock.patch', {instance, revision: empty.revision, changes: [
    {name: '杜威', group_type: 10102, level: 100, rarity: 'R', base_rarity: 'R'},
    {name: '杜威', group_type: 10102, level: 110, rarity: 'R', base_rarity: 'R'},
    {name: '卡辛', group_type: 10103, level: 99, rarity: 'R', base_rarity: 'R'},
  ]})
  expect(saved.ships[0]!.full_star).toBe(true)
  await page.goto('about:blank'); await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=data`)
  await expect(page.getByRole('tab')).toHaveText(['舰队科技', '养成计算', '扫描更新', '我的舰船'])
  await expect(page.locator('.fleet-ledger tbody tr')).toHaveCount(3)
  await page.getByRole('button', {name: '去重后舰船', exact: true}).click()
  await expect(page.locator('.fleet-ledger tbody tr')).toHaveCount(2)
  await expect(page.locator(`#ledger-ship-${saved.ships[0]!.id}`)).toHaveCount(0)
  await page.getByRole('searchbox').fill('杜威')
  await page.getByLabel('最低等级', {exact: true}).fill('100')
  await page.getByRole('columnheader', {name: '等级', exact: true}).getByRole('button').click()
  await page.getByRole('tab', {name: '舰队科技', exact: true}).click()
  await page.getByRole('tabpanel', {name: '舰队科技', exact: true}).locator('.ft-search input').fill('卡辛')
  await page.getByRole('tab', {name: '我的舰船', exact: true}).click()
  await expect(page.getByRole('tabpanel', {name: '我的舰船', exact: true}).getByRole('searchbox')).toHaveValue('杜威')
  await expect(page.getByLabel('最低等级', {exact: true})).toHaveValue('100')
  await expect(page.getByRole('button', {name: '去重后舰船', exact: true})).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('columnheader', {name: '等级', exact: true})).toHaveAttribute('aria-sort', 'descending')
  await page.reload()
  await expect(page.getByRole('searchbox')).toHaveValue('杜威')
  await page.screenshot({path: info.outputPath('ship-data-desktop.png'), fullPage: true})
  reports.length = 0
  await rpc(page, 'dock.patch', {instance, revision: saved.revision, changes: [{id: saved.ships[1]!.id, level: 121}]})
  // 覆盖原先两个5秒刷新周期，确认外部修改不会自动刷新当前页面。
  await page.waitForTimeout(11000)
  await expect(page.getByLabel(`等级 · 杜威 #${saved.ships[1]!.id}`, {exact: true})).toHaveValue('110')
  expect(reports).toHaveLength(0)
  await page.getByRole('button', {name: '重新载入', exact: true}).click()
  await expect(page.getByLabel(`等级 · 杜威 #${saved.ships[1]!.id}`, {exact: true})).toHaveValue('121')
  expect(reports).toHaveLength(1)
  await page.getByRole('tab', {name: '舰队科技', exact: true}).click()
  await expect(page.getByRole('tabpanel', {name: '舰队科技', exact: true}).locator('.ft-search input')).toHaveValue('卡辛')
  await page.getByRole('tab', {name: '扫描更新', exact: true}).click()
  await page.getByLabel('最低扫描等级', {exact: true}).fill('70')
  await page.goto(`/#/i/${instance}/task/FleetAnalysis`)
  await expect(page.getByRole('tab', {name: '扫描更新', exact: true})).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByLabel('最低扫描等级', {exact: true})).toHaveValue('70')
})

test('unresolved copies can confirm a candidate without guessing or changing another copy', async ({page}, info) => {
  test.setTimeout(60000)
  const instance = `identity-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  await page.goto('/'); await rpc(page, 'instances.create', {name: instance})
  const empty = await rpc(page, 'dock.report', {instance})
  const saved = await rpc(page, 'dock.patch', {instance, revision: empty.revision, changes: [
    {name: '约克', group_type: null, level: 120, review: true, rarity: 'SR', base_rarity: 'SR'},
    {name: '约克', group_type: null, level: 120, review: true, rarity: 'SR', base_rarity: 'SR'},
    {name: '北安普敦II', group_type: null, level: 120, review: true, rarity: 'SSR', base_rarity: 'SSR'},
  ]})
  const [first, second, northampton] = saved.ships
  await page.goto('about:blank'); await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=data`)
  const review = page.getByLabel(`需要核对 · 约克 #${first!.id}`, {exact: true})
  await expect(review).toBeEnabled()
  await review.click()
  await expect(review).toBeChecked()
  await expect(page.getByRole('alert')).toContainText('请先在舰名下选择')
  await page.getByLabel(`确认舰船身份 · 约克 #${first!.id}`, {exact: true}).selectOption({label: '约克 · 铁血 · 重巡 · 546'})
  await expect(page.locator(`#ledger-ship-${first!.id} input[type=checkbox]`)).not.toBeChecked()
  await page.getByLabel(`需要核对 · 北安普敦II #${northampton!.id}`, {exact: true}).uncheck()
  await expect(page.locator(`#ledger-ship-${northampton!.id} input[type=checkbox]`)).not.toBeChecked()
  await page.getByRole('button', {name: '保存', exact: true}).click()
  await expect(page.getByText('舰船数据已保存', {exact: true})).toBeVisible()
  const confirmed = await rpc(page, 'dock.report', {instance})
  expect(confirmed.ships.find(row => row.id === first!.id)).toMatchObject({group_type: 40311, review: false, level: 120})
  expect(confirmed.ships.find(row => row.id === second!.id)).toEqual(second)
  expect(confirmed.ships.find(row => row.id === northampton!.id)).toMatchObject({review: false, full_star: true})
  await page.setViewportSize({width: 390, height: 844})
  await expect(page.locator('.mobile-close')).toBeHidden()
  await expect(page.getByRole('button', {name: '去重后舰船', exact: true})).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await page.screenshot({path: info.outputPath('ship-data-mobile.png'), fullPage: true})
})

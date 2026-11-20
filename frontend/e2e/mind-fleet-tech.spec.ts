/**
 * @fileoverview 舰队科技页用例：Tempesta 舰船前后排约束、里程碑依赖预览与手动记录显式合并的留存行为。
 */

import {expect as baseExpect, test} from '@playwright/test'
import {rpc} from './fleet-helpers'
import {routeRpc} from './rpc-route'

const expect = baseExpect.configure({timeout: 15000})
test.setTimeout(60000)
test.use({launchOptions: {ignoreDefaultArgs: ['--hide-scrollbars']}})

test.beforeEach(async ({page}, info) => {
  await page.addInitScript(({language, theme}) => {
    localStorage.setItem('azurpilot.theme', theme)
    localStorage.setItem('azurpilot.language', language)
  }, {language: info.title.endsWith('(en-US)') ? 'en-US' : 'zh-CN', theme: info.title.includes('dark theme') ? 'modern-dark' : 'modern-light'})
})

for (const {language, width} of [{language: 'zh-CN', width: 1280}, {language: 'en-US', width: 1440}]) {
  test(`technology columns fit available width before enabling horizontal scroll (${language})`, async ({page}, info) => {
    await page.setViewportSize({width, height: 750})
    const instance = `tech-fit-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
    await page.goto('/')
    await rpc(page, 'instances.create', {name: instance})
    await page.goto('about:blank')
    await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=technology`)

    const surface = page.locator('.ft-technology-table')
    const region = surface.getByRole('region')
    const control = surface.locator('[data-slot=table-scroll-control]')
    const lastHeader = region.locator('thead tr:first-child th').last()
    const overflow = () => region.evaluate(element => element.scrollWidth - element.clientWidth)
    await expect(region.locator('tbody tr').first()).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('lang', language)
    await expect.poll(overflow).toBe(0)
    await expect(control).toHaveCount(0)
    await lastHeader.scrollIntoViewIfNeeded()
    await expect(lastHeader).toBeInViewport()
    if (language === 'zh-CN') {
      for (const label of ['编号', '舰种', '合计']) {
        const text = region.getByRole('button', {name: label, exact: true}).locator('span').first()
        await expect(text).toHaveCSS('white-space', 'nowrap')
      }
    }

    await page.setViewportSize({width: 390, height: 600})
    await expect.poll(overflow).toBeGreaterThan(100)
    await control.press('End')
    await expect(lastHeader).toBeInViewport()
    await page.setViewportSize({width, height: 750})
    await expect.poll(overflow).toBe(0)
    await expect(control).toHaveCount(0)
    await expect.poll(() => region.evaluate(element => element.scrollLeft)).toBe(0)
  })
}

test('technology milestone data stays legible in dark theme outside edit mode', async ({page}, info) => {
  const instance = `tech-contrast-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  await page.goto('/')
  await rpc(page, 'instances.create', {name: instance})
  const original = await rpc(page, 'fleetTech.report', {instance})
  await rpc(page, 'fleetTech.patch', {instance, revision: original.revision, changes: [{group_type: 10102, owned: true, full_star: true, lv120: true, awakening_pending: true}], nations: {}})
  await page.goto('about:blank')
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=technology`)
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'modern-dark')
  const row = page.locator('#technology-10102')
  await expect(row.locator('.ft-marked').first()).toBeVisible()
  await expect(row.locator('.ft-point button').first()).toBeDisabled()
  const ratios = await row.locator('td:is(.ft-marked,.ft-state-finished,.ft-awakening-pending)').evaluateAll(cells => {
    const context = document.createElement('canvas').getContext('2d', {willReadFrequently: true})!
    const luminance = (color: string) => {
      context.clearRect(0, 0, 1, 1)
      context.fillStyle = color
      context.fillRect(0, 0, 1, 1)
      return [...context.getImageData(0, 0, 1, 1).data].slice(0, 3).map(value => {
        const channel = value / 255
        return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4
      }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0)
    }
    return cells.flatMap(cell => {
      const background = luminance(getComputedStyle(cell).backgroundColor)
      return [cell.querySelector('button,a') ?? cell, ...cell.querySelectorAll('.ft-mark')].map(text => {
        const foreground = luminance(getComputedStyle(text).color)
        return (Math.max(background, foreground) + .05) / (Math.min(background, foreground) + .05)
      })
    })
  })
  expect(ratios.length).toBeGreaterThan(5)
  for (const ratio of ratios) expect(ratio).toBeGreaterThanOrEqual(4.5)
  await expect(row.locator('.ft-point button').first()).toHaveCSS('opacity', '1')
})

test('sticky technology header paints its own separators over scrolled rows', async ({page}, info) => {
  await page.setViewportSize({width: 1050, height: 780})
  const instance = `tech-header-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  await page.goto('/')
  await rpc(page, 'instances.create', {name: instance})
  await page.goto('about:blank')
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=technology`)

  const region = page.getByRole('region', {name: '舰队科技', exact: true})
  const header = region.locator('thead')
  await header.scrollIntoViewIfNeeded()
  const clip = await region.evaluate(element => {
    element.scrollTop = 113
    element.scrollLeft = 80
    const regionBounds = element.getBoundingClientRect()
    const headerBounds = element.querySelector('thead')!.getBoundingClientRect()
    const x = Math.ceil(regionBounds.left), y = Math.ceil(headerBounds.top)
    return {x, y, width: Math.floor(regionBounds.right) - x, height: Math.floor(headerBounds.bottom) - y}
  })
  const original = await page.screenshot({clip})
  await page.addStyleTag({content: '.fleet-technology tbody td { background: magenta !important; }'})
  const overRecoloredRows = await page.screenshot({clip})
  expect(overRecoloredRows.equals(original)).toBe(true)
  for (const cell of await header.locator('th').all()) {
    await expect(cell).toHaveCSS('border-bottom-width', '1px')
    await expect(cell).toHaveCSS('border-bottom-style', 'solid')
  }
})

test('wheel and drag reach both ends while the ship name stays in view on wider tables', async ({page}, info) => {
  await page.setViewportSize({width: 1050, height: 780})
  const instance = `tech-scroll-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  await page.goto('/')
  await rpc(page, 'instances.create', {name: instance})
  await page.goto('about:blank')
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=technology`)

  const region = page.getByRole('region', {name: '舰队科技', exact: true})
  const horizontal = page.locator('.fleet-technology [data-slot=table-scroll-control]')
  const name = region.locator('thead th').filter({hasText: '名称'})
  const lastColumn = region.getByRole('columnheader').filter({hasText: '满级待觉醒'})
  const main = page.locator('main')
  const innerScroll = () => region.evaluate(element => element.scrollTop)
  const pageScroll = () => main.evaluate(element => element.scrollTop)
  await region.scrollIntoViewIfNeeded()
  await expect(horizontal).toBeInViewport()
  await expect(name).toHaveCSS('position', 'sticky')
  await region.hover({position: {x: 240, y: 130}})
  const pageBeforeWheel = await pageScroll()
  await page.mouse.wheel(0, 180)
  await expect.poll(innerScroll).toBeGreaterThan(100)
  expect(await pageScroll()).toBe(pageBeforeWheel)

  await horizontal.press('Home')
  const drag = (await horizontal.boundingBox())!
  await page.mouse.move(drag.x + 15, drag.y + drag.height / 2)
  await page.mouse.down()
  await page.mouse.move(drag.x + drag.width * 0.75, drag.y + drag.height / 2, {steps: 8})
  await page.mouse.up()
  await expect.poll(() => region.evaluate(element => element.scrollLeft / (element.scrollWidth - element.clientWidth))).toBeGreaterThan(0.5)
  await expect.poll(async () => (await name.boundingBox())!.x - (await region.boundingBox())!.x).toBeCloseTo(0, 0)
  await horizontal.press('End')
  await expect.poll(() => region.evaluate(element => element.scrollWidth - element.clientWidth - element.scrollLeft)).toBeLessThanOrEqual(1)
  await expect(lastColumn).toBeInViewport()
  await name.getByRole('button').focus()
  await page.keyboard.press('Tab')
  const faction = region.getByRole('button', {name: '阵营/分组', exact: true})
  await expect(faction).toBeFocused()
  await expect.poll(() => faction.evaluate(element => {
    const {x, y, width, height} = element.getBoundingClientRect()
    return element.contains(document.elementFromPoint(x + width / 2, y + height / 2))
  })).toBe(true)

  // Drag the native vertical thumb, then continue scrolling the page at either boundary.
  await region.evaluate(element => {element.scrollTop = 0})
  await expect.poll(innerScroll).toBe(0)
  const geometry = await region.evaluate(element => {
    const {left, right, top} = element.getBoundingClientRect()
    return {x: (left + element.clientWidth + right) / 2, y: top + 6, gutter: right - left - element.clientWidth}
  })
  expect(geometry.gutter).toBeGreaterThanOrEqual(8)
  await page.mouse.move(geometry.x, geometry.y)
  await page.mouse.down()
  await page.mouse.move(geometry.x, geometry.y + 120, {steps: 8})
  await page.mouse.up()
  await expect.poll(innerScroll).toBeGreaterThan(1000)
  await region.evaluate(element => {
    const main = element.closest('main')!
    main.scrollTop += element.getBoundingClientRect().top - main.getBoundingClientRect().top - 225
    element.scrollTop = element.scrollHeight
  })
  const bottomTarget = (await region.boundingBox())!
  await page.mouse.move(bottomTarget.x + 240, bottomTarget.y + 130)
  const beforeBottomWheel = await pageScroll()
  expect(beforeBottomWheel).toBeLessThan(await main.evaluate(element => element.scrollHeight - element.clientHeight))
  await page.mouse.wheel(0, 500)
  await page.mouse.wheel(0, 500)
  await expect.poll(pageScroll).toBeGreaterThan(beforeBottomWheel)
  await region.evaluate(element => {element.scrollTop = 0})
  const beforeTopWheel = await pageScroll()
  await page.mouse.wheel(0, -500)
  await expect.poll(pageScroll).toBeLessThan(beforeTopWheel)

  await page.setViewportSize({width: 390, height: 550})
  await horizontal.scrollIntoViewIfNeeded()
  await expect(name).not.toHaveCSS('position', 'sticky')
  const longName = region.locator('tbody .ft-name a').first()
  await longName.evaluate(element => {element.textContent = 'A long localized ship name that must stay readable on a narrow screen'})
  await expect.poll(() => longName.evaluate(element => {
    const text = document.createRange()
    text.selectNodeContents(element)
    return text.getBoundingClientRect().width - element.getBoundingClientRect().width
  })).toBeLessThanOrEqual(1)
  await horizontal.press('End')
  await expect(lastColumn).toBeInViewport()
  await expect.poll(() => main.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
})

test('technology reload stays in the page header and preserves the draft', async ({page}, info) => {
  await page.setViewportSize({width: 390, height: 844})
  const instance = `tech-reload-${info.testId.replace(/[^a-z0-9]/gi, '').slice(-12)}-${info.retry}`
  await page.goto('/'); await rpc(page, 'instances.create', {name: instance}); await page.goto('about:blank')
  const requests: Array<{id: string; method: string}> = [], responses: string[] = []
  let releaseCatalog: (() => void) | undefined
  await routeRpc(page, socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      const request = JSON.parse(message)
      if (request.type === 'request' && /^(fleetTech|dock)\./.test(request.method)) requests.push(request)
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(message)
      if (!releaseCatalog && response.type === 'response' && requests.some(request => request.id === response.id && request.method === 'fleetTech.catalog')) {
        releaseCatalog = () => socket.send(JSON.stringify({...response, ok: false, error: {code: 'INTERNAL_ERROR', message: '测试图鉴读取失败'}}))
        return
      }
      if (response.type === 'response') responses.push(response.id)
      socket.send(message)
    })
  })
  await page.goto(`/#/i/${instance}/task/FleetAnalysis?tab=technology`)
  const reload = page.getByRole('button', {name: '重新载入', exact: true})
  await expect(reload).toHaveCount(1)
  await expect(reload).toBeVisible()
  const original = await reload.elementHandle()
  expect(original).not.toBeNull()
  await expect.poll(() => !!releaseCatalog).toBe(true)
  await expect(reload).toBeEnabled()
  await reload.click()
  releaseCatalog!()
  await expect(page.getByText('测试图鉴读取失败', {exact: true})).toBeVisible()
  await expect(reload).toBeEnabled()
  const technologyRequests = () => requests.filter(request => request.method.startsWith('fleetTech.')).map(request => request.method).sort()
  expect(technologyRequests()).toEqual(['fleetTech.catalog', 'fleetTech.report'])
  await reload.click()
  expect(await reload.evaluate((element, initial) => element === initial, original)).toBe(true)
  await page.getByLabel('搜索舰名', {exact: true}).fill('杜威')
  expect(technologyRequests()).toEqual(['fleetTech.catalog', 'fleetTech.catalog', 'fleetTech.report', 'fleetTech.report'])
  await page.getByRole('button', {name: '记录编辑模式', exact: true}).click()
  const milestone = page.getByRole('button', {name: '杜威 · 获得 · 未完成', exact: true})
  await milestone.click()
  const changed = page.getByRole('button', {name: '杜威 · 获得 · 已完成', exact: true})
  await expect(changed).toHaveAttribute('aria-pressed', 'true')
  await expect(reload).toHaveCount(1)
  const reloadBox = await reload.boundingBox(), tabsBox = await page.getByRole('tablist', {name: '舰船数据'}).boundingBox()
  expect(reloadBox).not.toBeNull(); expect(tabsBox).not.toBeNull()
  expect(reloadBox!.y + reloadBox!.height).toBeLessThanOrEqual(tabsBox!.y)
  const start = requests.length
  await reload.click()
  await expect.poll(() => requests.slice(start).map(request => request.method)).toEqual(['fleetTech.report'])
  await expect.poll(() => responses.includes(requests[start].id)).toBe(true)
  expect(requests.slice(start).map(request => request.method)).toEqual(['fleetTech.report'])
  await expect(changed).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', {name: '放弃草稿', exact: true})).toBeVisible()
  for (const tab of ['我的舰船', '养成计算', '扫描更新']) {
    await page.getByRole('tab', {name: tab, exact: true}).click()
    await expect(reload).toHaveCount(1)
    await expect(reload).toBeEnabled()
    expect(await reload.evaluate((element, initial) => element === initial, original)).toBe(true)
  }
  await page.getByRole('tab', {name: '舰队科技', exact: true}).click()
  await expect(reload).toHaveCount(1)
  expect(await reload.evaluate((element, initial) => element === initial, original)).toBe(true)
  await expect(changed).toHaveAttribute('aria-pressed', 'true')
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
  await page.goto('/'); await rpc(page, 'instances.create', {name: instance}); await page.goto('about:blank')
  let holdWrite = false
  let releaseReport: (() => void) | undefined, releaseSave: (() => void) | undefined
  await routeRpc(page, socket => {
    const server = socket.connectToServer()
    const methods = new Map<string, string>()
    socket.onMessage(message => {
      const request = JSON.parse(message)
      if (request.type === 'request') methods.set(request.id, request.method)
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(message)
      if (response.type === 'response' && holdWrite) {
        const method = methods.get(response.id)
        if (method === 'fleetTech.report' && !releaseReport) {
          releaseReport = () => socket.send(message)
          return
        }
        if (method === 'fleetTech.patch' && !releaseSave) {
          releaseSave = () => socket.send(message)
          return
        }
      }
      socket.send(message)
    })
  })
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
  const reload = page.getByRole('button', {name: '重新载入', exact: true})
  holdWrite = true
  await reload.click()
  await expect.poll(() => !!releaseReport).toBe(true)
  await page.getByRole('button', {name: '保存', exact: true}).click()
  await expect.poll(() => !!releaseSave).toBe(true)
  await expect(reload).toBeDisabled()
  releaseSave!()
  await expect(page.locator('.ft-modified')).toHaveCount(0)
  await expect(page.getByRole('button', {name: '保存', exact: true})).toBeDisabled()
  await expect(reload).toBeEnabled()
  releaseReport!()
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

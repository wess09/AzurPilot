import {test, expect} from '@playwright/test'

test('重名群组可分别选择、计费、保存和导出，歧义旧记录保留核对', async ({page}) => {
  await page.goto('/')
  // 模拟服务跨浏览器上下文保存清单，本例先清空自己的实例。
  await page.evaluate(() => new Promise<void>((resolve, reject) => {
    const socket = new WebSocket(`${location.origin.replace(/^http/, 'ws')}/api/v1/ws`)
    socket.onopen = () => socket.send(JSON.stringify({v: 1, type: 'request', id: 'before', method: 'mind.report', params: {instance: 'demo-alt'}}))
    socket.onmessage = event => {
      const response = JSON.parse(event.data)
      if (response.id === 'before') {
        if (!response.ok) {socket.close(); reject(new Error(response.error.message)); return}
        socket.send(JSON.stringify({v: 1, type: 'request', id: 'clear', method: 'mind.save', params: {instance: 'demo-alt', revision: response.result.revision, ships: []}}))
      } else if (response.id === 'clear') {
        socket.close()
        if (response.ok) resolve(); else reject(new Error(response.error.message))
      }
    }
    socket.onerror = () => reject(new Error('模拟服务未连接'))
  }))
  await page.goto('about:blank')
  await page.addInitScript(() => {localStorage.setItem('azurpilot.language', 'zh-CN')})
  await page.goto('/#/i/demo-alt/mind-calculator')
  const add = page.locator('.mind-add')
  await expect(add).toBeVisible()
  const names = await page.locator('#mind-ship-catalog option').evaluateAll(options => options.map(option => (option as HTMLOptionElement).value))
  const kaga = names.filter(name => name.startsWith('加贺（'))
  expect(kaga).toHaveLength(2)
  const surface = kaga.find(name => name.includes('战列'))!
  const aviation = kaga.find(name => name.includes('正航'))!
  for (const [name, level] of [[surface, '120'], [aviation, '100']]) {
    await add.getByLabel('船名', {exact: true}).fill(name)
    await add.getByLabel('等级', {exact: true}).fill(level)
    await add.getByRole('button', {name: '添加舰船'}).click()
  }
  await expect(page.locator('.mind-ship-table tbody tr')).toHaveCount(2)
  await expect(page.locator('.mind-totals strong').first()).toHaveText('2,200')
  await page.getByRole('button', {name: '保存舰船数据'}).click()
  await expect(page.locator('.mind-intro')).toContainText('数据已保存到当前实例')
  await page.reload()
  await expect(page.locator('.mind-ship-table tbody tr')).toHaveCount(2)
  await expect(page.locator('.mind-totals strong').first()).toHaveText('2,200')
  const legacy = JSON.stringify({ships: [{name: '约克', level: 100, review: false}]})
  await page.locator('input[type=file][accept=".json,.csv,.xlsx"]').setInputFiles({name: 'legacy.json', mimeType: 'application/json', buffer: Buffer.from(legacy)})
  const york = page.locator('.mind-ship-table tbody tr').nth(2)
  await expect(york.getByLabel('船名 3', {exact: true})).toHaveValue('约克')
  await expect(york.getByRole('combobox', {name: '状态 3', exact: true})).toContainText('待核对')
  const royalYork = names.find(name => name.startsWith('约克（') && name.includes('皇家'))!
  await york.getByLabel('船名 3', {exact: true}).fill(royalYork)
  await york.getByLabel('船名 3', {exact: true}).press('Enter')
  await expect(york.getByRole('combobox', {name: '状态 3', exact: true})).toContainText('待核对')
  await expect(page.locator('.mind-intro')).toContainText('数据已保存到当前实例')
  await york.getByRole('combobox', {name: '状态 3', exact: true}).click()
  await page.getByRole('option', {name: '计入舰船', exact: true}).click()
  await expect(page.locator('.mind-totals strong').first()).toHaveText('3,520')
  await expect(page.locator('.mind-intro')).toContainText('数据已保存到当前实例')
  await page.reload()
  await expect(page.getByLabel('船名 3', {exact: true})).toHaveValue(royalYork)
  await page.screenshot({path: test.info().outputPath('same-name-groups.png'), fullPage: true})
})

import { expect, test } from '@playwright/test'

test.beforeEach(async ({page}) => {
  await page.route('https://www.clarity.ms/**', route => route.abort())
})

test('现代主题浅色与深色的日志在面板内部滚动', async ({page}) => {
  await page.route('https://api.yppp.net/**', route => route.abort())
  await page.setViewportSize({width: 1440, height: 900})
  await page.goto('/#/i/testpilot/overview')

  for (const theme of ['legacy-light', 'legacy-dark']) {
    await page.evaluate(value => localStorage.setItem('azurpilot.theme', value), theme)
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    const log = page.locator('.log-content')
    await expect(log).toBeVisible()
    await log.evaluate(element => {
      for (let index = 0; index < 300; index += 1) {
        const line = document.createElement('div')
        line.textContent = `日志高度回归 ${index}`
        element.appendChild(line)
      }
    })

    const layout = await page.evaluate(() => {
      const log = document.querySelector<HTMLElement>('.log-content')!
      const panel = document.querySelector<HTMLElement>('.monitor-panel')!
      return {
        pageHeight: document.documentElement.scrollHeight,
        viewportHeight: innerHeight,
        logClientHeight: log.clientHeight,
        logScrollHeight: log.scrollHeight,
        panelBottom: panel.getBoundingClientRect().bottom,
      }
    })
    expect(layout.pageHeight, theme).toBeLessThanOrEqual(layout.viewportHeight + 1)
    expect(layout.logScrollHeight, theme).toBeGreaterThan(layout.logClientHeight)
    expect(layout.panelBottom, theme).toBeLessThanOrEqual(layout.viewportHeight + 1)
  }
})

test('自定义背景支持 URL 与上传文件并在刷新后恢复', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.material', 'glass'))
  const remote = 'https://background.example/custom.jpg'
  await page.route(remote, route => route.fulfill({
    contentType: 'image/png',
    body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64'),
  }))
  await page.route('https://api.yppp.net/**', route => route.abort())
  await page.goto('/#/interface')

  const source = page.getByRole('combobox', {name: '自定义背景'})
  await source.click()
  await page.getByRole('option', {name: '填写 URL'}).click()
  // URL 模式一行一个 API。把默认列表清空后只留下测试地址，
  // 避免“本次随机生效”挑到其它内置地址。
  const urlRows = page.getByRole('textbox', {name: '填写 URL'})
  for (let index = await urlRows.count() - 1; index >= 0; index -= 1) await urlRows.nth(index).fill('')
  await urlRows.first().fill(remote)
  await page.getByRole('button', {name: '应用背景'}).click()
  await expect(page.locator('#ui-background-direct')).toHaveValue(remote)
  // URL 背景解析完成后统一走同源代理，壁纸节点不挂第三方直链。
  await expect(page.locator('.wallpaper img')).toHaveAttribute('src', /\/api\/v1\/background\/media\?url=/)
  expect(await page.evaluate(() => {
    const value = JSON.parse(localStorage.getItem('azurpilot.background') ?? '{}')
    return {source: value.source, urls: value.urls}
  })).toEqual({source: 'url', urls: [remote]})

  await source.click()
  await page.getByRole('option', {name: '上传文件'}).click()
  await page.locator('.background-upload input[type="file"]').setInputFiles({
    name: 'local.png',
    mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64'),
  })
  await expect(page.locator('.background-gallery-list')).toContainText('local.png')
  const uploaded = page.locator('.wallpaper img')
  await expect(uploaded).toHaveAttribute('src', /^\/background-library\//)
  const uploadedSrc = await uploaded.getAttribute('src')
  await page.reload()
  await expect(page.locator('.wallpaper img')).toHaveAttribute('src', uploadedSrc!)
  await expect(page.getByRole('combobox', {name: '自定义背景'})).toHaveText('上传文件')
})

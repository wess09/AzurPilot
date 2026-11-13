/**
 * @fileoverview 主题用例：简约主题跟随系统明暗并恢复配色、现代主题日志内滚、自定义背景的持久化。
 */

import { expect, test } from '@playwright/test'

test.beforeEach(async ({page}) => {
  await page.route('https://www.clarity.ms/**', route => route.abort())
})

test('简约主题跟随系统明暗并恢复已保存的配色', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.material', 'glass'))
  await page.route('https://api.yppp.net/**', route => route.abort())
  await page.emulateMedia({colorScheme: 'light'})
  await page.goto('/#/interface')
  const root = page.locator('html')
  const theme = page.getByRole('combobox', {name: '界面主题'})
  await theme.click()
  await page.getByRole('option', {name: '简约'}).click()
  await expect(root).toHaveAttribute('data-theme', 'minimal')
  await expect(root).toHaveAttribute('data-color-mode', 'light')
  await expect(page.locator('.wallpaper')).toHaveCount(0)
  await expect(page.locator('.sidebar')).toHaveCSS('backdrop-filter', 'none')
  await expect(page.locator('.sidebar')).toHaveCSS('border-radius', '0px')
  await expect(page.locator('.config-group')).toHaveCSS('border-radius', '14px')

  const forest = page.locator('.palette-option').filter({has: page.locator('input[value="forest"]')})
  await forest.click()
  await expect(root).toHaveCSS('--accent', '#286747')
  await page.emulateMedia({colorScheme: 'dark'})
  await expect(root).toHaveAttribute('data-color-mode', 'dark')
  await expect(root).toHaveCSS('--accent', '#86cba3')

  const mode = page.getByRole('combobox', {name: '主题模式'})
  await mode.click()
  await page.getByRole('option', {name: '深色'}).click()
  await page.emulateMedia({colorScheme: 'light'})
  await page.reload()
  await expect(theme).toHaveText('简约')
  await expect(mode).toHaveText('深色')
  await expect(root).toHaveAttribute('data-color-mode', 'dark')
  await expect(forest.locator('input')).toBeChecked()

  await page.getByRole('button', {name: '添加自定义配色'}).click()
  const paletteEditor = page.getByRole('dialog').filter({has: page.getByRole('heading', {name: '自定义配色'})})
  await paletteEditor.getByRole('textbox', {name: '主色', exact: true}).fill('#ffffff')
  await paletteEditor.getByRole('button', {name: '保存并应用'}).click()
  await expect(root).toHaveCSS('--accent', '#ffffff')
  await page.reload()
  await expect(root).toHaveCSS('--accent', '#ffffff')
  await page.getByRole('button', {name: '删除方案'}).click()
  await expect(root).toHaveCSS('--accent', '#8ab4ff')

  await mode.click()
  await page.getByRole('option', {name: '程序员'}).click()
  await expect(root).toHaveCSS('--bg', '#0b0b0b')
  await expect(page.locator('.palette-options')).toHaveCount(0)

  await theme.click()
  await page.getByRole('option', {name: '现代'}).click()
  await expect(root).toHaveAttribute('data-theme', 'legacy-dark')
  await expect(root).not.toHaveAttribute('data-color-mode', /.+/)
  await expect(root).toHaveAttribute('data-material', 'glass')
  await expect(root).not.toHaveCSS('--bg', '#0b0b0b')
  const reducedBackdrop = await root.getAttribute('data-reduce-backdrop')
  await expect(page.locator('.sidebar')).toHaveCSS('backdrop-filter', reducedBackdrop === null ? /blur\(/ : 'none')
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

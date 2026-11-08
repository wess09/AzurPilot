import { expect, test } from '@playwright/test'

/** 元素实际读到的令牌值：把令牌挂到探针元素上，让浏览器把 var() 解析并归一化成与计算样式同样的写法。 */
async function resolvedFilter(page: import('@playwright/test').Page, token: string) {
  return page.evaluate(tokenName => {
    const probe = document.createElement('div')
    probe.style.backdropFilter = `var(${tokenName})`
    document.body.appendChild(probe)
    const value = getComputedStyle(probe).backdropFilter
    probe.remove()
    return value
  }, token)
}

test('生产构建保留高斯模糊且资源图标能够解码', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.material', 'glass'))
  // 使用固定背景隔离外部图片服务，直接验证构建后的浏览器计算样式。
  await page.route('https://api.yppp.net/**', route => route.fulfill({
    contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><path fill="#3588cc" d="M0 0h1280v720H0z"/></svg>',
  }))
  await page.goto('/#/i/testpilot/overview')
  await expect(page.getByRole('heading', {name: 'testpilot', exact: true})).toHaveText('testpilot')
  // 断言元素与它该读的令牌一致，而不是把数值写死：调令牌不该让这条用例变红，改错接线才该变红。
  const expectFilterFrom = async (selector: string, token: string) => {
    const filter = await resolvedFilter(page, token)
    expect(filter).toMatch(/blur\(/)
    await expect(page.locator(selector).first()).toHaveCSS('backdrop-filter', filter)
  }
  await expectFilterFrom('.sidebar', '--theme-surface-filter')
  await expectFilterFrom('.legacy-page-nav', '--theme-surface-filter')
  // 一级面：面板与资源卡都走一级面滤镜。
  await expectFilterFrom('.monitor-panel', '--theme-surface-filter')
  await expectFilterFrom('.resource-card', '--theme-surface-filter')
  const icons = page.locator('.resource-icon-image')
  await expect(icons.first()).toBeVisible()
  await expect.poll(() => icons.evaluateAll(elements => elements.every(element =>
    element instanceof HTMLImageElement && element.complete && element.naturalWidth > 0,
  ))).toBe(true)
  const loadedFonts = await page.evaluate(async () => {
    const faces = await Promise.all([
      document.fonts.load('600 16px MiSans', '碧蓝航线'),
      document.fonts.load('16px "JetBrains Mono"', 'AzurPilot'),
    ])
    return faces.map(items => items.some(face => face.status === 'loaded'))
  })
  expect(loadedFonts).toEqual([true, true])
  // 无障碍模式仍应关闭模糊，防止调整前缀顺序破坏降级样式。
  await page.emulateMedia({forcedColors: 'active'})
  await expect(page.locator('.sidebar')).toHaveCSS('backdrop-filter', 'none')
  await expect(page.locator('.resource-card').first()).toHaveCSS('backdrop-filter', 'none')
})

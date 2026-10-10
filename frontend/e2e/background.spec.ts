import { expect, test } from '@playwright/test'

test('背景代抓和上传携带授权令牌，未授权 HTTP 请求被拒绝', async ({page, request}) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'glass')
    localStorage.setItem('azurpilot.background', JSON.stringify({
      source: 'url', kind: 'image', urls: ['https://example.com/background'], active: 0, name: '',
    }))
  })
  const denied = await request.get('/api/v1/background/media?url=https://example.com/background')
  expect(denied.status()).toBe(401)
  expect((await request.post('/api/v1/background/gallery')).status()).toBe(401)
  const mediaResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/background/media')
  await page.goto('/#/interface')
  const media = await mediaResponse
  expect(media.status()).toBe(200)
  expect(new URL(media.url()).searchParams.get('token')).toBeTruthy()
  await expect(page.locator('img.wallpaper-media')).toBeVisible()
  await page.locator('#ui-background-source').click()
  await page.getByRole('option', {name: '上传文件', exact: true}).click()
  const uploaded = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/background/gallery' && response.request().method() === 'POST')
  await page.locator('.background-upload-input').setInputFiles({
    name: 'auth-regression.png', mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64'),
  })
  const response = await uploaded
  expect(response.status()).toBe(200)
  expect(response.request().headers()['x-azurpilot-background-token']).toBeTruthy()
  expect(new URL(response.url()).search).toBe('')
  await expect(page.locator('.background-gallery-name', {hasText: 'auth-regression.png'})).toBeVisible()
})

test('关闭背景后切回上传文件档直接铺上原图', async ({page}) => {
  /* 「关闭背景」档只在普通材质出现。 */
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'plain')
  })
  await page.goto('/#/interface')
  const source = page.locator('#ui-background-source')
  await source.click()
  await page.getByRole('option', {name: '上传文件', exact: true}).click()
  await page.locator('.background-upload-input').setInputFiles({
    name: 'switch-back.png', mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64'),
  })
  await expect(page.locator('.wallpaper img')).toBeVisible()
  await source.click()
  await page.getByRole('option', {name: '关闭背景', exact: true}).click()
  await expect(page.locator('.wallpaper img')).toHaveCount(0)
  await source.click()
  await page.getByRole('option', {name: '上传文件', exact: true}).click()
  await expect(page.locator('.wallpaper img')).toBeVisible()
})

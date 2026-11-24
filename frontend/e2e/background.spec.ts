/**
 * @fileoverview 背景壁纸用例：代抓与上传接口的授权令牌校验，以及各背景来源切换后的铺图行为。
 */

import { expect, test } from '@playwright/test'
import { routeRpc } from './rpc-route'

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


test('图库首读失败后在同一份读取状态中重试', async ({page}) => {
  let reads = 0
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'plain')
  })
  await routeRpc(page, socket => {
    const server = socket.connectToServer()
    server.onMessage(message => socket.send(message))
    socket.onMessage(message => {
      const frame = JSON.parse(message)
      if (frame.method === 'background.gallery.list' && ++reads === 1) {
        socket.send(JSON.stringify({v: 1, type: 'response', id: frame.id, ok: false,
          error: {code: 'TEST_FAILURE', message: '图库读取失败'}}))
        return
      }
      server.send(message)
    })
  })
  await page.goto('/#/interface')
  await page.locator('#ui-background-source').click()
  await page.getByRole('option', {name: '上传文件', exact: true}).click()
  const gallery = page.locator('.background-gallery')
  await expect(gallery.getByRole('alert')).toContainText('图库读取失败')
  expect(reads).toBe(1)
  await gallery.getByRole('button', {name: '重试', exact: true}).click()
  await expect(gallery.getByRole('alert')).toHaveCount(0)
  expect(reads).toBe(2)
})


test('旧背景迁移失败时，切换到网址仍保留本地旧文件', async ({page}) => {
  await page.route('**/gallery-seed', route => route.fulfill({contentType: 'text/html', body: '<html></html>'}))
  await page.goto('/gallery-seed')
  await page.evaluate(async () => {
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('azurpilot-preferences', 1)
      request.onupgradeneeded = () => request.result.createObjectStore('media')
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    await new Promise<void>((resolve, reject) => {
      const tx = database.transaction('media', 'readwrite')
      tx.objectStore('media').put(new Blob(['legacy wallpaper'], {type: 'image/png'}), 'background')
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
    database.close()
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'plain')
    localStorage.setItem('azurpilot.background.plain', JSON.stringify({
      source: 'upload', kind: 'image', urls: [], active: 0, name: 'legacy.png',
    }))
  })
  let denied = 0
  await routeRpc(page, socket => {
    const server = socket.connectToServer()
    server.onMessage(message => socket.send(message))
    socket.onMessage(message => {
      const frame = JSON.parse(message)
      if (frame.method === 'background.access') {
        denied++
        socket.send(JSON.stringify({v: 1, type: 'response', id: frame.id, ok: false,
          error: {code: 'TEST_FAILURE', message: '旧背景暂时无法迁移'}}))
        return
      }
      server.send(message)
    })
  })
  await page.goto('/#/interface')
  await expect.poll(() => denied).toBe(1)
  const source = page.locator('#ui-background-source')
  await source.click()
  await page.getByRole('option', {name: '填写 URL'}).click()
  await expect(page.getByRole('button', {name: '应用背景'})).toBeVisible()
  const stored = await page.evaluate(() => new Promise<string>((resolve, reject) => {
    const open = indexedDB.open('azurpilot-preferences', 1)
    open.onerror = () => reject(open.error)
    open.onsuccess = () => {
      const database = open.result
      const request = database.transaction('media', 'readonly').objectStore('media').get('background')
      request.onsuccess = () => { database.close(); resolve(request.result?.text() ?? '') }
      request.onerror = () => { database.close(); reject(request.error) }
    }
  }))
  expect(stored).toBe('legacy wallpaper')
})

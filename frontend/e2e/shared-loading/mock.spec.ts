import { expect, test } from '@playwright/test'
import { routeRpc } from '../rpc-route'

for (const [method, path, readyHeading] of [
  ['schema.get', '/#/interface', '界面设置'],
  ['dock.report', '/#/i/demo-main/task/FleetAnalysis?tab=scan', /开始读取/],
] as const) {
  test('a failed ' + method + ' read recovers from the shared error state', async ({page}) => {
    let failed = false
    await page.addInitScript(() => localStorage.setItem('azurpilot.language', 'zh-CN'))
    await routeRpc(page, socket => {
      const server = socket.connectToServer()
      socket.onMessage(message => {
        const request = JSON.parse(String(message))
        if (request.method !== method || failed) {
          server.send(message)
          return
        }
        failed = true
        socket.send(JSON.stringify({
          v: 1, type: 'response', id: request.id, ok: false,
          error: {code: 'INTERNAL_ERROR', message: '读取失败，请重试'},
        }))
      })
      server.onMessage(message => socket.send(message))
    })
    await page.goto(path)
    const main = page.locator('main')
    await expect(main.getByRole('alert')).toContainText('读取失败，请重试')
    await expect(main.locator('[data-slot=loading]')).toHaveCount(0)
    await expect(main.getByRole('heading', {name: readyHeading})).toHaveCount(0)
    await main.getByRole('button', {name: '重试', exact: true}).click()
    await expect(main.getByRole('heading', {name: readyHeading})).toHaveCount(1)
    await expect(main.getByRole('alert')).toHaveCount(0)
  })
}

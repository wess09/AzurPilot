import {routeRpc} from '../rpc-route'
import { expect, test } from '@playwright/test'

for (const theme of ['legacy-light', 'legacy-dark'] as const) {
  test(`系统设置在 ${theme} 下渲染并保存开关`, async ({page}) => {
    let enabled = false
    const requests = new Set<string>()
    await page.addInitScript(value => localStorage.setItem('azurpilot.theme', value), theme)
    await routeRpc(page, socket => {
      const server = socket.connectToServer()
      socket.onMessage(message => {
        const request = JSON.parse(message.toString())
        if (request.method === 'settings.get') requests.add(request.id)
        if (request.method === 'settings.patch' && 'SSLVerify' in request.params.values) {
          enabled = request.params.values.SSLVerify
          socket.send(JSON.stringify({v: 1, type: 'response', id: request.id, ok: true, result: {updated: ['SSLVerify']}}))
        } else {
          server.send(message)
        }
      })
      server.onMessage(message => {
        const response = JSON.parse(message.toString())
        if (response.type === 'response' && requests.delete(response.id) && response.ok) {
          response.result.groups.find((group: {key: string}) => group.key === 'Git').fields.push({
            key: 'SSLVerify', type: 'bool', label: '验证证书', help: '检查证书', value: enabled, options: [],
          })
          socket.send(JSON.stringify(response))
        } else {
          socket.send(message)
        }
      })
    })

    await page.goto('/#/settings')
    const control = page.getByRole('switch', {name: '验证证书', exact: true})
    const thumb = control.locator('[data-slot="switch-thumb"]')
    await expect(control).toHaveAttribute('aria-checked', 'false')
    await expect(control).toHaveAttribute('aria-describedby', 'deploy-SSLVerify-description')
    await expect(page.locator('#deploy-SSLVerify-description')).toHaveText('检查证书')
    await expect(page.locator('html')).toHaveClass(theme === 'legacy-dark' ? /\bdark\b/ : /^(?!.*\bdark\b)/)
    const uncheckedColor = await thumb.evaluate(element => getComputedStyle(element).backgroundColor)
    await control.check()
    await expect(control).toHaveAttribute('aria-checked', 'true')
    await expect(page.locator('#deploy-SSLVerify-status')).toContainText('已保存')
    if (theme === 'legacy-dark') {
      await expect.poll(() => thumb.evaluate(element => getComputedStyle(element).backgroundColor)).not.toBe(uncheckedColor)
    }
    await page.reload()
    await expect(control).toHaveAttribute('aria-checked', 'true')
    await page.setViewportSize({width: 390, height: 844})
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}

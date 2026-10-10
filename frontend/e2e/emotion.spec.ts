import {expect, test} from '@playwright/test'
import type {Config} from '../src/api/types'

test('实测心情重新输入同值会校准，浏览页面和普通字段不会重新提交', async ({page}) => {
  const patches: string[] = []
  const saved = new Map<string, Config>()
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    const pending = new Map<string, string>()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      if (request.method === 'config.patch') {
        const path = request.params.changes[0].path as string
        patches.push(path)
        pending.set(request.id, path)
      }
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      const path = pending.get(response.id)
      if (path && response.ok) saved.set(path, response.result as Config)
      socket.send(message)
    })
  })

  // 新连接重新读配置，核对实际 JSON 读回值，而非页面乐观更新的副本。
  const reread = () => page.evaluate(() => new Promise<Config>((resolve, reject) => {
    const socket = new WebSocket(`${location.origin.replace(/^http/, 'ws')}/api/v1/ws`)
    socket.onopen = () => socket.send(JSON.stringify({v: 1, type: 'request', id: 'emotion-read',
      method: 'config.get', params: {instance: 'testpilot'}}))
    socket.onerror = () => reject(new Error('配置读取连接失败'))
    socket.onmessage = event => {
      const response = JSON.parse(event.data)
      if (response.id !== 'emotion-read') return
      socket.close()
      if (response.ok) resolve(response.result as Config)
      else reject(new Error(response.error.message))
    }
  }))

  for (const [task, group, arg] of [['Main', 'Emotion', 'Fleet1Value'],
                                  ['Main', 'Emotion', 'Fleet2Value'],
                                  ['General', 'PublicEmotion', 'FleetValue']]) {
    const path = `${task}.${group}.${arg}`
    await page.goto(`/#/i/testpilot/task/${task}`)
    const field = page.locator(`[id="${path}"]`)
    await expect(field).toBeVisible()
    const before = await reread()
    const old = await field.inputValue()
    await field.focus()
    await field.blur()
    expect((await reread()).values[task][group]).toEqual(before.values[task][group])
    expect(patches).not.toContain(path)

    await field.fill('')
    await field.fill(old)
    await field.press('Enter')
    await expect.poll(() => saved.has(path)).toBe(true)
    expect(patches.filter(value => value === path)).toHaveLength(1)
    const prefix = arg.replace(/Value$/, '')
    const fields = (await reread()).values[task][group]
    expect(fields[arg]).toBe(Number(old))
    expect(fields[`${prefix}Record`]).not.toBe(before.values[task][group][`${prefix}Record`])
    expect(fields[`${prefix}RecoveryState`]).toEqual({version: 2,
      record: String(fields[`${prefix}Record`]).replace(' ', 'T'),
      signature: [fields[`${prefix}Recover`], fields[`${prefix}Oath`], fields[`${prefix}Onsen`]],
      segments: [[0, 360000000, Number(old)]]})
    await page.reload()
    await expect(field).toHaveValue(old)
  }

  await page.goto('/#/i/testpilot/task/Alas')
  const ordinary = page.locator('[id="Alas.Error.GameStuckThreshold"]')
  await expect(ordinary).toBeVisible()
  const old = await ordinary.inputValue()
  await ordinary.fill('')
  await ordinary.fill(old)
  await ordinary.blur()
  await reread()
  expect(patches).not.toContain('Alas.Error.GameStuckThreshold')
})

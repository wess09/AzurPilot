import {test, expect, type Page} from '@playwright/test'

async function openEditor(page: Page) {
  await page.addInitScript(() => {
    const Native = window.WebSocket
    const sockets: WebSocket[] = []
    ;(window as unknown as {testSockets: WebSocket[]}).testSockets = sockets
    window.WebSocket = class extends Native {
      constructor(url: string | URL, protocols?: string | string[]) { super(url, protocols); sockets.push(this) }
    }
  })
  const firstSocket = page.waitForEvent('websocket')
  await page.goto('/#/i/testpilot/task/SchedulerProgram')
  const socket = await firstSocket
  await expect(page.getByRole('textbox', {name:'方案名称'})).toBeVisible()
  return socket
}

async function reconnect(page: Page, socket: Awaited<ReturnType<typeof openEditor>>) {
  const closed = socket.waitForEvent('close', {timeout:10000})
  const requests: string[] = [], responses: string[] = []
  const observe = (next: typeof socket) => {
    next.on('framesent', frame => requests.push(String(frame.payload)))
    next.on('framereceived', frame => responses.push(String(frame.payload)))
  }
  page.on('websocket', observe)
  try {
    await page.evaluate(() => (window as unknown as {testSockets: WebSocket[]}).testSockets.forEach(socket => socket.close()))
    await closed
    await expect.poll(() => requests.some(request => request.includes('scheduler.program.get')), {timeout:15000}).toBe(true)
    const {id} = JSON.parse(requests.find(request => request.includes('scheduler.program.get'))!) as {id: string}
    await expect.poll(() => responses.some(response => response.includes(id))).toBe(true)
  } finally {page.off('websocket', observe)}
}

for (const dirty of [false, true]) {
  test(`scheduler reconnect ${dirty ? 'retains dirty draft and detects conflict' : 'refreshes a clean draft and revision'}`, async ({page, browser}) => {
    const socket = await openEditor(page)
    const name = page.getByRole('textbox', {name:'方案名称'})
    if (dirty) await name.fill('local unsaved draft')
    const other = await browser.newPage()
    try {
      await other.goto('/#/i/testpilot/task/SchedulerProgram')
      const otherName = other.getByRole('textbox', {name:'方案名称'})
      await expect(otherName).toBeVisible()
      await otherName.fill(dirty ? 'external dirty revision' : 'external clean revision')
      await other.getByRole('button', {name:'保存草稿'}).click()
      await expect(other.getByText('草稿已保存').last()).toBeVisible()
      await reconnect(page, socket)
      if (dirty) {
        await expect(name).toHaveValue('local unsaved draft')
        await page.getByRole('button', {name:'保存草稿'}).click()
        await expect(page.getByText('调度方案已被其他窗口修改，请重新加载')).toBeVisible()
        await expect(name).toHaveValue('local unsaved draft')
      } else {
        await expect(name).toHaveValue('external clean revision')
        await name.fill('saved after reconnect')
        await page.getByRole('button', {name:'保存草稿'}).click()
        await expect(page.getByText('草稿已保存').last()).toBeVisible()
      }
    } finally {await other.close()}
  })
}

test('scheduler variable fields edit through the shared controls', async ({page}) => {
  await openEditor(page)
  const more = page.getByRole('button', {name: '更多操作', exact: true})
  await more.click()
  await page.getByRole('button', {name: '变量与端口', exact: true}).click()
  await page.keyboard.press('Escape')
  const fields = page.locator('.program-schema-panel')
  await fields.getByRole('button', {name: '添加', exact: true}).click()
  const row = fields.locator('.program-schema-row').last()
  const select = row.getByRole('combobox', {name: '变量类型'})
  await expect(select).toHaveAttribute('data-slot', 'select-trigger')
  await select.press('Enter')
  const options = page.getByRole('listbox')
  await expect(options).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(select).toBeFocused()
  await expect(row.getByRole('checkbox', {name: '重启保留'})).toHaveAttribute('data-slot', 'checkbox')
  await row.getByRole('checkbox', {name: '重启保留'}).check()
  await expect(row.getByRole('checkbox', {name: '重启保留'})).toBeChecked()
  await expect(row.getByRole('textbox', {name: '初始值'})).toHaveAttribute('data-slot', 'textarea')
})

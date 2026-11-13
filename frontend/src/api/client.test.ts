import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from './client'
import { webSocketTransport } from './generated'

/**
 * 顶替全局 WebSocket 的桩：客户端在 connect() 里自建连接，测试经静态 `latest`
 * 取到最新实例；`sent` 记录客户端发出的每条请求，`emit`/`emitBytes` 从服务端方向注入消息。
 */
class FakeSocket {
  static OPEN = 1
  static latest: FakeSocket
  readyState = 1
  onmessage?: (event: {data: string | ArrayBuffer}) => void
  onclose?: () => void
  sent: Record<string, unknown>[] = []
  url: string
  constructor(url: string | URL) {FakeSocket.latest = this; this.url = String(url)}
  send(message: string) {this.sent.push(JSON.parse(message))}
  close() {this.readyState = 3; this.onclose?.()}
  emit(message: unknown) {this.onmessage?.({data: JSON.stringify(message)})}
  emitBytes(bytes: ArrayBuffer) { this.onmessage?.({data: bytes}) }
}

describe('WebSocket 客户端', () => {
  let client: ApiClient
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('window', {location: {href: 'http://localhost:5173/', protocol: 'http:'}})
    vi.stubGlobal('document', {baseURI: 'http://localhost:5173/'})
    vi.stubGlobal('WebSocket', FakeSocket)
    client = new ApiClient(); client.connect()
    FakeSocket.latest.emit({v: 1, type: 'event', topic: 'session', seq: 1, data: {authRequired: false}})
  })
  afterEach(() => {client.disconnect(); vi.useRealTimers(); vi.unstubAllGlobals()})
  it('乱序响应按请求 ID 关联', async () => {
    const first = client.request('system.ping', {})
    const second = client.request('instances.list', {})
    const socket = FakeSocket.latest
    socket.emit({v: 1, type: 'response', id: socket.sent[1].id, ok: true, result: []})
    socket.emit({v: 1, type: 'response', id: socket.sent[0].id, ok: true, result: {pong: true}})
    expect(await first).toEqual({pong: true}); expect(await second).toEqual([])
  })
  it('断线拒绝未完成请求，不自动重复写操作', async () => {
    const request = client.request('instances.create', {name: 'pilot'})
    const rejection = expect(request).rejects.toMatchObject({code: 'DISCONNECTED'})
    FakeSocket.latest.close(); await rejection
    await vi.advanceTimersByTimeAsync(2000)
    expect(FakeSocket.latest.sent).toEqual([])
  })
  it('请求超时后清理等待项', async () => {
    const request = client.request('system.ping', {})
    const rejection = expect(request).rejects.toMatchObject({code: 'TIMEOUT'})
    await vi.advanceTimersByTimeAsync(45000); await rejection
  })
  it('认证完成前不发送业务请求', async () => {
    client.disconnect(); client = new ApiClient(); client.connect()
    FakeSocket.latest.emit({v: 1, type: 'event', topic: 'session', seq: 1, data: {authRequired: true}})
    await expect(client.request('instances.list', {})).rejects.toMatchObject({code: 'DISCONNECTED'})
    expect(FakeSocket.latest.sent).toHaveLength(0)
  })
  it('WebSocket 地址跟随 document.baseURI，远程访问隧道前缀不丢', () => {
    // 地址与 peer_id 都是占位符，不要填真实隧道。
    vi.stubGlobal('window', {location: {href: 'https://tunnel.example.com/example-peer-id/', protocol: 'https:'}})
    vi.stubGlobal('document', {baseURI: 'https://tunnel.example.com/example-peer-id/'})
    client.disconnect(); client = new ApiClient(); client.connect()
    expect(FakeSocket.latest.url).toBe('wss://tunnel.example.com/example-peer-id/api/v1/ws?channel=control')
  })
  it('保留校验失败的诊断详情供脚本编辑器定位行列', async () => {
    const request = client.request('system.ping', {})
    const rejection = expect(request).rejects.toMatchObject({
      code: 'INVALID_PARAMS', details: [{message: '不允许调用 os.execute', line: 4, column: 12}],
    })
    const sent = FakeSocket.latest.sent.at(-1)!
    FakeSocket.latest.emit({v: 1, type: 'response', id: sent.id, ok: false, error: {
      code: 'INVALID_PARAMS', message: '策略校验失败', details: [{message: '不允许调用 os.execute', line: 4, column: 12}],
    }})
    await rejection
  })
  it('刷新后用已保存的密码登录，密码失效时清除旧值', async () => {
    const values = new Map<string, string>()
    Object.assign(window, {localStorage: {getItem: (key: string) => values.get(key), setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key)}})
    const login = client.login('测试访问密码')
    FakeSocket.latest.emit({v: 1, type: 'response', id: FakeSocket.latest.sent.at(-1)!.id, ok: true, result: {authenticated: true}})
    await login
    client.disconnect(); client = new ApiClient(); client.connect()
    FakeSocket.latest.emit({v: 1, type: 'event', topic: 'session', seq: 1, data: {authRequired: true}})
    expect(FakeSocket.latest.sent.at(-1)).toMatchObject({method: 'auth.login', params: {password: '测试访问密码'}})
    FakeSocket.latest.emit({v: 1, type: 'response', id: FakeSocket.latest.sent.at(-1)!.id, ok: false, error: {code: 'UNAUTHORIZED', message: '密码已更换'}})
    await vi.advanceTimersByTimeAsync(0)
    expect(client.getSnapshot()).toBe('auth')
    expect(values.size).toBe(0)
  })
  it('启动器票据只认证当前连接，立即清除地址中的票据且不保存访问密码', async () => {
    client.disconnect()
    const replaceState = vi.fn()
    const setItem = vi.fn()
    vi.stubGlobal('window', {
      location: {href: 'http://localhost:5173/?launcherTicket=opaque_ticket&view=settings', protocol: 'http:'},
      history: {replaceState}, localStorage: {getItem: () => null, setItem},
    })
    client = new ApiClient(); client.connect()
    expect(replaceState).toHaveBeenCalledWith(null, '', 'http://localhost:5173/?view=settings')
    FakeSocket.latest.emit({v: 1, type: 'event', topic: 'session', seq: 1, data: {authRequired: true}})
    const request = FakeSocket.latest.sent.at(-1)!
    expect(request).toMatchObject({method: 'auth.launcher', params: {ticket: 'opaque_ticket'}})
    FakeSocket.latest.emit({v: 1, type: 'response', id: request.id, ok: true, result: {authenticated: true}})
    await vi.advanceTimersByTimeAsync(0)
    expect(client.getSnapshot()).toBe('ready')
    expect(setItem).not.toHaveBeenCalled()
  })

  it('数据连接重组分片时操作请求仍能完成，重连后恢复订阅', async () => {
    client.disconnect()
    client = new ApiClient()
    client.connect()
    const session = (socket: FakeSocket, channel: string) => socket.emit({
      v: 1, type: 'event', topic: 'session', seq: 1, data: {authRequired: false, channel},
    })
    const control = FakeSocket.latest
    session(control, 'control')
    const data = FakeSocket.latest
    expect(data.url).toContain('channel=data')
    session(data, 'data')
    const subscription = client.request('events.subscribe', {instance: 'pilot', topics: ['instances', 'logs', 'preview']})
    expect(control.sent.at(-1)?.params).toEqual({instance: 'pilot', topics: ['instances']})
    control.emit({v: 1, type: 'response', id: control.sent.at(-1)!.id, ok: true, result: {instance: 'pilot'}})
    await subscription
    expect(data.sent.at(-1)?.params).toEqual({instance: 'pilot', topics: ['logs', 'preview']})
    data.emit({v: 1, type: 'response', id: data.sent.at(-1)!.id, ok: true, result: {}})

    const report = client.request('statistics.report', {instance: 'pilot'})
    await Promise.resolve()
    expect(data.sent.at(-1)?.method).toBe('statistics.report')
    const result = '舰船数据'.repeat(14000)
    const bytes = new TextEncoder().encode(JSON.stringify({
      v: 1, type: 'response', id: data.sent.at(-1)!.id, ok: true, result,
    }))
    // 结果刻意超过单帧上限，按传输协议切成多片：每片首字节 1 表示末片、0 表示续片，
    // 去掉旗标后的载荷不得超过 frameBytes - 1。
    const chunks: Uint8Array<ArrayBuffer>[] = []
    const chunkSize = webSocketTransport.frameBytes - 1
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      const content = bytes.subarray(offset, offset + chunkSize)
      const part = new Uint8Array(content.length + 1)
      part[0] = Number(offset + content.length === bytes.length)
      part.set(content, 1)
      chunks.push(part)
    }
    data.emitBytes(chunks[0].buffer)
    const operation = client.request('scheduler.stop', {instance: 'pilot'})
    expect(control.sent.at(-1)?.method).toBe('scheduler.stop')
    control.emit({v: 1, type: 'response', id: control.sent.at(-1)!.id, ok: true, result: {status: 'stopped'}})
    await expect(operation).resolves.toMatchObject({status: 'stopped'})
    chunks.slice(1).forEach(part => data.emitBytes(part.buffer))
    await expect(report).resolves.toBe(result)
    const interrupted = client.request('statistics.report', {instance: 'pilot'})
    await Promise.resolve()
    data.close()
    expect(client.getSnapshot()).toBe('ready')
    await vi.advanceTimersByTimeAsync(2000)
    const replacement = FakeSocket.latest
    expect(replacement.url).toBe(data.url)
    session(replacement, 'data')
    expect(replacement.sent[0]).toMatchObject({method: 'events.subscribe', params: {
      instance: 'pilot', topics: ['logs', 'preview'],
    }})
    await Promise.resolve()
    expect(replacement.sent[1]?.method).toBe('statistics.report')
    replacement.emit({v: 1, type: 'response', id: replacement.sent[1].id, ok: true, result: {series: []}})
    await expect(interrupted).resolves.toEqual({series: []})
  })

  it('操作连接登录后，远程数据连接单独认证', async () => {
    client.disconnect()
    client = new ApiClient()
    client.connect()
    const control = FakeSocket.latest
    control.emit({v: 1, type: 'event', topic: 'session', data: {authRequired: true, channel: 'control'}})
    expect(FakeSocket.latest).toBe(control)
    const login = client.login('测试访问密码')
    control.emit({v: 1, type: 'response', id: control.sent.at(-1)!.id, ok: true, result: {authenticated: true}})
    await login
    const data = FakeSocket.latest
    data.emit({v: 1, type: 'event', topic: 'session', data: {authRequired: true, channel: 'data'}})
    expect(data.sent).toHaveLength(1)
    expect(data.sent[0]).toMatchObject({method: 'auth.login', params: {password: '测试访问密码'}})
    const read = client.request('config.get', {instance: 'pilot'})
    data.emit({v: 1, type: 'response', id: data.sent[0].id, ok: true, result: {authenticated: true}})
    await vi.advanceTimersByTimeAsync(0)
    expect(data.sent[1]?.method).toBe('config.get')
    data.emit({v: 1, type: 'response', id: data.sent[1].id, ok: true, result: {instance: 'pilot'}})
    await expect(read).resolves.toEqual({instance: 'pilot'})
  })
})

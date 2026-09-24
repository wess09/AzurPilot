import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { WebSocketServer, WebSocket } from 'ws'
import { createMockState, fail } from './state.mjs'

// 科研物品图标：真实后端把 assets/stats/research_items 挂在这个前缀下（见
// module/api/statistics_service.py 的 research-items 静态目录）。mock 也照挂，
// 否则科研统计页的图标列全是裂图，看不出图标布局对不对。
const RESEARCH_ICON_DIR = fileURLToPath(new URL('../../assets/stats/research_items/', import.meta.url))

export function createMockServer({password = '', empty = false} = {}) {
  const state = createMockState({empty})
  const server = createServer((request, response) => {
    if (request.url?.startsWith('/research-items/')) {
      // basename 挡住 ../ 之类的越权路径，只认目录里的单层文件名
      const name = path.basename(decodeURIComponent(request.url))
      if (name.endsWith('.png')) {
        readFile(path.join(RESEARCH_ICON_DIR, name)).then(buffer => {
          response.setHeader('Content-Type', 'image/png')
          response.writeHead(200)
          response.end(buffer)
        }).catch(() => {
          response.writeHead(404)
          response.end()
        })
        return
      }
    }
    response.setHeader('Content-Type', 'application/json; charset=utf-8')
    response.writeHead(request.url === '/healthz' ? 200 : 404)
    response.end(JSON.stringify(request.url === '/healthz' ? {status: 'ok', protocolVersion: 1, mock: true} : {message: '请通过 Vite 打开前端'}))
  })
  const sockets = new WebSocketServer({noServer: true, maxPayload: 1024 * 1024})
  server.on('upgrade', (request, socket, head) => {
    let validOrigin = false
    try {validOrigin = new URL(request.headers.origin).host === request.headers.host} catch { /* 缺少来源时拒绝连接。 */ }
    if (request.url !== '/api/v1/ws' || !validOrigin) {socket.end('HTTP/1.1 403 Forbidden\r\n\r\n'); return}
    sockets.handleUpgrade(request, socket, head, ws => sockets.emit('connection', ws))
  })
  const sessions = new Set()
  sockets.on('connection', socket => {
    const session = {socket, authenticated: !password, seq: 0, topics: [], instance: null, last: new Map(), ids: new Set()}
    sessions.add(session)
    const send = message => {
      if (socket.readyState !== WebSocket.OPEN) return
      if (socket.bufferedAmount > 4 * 1024 * 1024) {socket.close(1013); return}
      socket.send(JSON.stringify(message))
    }
    session.event = (topic, data) => send({v: 1, type: 'event', topic, seq: ++session.seq, data})
    session.event('session', {authRequired: !!password, protocolVersion: 1})
    socket.on('message', raw => {
      let request
      try {
        request = JSON.parse(raw.toString())
        if (!request || request.v !== 1 || request.type !== 'request' || typeof request.id !== 'string' || !request.id.length || request.id.length > 100 || typeof request.method !== 'string') fail('INVALID_REQUEST', '请求信封无效')
        if (session.ids.has(request.id)) fail('DUPLICATE_REQUEST', '请求 ID 重复')
        session.ids.add(request.id)
        if (session.ids.size > 128) session.ids.delete(session.ids.values().next().value)
        let result
        if (request.method === 'auth.login') {
          if ((request.params?.password ?? '') !== password) fail('UNAUTHORIZED', '访问密码不正确')
          session.authenticated = true; result = {authenticated: true}
        } else {
          if (!session.authenticated) fail('UNAUTHORIZED', '请先登录')
          result = state.dispatch(request.method, request.params)
          if (request.method === 'events.subscribe') {session.topics = result.topics; session.instance = result.instance; session.last.clear()}
        }
        send({v: 1, type: 'response', id: request.id, ok: true, result})
        publish()
      } catch (error) {
        send({v: 1, type: 'response', id: request?.id ?? '', ok: false, error: {code: error.code ?? 'INVALID_REQUEST', message: error.code ? error.message : '请求格式无效', details: error.details ?? null}})
      }
    })
    socket.on('close', () => sessions.delete(session))
  })
  function publish() {
    for (const session of sessions) {
      if (!session.authenticated) continue
      for (const topic of session.topics) {
        try {
          if (topic === 'preview' && session.last.has(topic) && Date.now() - (session.previewAt ?? 0) < 3000) continue
          if (topic === 'preview') session.previewAt = Date.now()
          const method = {instances: 'instances.list', overview: 'overview.get', logs: 'logs.get', preview: 'preview.capture'}[topic]
          const data = state.dispatch(method, topic === 'instances' ? {} : {instance: session.instance})
          const serialized = JSON.stringify(data)
          if (session.last.get(topic) !== serialized) {session.event(topic, data); session.last.set(topic, serialized)}
        } catch (error) {
          const data = {topic, instance: session.instance, code: error.code, message: error.message}
          const serialized = JSON.stringify(data)
          if (session.last.get(topic) !== serialized) {session.event('subscription.error', data); session.last.set(topic, serialized)}
        }
      }
    }
  }
  const interval = setInterval(() => {state.tick(); publish()}, 3000)
  interval.unref()
  const close = () => new Promise(resolve => {
    clearInterval(interval)
    for (const socket of sockets.clients) socket.terminate()
    sockets.close(() => server.close(resolve))
  })
  return {server, close}
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const {values: options} = parseArgs({options: {dev: {type: 'boolean'}, port: {type: 'string', default: '5173'}}})
  const port = Number(process.env.AZURPILOT_MOCK_PORT ?? 22392)
  const mock = createMockServer({password: process.env.AZURPILOT_MOCK_PASSWORD ?? '', empty: process.env.AZURPILOT_MOCK_SCENARIO === 'empty'})
  mock.server.on('error', error => {console.error(`模拟服务启动失败：${error.message}`); process.exit(1)})
  mock.server.listen(port, '127.0.0.1', () => console.info(`前端模拟服务：http://127.0.0.1:${port}（数据只保存在内存）`))
  let vite
  if (options.dev) {
    const {createServer} = await import('vite')
    vite = await createServer({mode: 'mock', server: {host: '127.0.0.1', port: Number(options.port)}})
    await vite.listen()
    vite.printUrls()
  }
  let closing = false
  const shutdown = async () => {
    if (closing) return
    closing = true
    await vite?.close(); await mock.close()
  }
  process.on('SIGINT', shutdown)
  process.on('SIGTERM', shutdown)
}

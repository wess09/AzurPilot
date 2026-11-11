import {webSocketTransport} from './generated'
import type {ApiEvent, ApiResponse} from './types'
import {translateCurrentUi} from '../i18n'

export class ApiError extends Error {
  constructor(public code: string, message: string, public details?: unknown) { super(message) }
}

type Connection = 'connecting' | 'ready' | 'auth' | 'offline'
type Channel = 'control' | 'data'
type Pending = {
  resolve: (value: unknown) => void
  reject: (error: Error) => void
  timer: ReturnType<typeof setTimeout>
}
type Session = {authRequired: boolean; channel?: Channel}
type SessionHandler = (session: Session, current: () => boolean) => void | Promise<void>

const {frameBytes, requestBytes, responseBytes} = webSocketTransport
const timeoutMs = 45000
const disconnected = () => new ApiError('DISCONNECTED', translateCurrentUi('api.disconnected'))
const timedOut = () => new ApiError('TIMEOUT', translateCurrentUi('api.timeout'))

/** 把连续的二进制分片恢复成一条 JSON 消息。 */
class IncomingMessage {
  private parts: Uint8Array[] = []
  private size = 0

  decode(data: string | ArrayBuffer, fragmented: boolean): ApiResponse | ApiEvent | undefined {
    if (typeof data === 'string') {
      if (this.size) throw new Error('Incomplete WebSocket message')
      if (fragmented && data.length * 3 > frameBytes &&
          new TextEncoder().encode(data).length > frameBytes) throw new Error('WebSocket frame too large')
      return JSON.parse(data)
    }
    if (!fragmented || !(data instanceof ArrayBuffer)) throw new Error('Unexpected WebSocket message')
    const bytes = new Uint8Array(data)
    const final = bytes[0]
    if (bytes.length < 2 || bytes.length > frameBytes ||
        (final !== 1 && (final !== 0 || bytes.length !== frameBytes))) {
      throw new Error('Invalid WebSocket fragment')
    }
    this.size += bytes.length - 1
    if (this.size > responseBytes) throw new Error('WebSocket message too large')
    this.parts.push(bytes.subarray(1))
    if (!final) return
    const payload = new Uint8Array(this.size)
    let offset = 0
    for (const part of this.parts) {
      payload.set(part, offset)
      offset += part.length
    }
    this.parts = []
    this.size = 0
    return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(payload))
  }
}

export class RpcSocket {
  private socket?: WebSocket
  private pending = new Map<string, Pending>()
  private listeners = new Set<() => void>()
  private retry?: ReturnType<typeof setTimeout>
  private heartbeat?: ReturnType<typeof setInterval>
  private attempt = 0
  private stopped = true
  private fragmented = false
  private state: Connection = 'connecting'
  private counter = 0
  private lastReceived = 0

  constructor(
    private channel: Channel,
    private authenticate: SessionHandler,
    private onEvent: (event: ApiEvent) => void,
    private onReady: () => void = () => {},
  ) {}

  getSnapshot = () => this.state
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  private setState(state: Connection) {
    this.state = state
    this.listeners.forEach(listener => listener())
  }

  connect = () => {
    if (this.socket && this.socket.readyState < 2) return
    clearTimeout(this.retry)
    this.stopped = false
    this.fragmented = false
    this.setState('connecting')
    // 隧道经 /<peer_id>/ 反代，两个连接均跟随页面的 base URI。
    const url = new URL('api/v1/ws', document.baseURI)
    url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    url.searchParams.set('channel', this.channel)
    const socket = this.socket = new WebSocket(url)
    socket.binaryType = 'arraybuffer'
    const incoming = new IncomingMessage()
    let sessionSeen = false
    const current = () => socket === this.socket
    socket.onmessage = event => {
      if (!current()) return
      this.lastReceived = Date.now()
      let message: ApiResponse | ApiEvent | undefined
      try { message = incoming.decode(event.data, this.fragmented) }
      catch { socket.close(4002); return }
      if (message === undefined) return
      if (!message || message.v !== 1) { socket.close(4002); return }
      if (message.type === 'response') {
        const pending = this.pending.get(message.id)
        if (!pending) return
        clearTimeout(pending.timer)
        this.pending.delete(message.id)
        if (message.ok) pending.resolve(message.result)
        else pending.reject(new ApiError(message.error?.code ?? 'UNKNOWN',
          message.error?.message ?? translateCurrentUi('api.requestFailed'), message.error?.details))
      } else if (message.type === 'event') {
        if (message.topic === 'session' && !sessionSeen) {
          sessionSeen = true
          const session = message.data as Session
          this.fragmented = session.channel === this.channel
          if (this.channel === 'data' && !this.fragmented) { socket.close(4002); return }
          const denied = () => {
            if (current()) this.setState('auth')
          }
          try {
            const authentication = this.authenticate(session, current)
            if (authentication) void authentication.then(() => {
              if (current()) this.ready()
            }).catch(denied)
            else this.ready()
          } catch { denied() }
        }
        this.onEvent(message)
      }
    }
    socket.onclose = () => {
      if (!current()) return
      this.socket = undefined
      this.clearPending()
      const denied = this.channel === 'data' && this.state === 'auth'
      if (!denied) this.setState('offline')
      if (!this.stopped && !denied) {
        this.retry = setTimeout(this.connect, Math.min(15000, 800 * 2 ** this.attempt++) + Math.random() * 400)
      }
    }
    socket.onerror = () => socket.close()
  }

  get splitTransport() { return this.fragmented }

  ready() {
    if (this.socket?.readyState !== WebSocket.OPEN) return
    this.attempt = 0
    clearInterval(this.heartbeat)
    this.heartbeat = setInterval(() => {
      const socket = this.socket
      if (Date.now() - this.lastReceived > timeoutMs) { socket?.close(); return }
      void this.request('system.ping', {}).catch(() => socket?.close())
    }, 15000)
    this.state = 'ready'
    this.onReady()
    this.listeners.forEach(listener => listener())
  }

  waitReady() {
    if (this.state === 'ready') return Promise.resolve()
    if (this.stopped || this.state === 'auth') return Promise.reject(disconnected())
    return new Promise<void>((resolve, reject) => {
      const unsubscribe = this.subscribe(() => {
        if (this.state === 'ready' || this.stopped || this.state === 'auth') {
          unsubscribe()
          clearTimeout(timer)
          if (this.state === 'ready') resolve()
          else reject(disconnected())
        }
      })
      const timer = setTimeout(() => { unsubscribe(); reject(timedOut()) }, timeoutMs)
    })
  }

  request<T>(method: string, params: unknown): Promise<T> {
    const socket = this.socket
    if (socket?.readyState !== WebSocket.OPEN ||
        (this.state !== 'ready' && method !== 'auth.login' && method !== 'auth.launcher')) {
      return Promise.reject(new ApiError('DISCONNECTED', translateCurrentUi('api.notConnected')))
    }
    const id = this.channel + '-' + Date.now() + '-' + ++this.counter
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(timedOut()) }, timeoutMs)
      this.pending.set(id, {resolve: value => resolve(value as T), reject, timer})
      try {
        this.send(socket, JSON.stringify({v: 1, type: 'request', id, method, params}))
      } catch (error) {
        clearTimeout(timer)
        this.pending.delete(id)
        reject(error)
      }
    })
  }

  private send(socket: WebSocket, message: string) {
    if (!this.fragmented || message.length * 3 <= frameBytes) { socket.send(message); return }
    const bytes = new TextEncoder().encode(message)
    if (bytes.length <= frameBytes) { socket.send(message); return }
    if (bytes.length > requestBytes) throw new ApiError('INVALID_REQUEST', '请求超过 8 MiB 限制')
    const size = frameBytes - 1
    for (let offset = 0; offset < bytes.length; offset += size) {
      const data = bytes.subarray(offset, offset + size)
      const part = new Uint8Array(data.length + 1)
      part[0] = Number(offset + size >= bytes.length)
      part.set(data, 1)
      try { socket.send(part) }
      catch (error) { socket.close(); throw error }
    }
  }

  private clearPending() {
    clearInterval(this.heartbeat)
    this.pending.forEach(pending => {
      clearTimeout(pending.timer)
      pending.reject(disconnected())
    })
    this.pending.clear()
  }

  disconnect() {
    this.stopped = true
    clearTimeout(this.retry)
    const socket = this.socket
    this.socket = undefined
    socket?.close()
    this.clearPending()
    this.setState('offline')
  }
}

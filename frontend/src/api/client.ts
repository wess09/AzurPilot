/**
 * @fileoverview 统一分发 WebUI RPC：操作连接的状态驱动登录界面，数据连接独立恢复。
 */
import {dataMethods, webSocketTransport, type Parameters} from './generated'
import {ApiError, RpcSocket} from './socket'
import type {ApiEvent, Results} from './types'

export {ApiError} from './socket'

const dataRequests = new Set<string>(dataMethods)
const dataTopics = new Set<string>(webSocketTransport.dataTopics)
type Subscription = Parameters['events.subscribe']

/**
 * WebUI 的统一 RPC 客户端：按方法把请求分发到操作、数据两条连接，并把事件广播给订阅者。
 * 操作连接的状态（getSnapshot）驱动登录界面；数据连接断开后独立恢复，读取类请求重连成功后自动重试一次。
 */
export class ApiClient {
  private password = ''
  private launcherTicket?: string
  private events = new Set<(event: ApiEvent) => void>()
  private dataSubscription?: Subscription
  private emit = (event: ApiEvent) => this.events.forEach(listener => listener(event))

  private data = new RpcSocket('data', session => {
    if (!session.authRequired) return
    if (!this.password) throw new Error('Missing data connection credentials')
    return this.data.request<void>('auth.login', {password: this.password})
  }, event => {
    if (event.topic !== 'session') this.emit(event)
  }, () => this.subscribeData())

  private control = new RpcSocket('control', (session, current) => {
    if (this.launcherTicket) {
      const ticket = this.launcherTicket
      this.launcherTicket = undefined
      return this.control.request<void>('auth.launcher', {ticket}).catch(error => {
        if (session.authRequired) throw error
      })
    }
    if (!session.authRequired) return
    if (!this.password) throw new Error('Missing access password')
    return this.authenticate(this.password, current)
  }, this.emit, () => {
    if (!this.control.splitTransport) {
      this.data.disconnect()
      return
    }
    if (this.data.getSnapshot() === 'auth') this.data.disconnect()
    this.data.connect()
  })

  getSnapshot = this.control.getSnapshot
  subscribe = this.control.subscribe
  /** 订阅事件广播；返回取消订阅函数。 */
  onEvent = (listener: (event: ApiEvent) => void) => {
    this.events.add(listener)
    return () => { this.events.delete(listener) }
  }

  /** 恢复本地保存的密码、从地址栏摘走启动器票据后接通连接；存储不可用时仍走会话内登录。 */
  connect = () => {
    if (!this.password) {
      try { this.password = window.localStorage.getItem('azurpilot.access-password') ?? '' }
      catch { /* 浏览器禁用存储时保留会话登录。 */ }
    }
    try {
      const page = new URL(window.location.href)
      const ticket = page.searchParams.get('launcherTicket')
      if (ticket) {
        this.launcherTicket = ticket
        page.searchParams.delete('launcherTicket')
        window.history.replaceState(null, '', page.toString())
      }
    } catch { /* 无导航上下文的测试及受限浏览器仍可正常连接。 */ }
    this.control.connect()
  }

  private async authenticate(password: string, current = () => true) {
    try { await this.control.request('auth.login', {password}) }
    catch (error) {
      if (current() && error instanceof ApiError && error.code === 'UNAUTHORIZED') {
        this.password = ''
        try { window.localStorage.removeItem('azurpilot.access-password') } catch { /* 存储不可用。 */ }
      }
      throw error
    }
    if (current()) {
      this.password = password
      try { window.localStorage.setItem('azurpilot.access-password', password) } catch { /* 保留会话登录。 */ }
    }
  }

  /** 用密码认证并把操作连接置为就绪；认证成功后密码写入 localStorage 供下次自动恢复。 */
  async login(password: string) {
    await this.authenticate(password)
    this.control.ready()
  }

  private subscribeData() {
    const subscription = this.dataSubscription
    if (!subscription || this.data.getSnapshot() !== 'ready') return
    void this.data.request('events.subscribe', subscription).catch(error => {
      if (this.dataSubscription !== subscription || this.data.getSnapshot() !== 'ready') return
      for (const topic of subscription.topics) {
        this.emit({v: 1, type: 'event', seq: 0, topic: 'subscription.error', data: {
          topic, instance: subscription.instance, code: error.code, message: error.message,
        }})
      }
    })
  }

  private async subscribeEvents(params: Subscription): Promise<Results['events.subscribe']> {
    const result = await this.control.request<Results['events.subscribe']>('events.subscribe', {
      instance: params.instance, topics: params.topics.filter(topic => !dataTopics.has(topic)),
    })
    this.dataSubscription = {instance: params.instance, topics: params.topics.filter(topic => dataTopics.has(topic))}
    this.subscribeData()
    return {...result, topics: params.topics}
  }

  private async requestData<T>(method: string, params: unknown): Promise<T> {
    await this.data.waitReady()
    try { return await this.data.request<T>(method, params) }
    catch (error) {
      if (!(error instanceof ApiError) || error.code !== 'DISCONNECTED') throw error
      // 数据通道只处理读取，重连后可以重试一次。写操作始终由调用方决定是否重试。
      await this.data.waitReady()
      return this.data.request<T>(method, params)
    }
  }

  request<M extends keyof Results & keyof Parameters>(method: M, params: Parameters[M]): Promise<Results[M]> {
    if (this.control.splitTransport && method === 'events.subscribe') {
      return this.subscribeEvents(params as Subscription) as Promise<Results[M]>
    }
    if (this.control.splitTransport && dataRequests.has(method)) {
      return this.requestData<Results[M]>(method, params)
    }
    return this.control.request<Results[M]>(method, params)
  }

  disconnect() {
    this.password = ''
    this.launcherTicket = undefined
    this.dataSubscription = undefined
    this.data.disconnect()
    this.control.disconnect()
  }
}

/** 全局唯一实例：整个前端直接 import 使用，不自行 new。 */
export const api = new ApiClient()

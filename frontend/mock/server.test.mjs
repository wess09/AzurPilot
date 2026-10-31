import { once } from 'node:events'
import { WebSocket } from 'ws'
import { expect, it } from 'vitest'
import { createMockServer } from './server.mjs'

it('WebSocket 认证、实例订阅替换与空订阅按协议工作', async () => {
  const mock = createMockServer({password: 'mock-password'})
  mock.server.listen(0, '127.0.0.1')
  await once(mock.server, 'listening')
  const port = mock.server.address().port
  const socket = new WebSocket(`ws://127.0.0.1:${port}/api/v1/ws`, {origin: `http://127.0.0.1:${port}`})
  const events = []
  const pending = new Map()
  let counter = 0
  socket.on('message', raw => {
    const message = JSON.parse(raw.toString())
    if (message.type === 'event') events.push(message)
    else {pending.get(message.id)?.(message); pending.delete(message.id)}
  })
  const request = (method, params = {}) => new Promise(resolve => {
    const id = String(++counter)
    pending.set(id, resolve)
    socket.send(JSON.stringify({v: 1, type: 'request', id, method, params}))
  })
  try {
    await once(socket, 'open')
    expect((await request('instances.list')).error.code).toBe('UNAUTHORIZED')
    expect(events[0].data.authRequired).toBe(true)
    expect((await request('auth.login', {password: 'wrong'})).ok).toBe(false)
    expect((await request('auth.login', {password: 'mock-password'})).ok).toBe(true)
    await request('events.subscribe', {instance: 'demo-main', topics: ['instances', 'overview']})
    await request('system.ping')
    expect(events.filter(event => event.topic === 'overview').at(-1).data.instance).toBe('demo-main')
    await request('events.subscribe', {instance: 'demo-alt', topics: ['overview']})
    await request('system.ping')
    expect(events.filter(event => event.topic === 'overview').at(-1).data.instance).toBe('demo-alt')
    await request('events.subscribe', {topics: []})
    const length = events.length
    await request('scheduler.start', {instance: 'demo-main'})
    await request('system.ping')
    expect(events).toHaveLength(length)
    expect(events.map(event => event.seq)).toEqual(events.map((_, index) => index + 1))
  } finally {socket.terminate(); await mock.close()}
})

it('股票实例注册不创建交易账户，旧交易代理方法已移除', async () => {
  const mock = createMockServer()
  mock.server.listen(0, '127.0.0.1')
  await once(mock.server, 'listening')
  const port = mock.server.address().port
  const socket = new WebSocket(`ws://127.0.0.1:${port}/api/v1/ws`, {origin: `http://127.0.0.1:${port}`})
  const pending = new Map()
  let counter = 0
  socket.on('message', raw => {const value=JSON.parse(raw.toString());if(value.type==='response'){pending.get(value.id)?.(value);pending.delete(value.id)}})
  const request = (method, params = {}) => new Promise(resolve => {const id=String(++counter);pending.set(id,resolve);socket.send(JSON.stringify({v:1,type:'request',id,method,params:{instance:'demo-main',...params}}))})
  try {
    await once(socket,'open')
    expect((await request('stock.status')).result).toMatchObject({registered:false,bound:false})
    const registered=await request('stock.register',{username:'测试股票',noticeVersion:'stock-public-v2-20261101'})
    expect(registered.result).toMatchObject({registered:true,bound:false,stock:{name:'测试股票'}})
    expect(registered.result.bindingCode).toBeTruthy()
    expect(JSON.stringify(registered)).not.toContain('privateKey')
    expect((await request('stock.request',{path:'/login'})).ok).toBe(false)
  } finally {socket.terminate();await mock.close()}
})

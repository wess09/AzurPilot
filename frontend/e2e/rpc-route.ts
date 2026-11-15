import type {Page, WebSocketRoute} from '@playwright/test'
import {webSocketTransport} from '../src/api/generated'

const {frameBytes} = webSocketTransport
type JsonRoute = {
  channel: string | null
  connectToServer: () => JsonRoute
  onMessage: (receive: (message: string) => void) => void
  send: (message: string | Buffer) => void
}

// 用完整 JSON 编写测试拦截器，测试改写后的消息仍按真实协议收发。
export function routeRpc(page: Page, handler: (socket: JsonRoute) => void) {
  return page.routeWebSocket(/\/api\/v1\/ws(?:\?channel=(?:control|data))?$/, socket => {
    const channel = new URL(socket.url()).searchParams.get('channel')
    function wrap(route: WebSocketRoute): JsonRoute {
      return {
        channel,
        connectToServer: () => wrap(route.connectToServer()),
        onMessage(receive) {
          let parts: Buffer[] = []
          route.onMessage(message => {
            if (typeof message === 'string') { receive(message); return }
            parts.push(message.subarray(1))
            if (message[0] === 1) {
              const text = Buffer.concat(parts).toString('utf8')
              parts = []
              receive(text)
            }
          })
        },
        send(message) {
          const bytes = Buffer.from(message)
          if (!channel || bytes.length <= frameBytes) { route.send(bytes.toString('utf8')); return }
          for (let offset = 0; offset < bytes.length; offset += frameBytes - 1) {
            const end = offset + frameBytes - 1
            route.send(Buffer.concat([Buffer.from([Number(end >= bytes.length)]), bytes.subarray(offset, end)]))
          }
        },
      }
    }
    handler(wrap(socket))
  })
}

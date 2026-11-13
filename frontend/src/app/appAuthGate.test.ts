import { describe, expect, it } from 'vitest'
import appSource from './App.tsx?raw'

// App 的登录闸门是一句提前返回：它必须排在 App 全部 Hook 之后，
// 否则同一次会话里 Hook 数量会随连接状态变化，React 抛 #300 崩掉整页。
const GATE = "if (connection === 'auth') return <Login/>"

/** 取出 App 组件体：从 export function App() 起，到顶格的那个右花括号为止。 */
function appBody(source: string): string {
  const start = source.indexOf('export function App()')
  if (start < 0) throw new Error('App.tsx 里找不到 export function App()')
  const end = source.indexOf('\n}', start)
  if (end < 0) throw new Error('App 组件体没有找到结束位置')
  return source.slice(start, end)
}

/** 片段里出现的 Hook 调用名。 */
function hooks(text: string): string[] {
  return [...text.matchAll(/\buse[A-Z]\w*\(/g)].map(match => match[0])
}

describe('App 登录闸门的 Hook 顺序', () => {
  it('闸门之前有 Hook，说明取到的确实是组件体', () => {
    const body = appBody(appSource)
    const gate = body.indexOf(GATE)
    expect(gate).toBeGreaterThan(-1)
    expect(hooks(body.slice(0, gate)).length).toBeGreaterThan(0)
  })

  it('闸门之后不再有任何 Hook 调用', () => {
    const body = appBody(appSource)
    const gate = body.indexOf(GATE)
    expect(hooks(body.slice(gate + GATE.length))).toEqual([])
  })
})

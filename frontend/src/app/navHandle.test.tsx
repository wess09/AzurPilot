/**
 * @fileoverview 侧栏把手（NavHandle）随背景开关显隐的渲染回归测试。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from './context'
import type { BackgroundSnapshot } from './background'
import { NavHandle } from './NavHandle'

const ui = ((key: string) => key) as never
const context = {ui, language: 'zh-CN'} as unknown as AppContextValue

const snapshot = (source: 'off' | 'url' | 'upload'): BackgroundSnapshot => ({
  source, kind: 'image', urls: ['https://example.com/a.png'], active: 0, name: '',
  assetUrl: '', directUrl: '', resolving: false, resolveError: '', loading: false, revision: 0,
})

// 只断言把手节点是否出现，用静态字符串渲染即可，不必为此挂 jsdom。
const render = (source: 'off' | 'url' | 'upload') => renderToStaticMarkup(
  <AppContext.Provider value={context}>
    <NavHandle background={snapshot(source)}/>
  </AppContext.Provider>,
)

describe('侧栏把手与背景', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('背景关闭时不渲染把手', () => {
    const html = render('off')
    expect(html).not.toContain('nav-handle')
  })

  it('背景开着时渲染把手', () => {
    const html = render('url')
    expect(html).toContain('nav-handle')
  })
})

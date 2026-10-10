import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from './context'
import type { BackgroundSnapshot } from './background'

/* 把手在铺着壁纸时才出现；主题固定成支持背景的一档。 */
vi.mock('./theme', async importOriginal => ({
  ...(await importOriginal<typeof import('./theme')>()),
  getThemePreference: () => ({theme: 'light'}),
  showsWallpaper: (theme: string, source: string) => source !== 'off' && ['light', 'dark', 'legacy-light', 'legacy-dark'].includes(theme),
}))

const { NavHandle } = await import('./NavHandle')

const ui = ((key: string) => key) as never
const context = {ui, language: 'zh-CN'} as unknown as AppContextValue

const snapshot = (source: 'off' | 'url' | 'upload'): BackgroundSnapshot => ({
  source, kind: 'image', urls: ['https://example.com/a.png'], active: 0, name: '',
  assetUrl: '', directUrl: '', resolving: false, resolveError: '', loading: false, revision: 0,
})

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

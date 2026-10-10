import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import { translateUi } from '../i18n'
import { FleetInfo } from './FleetInfoPage'

function render(value: unknown) {
  return renderToStaticMarkup(<AppContext.Provider value={{
    ui: (key, params) => translateUi('zh-CN', key, params),
  } as AppContextValue}><FleetInfo value={value}/></AppContext.Provider>)
}

describe('舰队信息心情兼容性', () => {
  it('显示名称等级和心情，零值有效，缺失或越界为未知', () => {
    const markup = render({vanguard: {1: [
      {name: '甲', level: 125, emotion: 150}, {name: '乙', level: 100, emotion: 0},
      {name: '丙', level: 70, emotion: null}, {name: '丁', level: 10, emotion: 151},
    ]}})
    expect(markup).toContain('甲')
    expect(markup).toContain('Lv.125 · 心情 150')
    expect(markup).toContain('Lv.100 · 心情 0')
    expect(markup).toContain('Lv.70 · 心情 未知')
    expect(markup).toContain('Lv.10 · 心情 未知')
  })

  it('兼容旧字符串舰船与旧对象、JSON 字符串', () => {
    const markup = render(JSON.stringify({main: {1: ['旧舰船', {name: '旧对象', level: 125}]}}))
    expect(markup).toContain('旧舰船')
    expect(markup).toContain('旧对象')
    expect(markup).toContain('Lv.125 · 心情 未知')
  })
})

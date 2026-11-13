/**
 * @fileoverview 材质细节面板的渲染回归测试：分区滑块、还原按钮可用性。
 */

import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import { MaterialDetailPanel } from './ThemeCustomPreference'
import { REGIONS, regionKnobs, regionProps } from '../app/themeKnobs'

const ui = ((key: string) => key) as never
// 类别选择器用的是主题感知的分段控件，它要读上下文（材质族/朴素族渲染不同）。
const context = {ui, language: 'zh-CN', theme: 'default'} as unknown as AppContextValue
const theme = context.theme

const render = (params: Record<string, number> = {}, initialRegion?: (typeof REGIONS)[number]) => renderToStaticMarkup(
  <AppContext.Provider value={{...context, theme}}>
    <MaterialDetailPanel
      regions={REGIONS}
      custom={{params}}
      ui={ui}
      onKnob={vi.fn()}
      onResetKnob={vi.fn()}
      onResetRegion={vi.fn()}
      onResetAll={vi.fn()}
      initialRegion={initialRegion}
    />
  </AppContext.Provider>,
)

describe('材质细节二级菜单', () => {
  it('顶部列出四个类别，默认只显示第一类接入的滑块', () => {
    const html = render()
    for (const region of REGIONS) expect(html, region).toContain(`settings.region${region[0].toUpperCase()}${region.slice(1)}`)
    expect(html.match(/role="slider"/g) ?? []).toHaveLength(regionProps.surface.length)
    for (const key of ['settings.propAlpha', 'settings.glassBlur', 'settings.glassSaturation']) expect(html, key).toContain(key)
    expect(html).toContain('settings.materialDetailScope')
    for (const knob of regionKnobs.filter(item => item.region !== REGIONS[0])) expect(html, knob.id).not.toContain(`ui-knob-${knob.id}`)
  })

  it('换一个类别就换成它自己的那几条滑块', () => {
    const html = render({}, 'control')
    expect(html.match(/role="slider"/g) ?? []).toHaveLength(regionProps.control.length)
    for (const knob of regionKnobs.filter(item => item.region === 'control')) expect(html, knob.id).toContain(`ui-knob-${knob.id}`)
    expect(html).not.toContain('ui-knob-surface.alpha')
  })

  it('未动过时项还原与本区还原都禁用，全部还原始终可点', () => {
    const knobsInSurface = regionProps.surface.length
    expect(render().match(/disabled=""/g) ?? []).toHaveLength(knobsInSurface + 1)
    expect(render({'surface.blur': 20}).match(/disabled=""/g) ?? []).toHaveLength(knobsInSurface - 1)
    expect(render({'surface.blur': 20})).toContain('settings.customResetAll')
  })
})

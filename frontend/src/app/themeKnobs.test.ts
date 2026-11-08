import { describe, expect, it } from 'vitest'
import legacyPalette from '../styles/legacy-palette.css?raw'
import { REGIONS, knobFor, regionKnobs, regionProps } from './themeKnobs'

const contractKeys = new Set([...legacyPalette.matchAll(/(--theme-[a-z0-9-]+)\s*:/g)].map(m => m[1]))

describe('区域旋钮目录', () => {
  it('每个区域只暴露 regionProps 声明的旋钮，不多不少', () => {
    const total = REGIONS.reduce((sum, region) => sum + regionProps[region].length, 0)
    expect(regionKnobs).toHaveLength(total)
    for (const region of REGIONS) {
      expect(regionKnobs.filter(knob => knob.region === region).map(knob => knob.prop)).toEqual([...regionProps[region]])
    }
  })

  it('只暴露实测有可见效果的参数：磨砂只给带材质的面（含弹窗与菜单），控件只有不透明度，圆角与阴影一个都不放', () => {
    expect(regionKnobs.filter(knob => knob.prop === 'blur').map(knob => knob.region)).toEqual(['surface', 'plate', 'inset', 'modal', 'menu'])
    expect(regionKnobs.filter(knob => knob.prop === 'saturation').map(knob => knob.region)).toEqual(['surface', 'plate', 'inset', 'modal', 'menu'])
    expect(regionKnobs.filter(knob => knob.prop === 'radius').map(knob => knob.region)).toEqual([])
    expect(regionKnobs.filter(knob => knob.prop === 'shadow').map(knob => knob.region)).toEqual([])
    expect(regionKnobs.filter(knob => knob.region === 'control').map(knob => knob.prop)).toEqual(['alpha'])
    const ids = regionKnobs.map(knob => knob.id)
    for (const id of [
      'surface.radius', 'plate.radius', 'inset.radius', 'control.radius', 'modal.radius', 'menu.radius',
      'surface.shadow', 'plate.shadow', 'inset.shadow', 'control.shadow', 'modal.shadow', 'menu.shadow',
      'control.blur', 'control.saturation',
    ]) {
      expect(ids, id).not.toContain(id)
    }
  })
  it('每个旋钮写入的 token 都在契约键里（拼错会静默无效）', () => {
    for (const knob of regionKnobs) {
      expect(knob.token, knob.id).toBe(`--theme-${knob.region}-${knob.prop}`)
      expect(contractKeys.has(knob.token), knob.id).toBe(true)
    }
  })

  it('范围自洽：min < max、step 为正、量程端点的写法带得出单位', () => {
    for (const knob of regionKnobs) {
      expect(knob.min, knob.id).toBeLessThan(knob.max)
      expect(knob.step, knob.id).toBeGreaterThan(0)
      expect(knob.fallback, knob.id).toBeGreaterThanOrEqual(knob.min)
      expect(knob.fallback, knob.id).toBeLessThanOrEqual(knob.max)
      expect(knob.format(knob.max), knob.id).toContain(knob.unit)
    }
  })

  it('knobFor 只认目录里的 id', () => {
    expect(knobFor('plate.alpha')?.token).toBe('--theme-plate-alpha')
    expect(knobFor('plate.opacity')).toBeUndefined()
    expect(knobFor('unknown.alpha')).toBeUndefined()
  })
})

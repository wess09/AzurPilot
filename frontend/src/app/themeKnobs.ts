/**
 * @fileoverview 主题外观旋钮的目录：定义可调区域、每个区域的参数范围与写入的 CSS 令牌。
 */
import type { UiKey } from '../i18n'

/**
 * 可调区域：四个层级（一级面、二级贴片、三级嵌面、控件）加两个按位置命名的区域（弹窗、菜单）。
 * 控件独立成组，因为它挂在哪一层随放置位置漂移；弹窗与菜单同理，它们不是某一层，而是分层覆盖不到的两类面。
 */
export const REGIONS = ['surface', 'plate', 'inset', 'control', 'modal', 'menu'] as const
export type RegionId = typeof REGIONS[number]

/** 参数全集。契约层给每个区域都铺了圆角与阴影的键，界面只暴露实测有可见效果的那几组（见 regionProps）。 */
const PROPS = ['alpha', 'blur', 'saturation', 'radius', 'shadow'] as const
type KnobProp = typeof PROPS[number]

export type RegionKnob = {
  /** 旋钮标识：`<区域>.<参数>`，也是偏好里的键。 */
  id: `${RegionId}.${KnobProp}`
  region: RegionId
  prop: KnobProp
  labelKey: UiKey
  unit: 'px' | '%'
  min: number
  max: number
  step: number
  /** 主题取值读不出数值时滑块的标称位置。 */
  fallback: number
  /** 该旋钮写入的契约参数键。 */
  token: string
  /** 数值 → CSS 值。 */
  format: (value: number) => string
}

const px = (value: number) => `${value}px`
const percent = (value: number) => `${value}%`

/** 各参数的取值范围与写法只在这里定义一次；区域只决定写入哪个 token。 */
const propSpec: Record<KnobProp, {labelKey: UiKey; unit: 'px' | '%'; min: number; max: number; step: number; fallback: number; format: (value: number) => string}> = {
  alpha: {labelKey: 'settings.propAlpha', unit: '%', min: 0, max: 100, step: 5, fallback: 80, format: percent},
  blur: {labelKey: 'settings.glassBlur', unit: 'px', min: 0, max: 48, step: 1, fallback: 16, format: px},
  saturation: {labelKey: 'settings.glassSaturation', unit: '%', min: 70, max: 180, step: 5, fallback: 120, format: percent},
  radius: {labelKey: 'settings.customRadius', unit: 'px', min: 0, max: 48, step: 1, fallback: 12, format: px},
  shadow: {labelKey: 'settings.customShadow', unit: 'px', min: 0, max: 48, step: 1, fallback: 24, format: value => value === 0 ? 'none' : `0 ${Math.round(value / 3)}px ${value * 2}px rgb(0 0 0 / .18)`},
}

/** 区域名（界面里作为折叠分组的标题）。 */
export const regionLabels: Record<RegionId, UiKey> = {
  surface: 'settings.regionSurface',
  plate: 'settings.regionPlate',
  inset: 'settings.regionInset',
  control: 'settings.regionControl',
  modal: 'settings.regionModal',
  menu: 'settings.regionMenu',
}

/**
 * 每个区域实际接入界面的旋钮，只列实测有可见效果的参数：磨砂给带材质的面（一至三级与弹窗、菜单），
 * 控件只有不透明度，圆角与阴影一个都不放。
 */
export const regionProps: Record<RegionId, readonly KnobProp[]> = {
  surface: ['alpha', 'blur', 'saturation'],
  plate: ['alpha', 'blur', 'saturation'],
  inset: ['alpha', 'blur', 'saturation'],
  control: ['alpha'],
  modal: ['alpha', 'blur', 'saturation'],
  menu: ['alpha', 'blur', 'saturation'],
}

/** 全量旋钮目录：按区域展开 regionProps × propSpec 生成，设置界面据此渲染滑块。 */
export const regionKnobs: readonly RegionKnob[] = REGIONS.flatMap(region =>
  regionProps[region].map(prop => {
    const spec = propSpec[prop]
    return {id: `${region}.${prop}`, region, prop, token: `--theme-${region}-${prop}`, ...spec}
  }))

/** 按偏好键（`<区域>.<参数>`）查找旋钮；id 不在目录里时返回 undefined。 */
export const knobFor = (id: string) => regionKnobs.find(knob => knob.id === id)

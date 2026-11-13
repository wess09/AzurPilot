/**
 * @fileoverview 主题大类的自定义参数与品牌配色：按大类存 localStorage，应用时折算成 CSS token，并迁移旧版全局旋钮。
 */

import { accentTokens, paletteColors, palettes, readCustomPalettes, type Palette, type ResolvedMode } from './palettes'
import { knobFor, type RegionId } from './themeKnobs'
import type { Family } from './theme'

/** 一个大类的自定义项：区域参数（键为 `<区域>.<参数>`）+ 可选的品牌配色（未选则跟随主题自带配色）。 */
export type FamilyCustom = {params: Record<string, number>; palette?: Palette}

const knobsKey = (family: Family) => `azurpilot.custom.${family}`
/** 自定义配色的定义是全局资产，只有「选哪套」按大类各存。 */
const customPalettesKey = 'azurpilot.custom-palettes'

const isPalette = (value: unknown): value is Palette =>
  typeof value === 'string' && ((palettes as readonly string[]).includes(value) || /^custom:[\w-]+$/.test(value))

// 早期版本按「玻璃参数 + 圆角 + 阴影」五个全局旋钮存，键名没有区域；读到就折算到一级面。
// 圆角与阴影已不在界面旋钮目录里（见 themeKnobs 的 regionProps），旧值折算后一并落空。
const legacyKeys: Record<string, string> = {blur: 'surface.blur', saturation: 'surface.saturation', opacity: 'surface.alpha', radius: 'surface.radius'}

// 已溶解的旧区域名搬到对应的层：侧栏、顶栏、外壳并进一级面，标签页与分段控件并进控件层。
// 弹窗与菜单不在此列——它们在新模型里是独立区域，旧值按本区生效。
// 参数在目标层没有旋钮时（如标签页的圆角）自然落空。同名冲突时后读到的胜出。
const legacyRegion: Record<string, RegionId> = {
  sidebar: 'surface', topbar: 'surface', chrome: 'surface',
  tab: 'control', segment: 'control',
}
const toLayer = (id: string) => {
  const dot = id.indexOf('.')
  const layer = dot > 0 ? legacyRegion[id.slice(0, dot)] : undefined
  return layer ? `${layer}${id.slice(dot)}` : id
}

function readParams(input: Record<string, unknown>) {
  const source = (input.params && typeof input.params === 'object' ? input.params : {}) as Record<string, unknown>
  const params: Record<string, number> = {}
  const accept = (id: string, value: unknown) => {
    const knob = knobFor(toLayer(id))
    if (!knob || typeof value !== 'number' || !Number.isFinite(value)) return
    params[toLayer(id)] = Math.min(knob.max, Math.max(knob.min, value))
  }
  for (const [key, value] of Object.entries(source)) accept(key, value)
  for (const [oldKey, id] of Object.entries(legacyKeys)) accept(id, input[oldKey])
  return params
}

/** 读取某大类的自定义参数与品牌配色：记录损坏或缺键时按默认态（空参数）处理，并把旧版全局旋钮折算进来。 */
export function readFamilyCustom(family: Family): FamilyCustom {
  try {
    const raw = JSON.parse(localStorage.getItem(knobsKey(family)) ?? '{}') as Record<string, unknown>
    if (!raw || typeof raw !== 'object') return {params: {}}
    return {params: readParams(raw), ...(isPalette(raw.palette) ? {palette: raw.palette} : {})}
  } catch { return {params: {}} }
}

function save(family: Family, custom: FamilyCustom) {
  try {
    /* 没有内容就不留键：无记录与默认态完全等价。 */
    if (Object.keys(custom.params).length || custom.palette) localStorage.setItem(knobsKey(family), JSON.stringify(custom))
    else localStorage.removeItem(knobsKey(family))
  } catch { /* 存储不可用时本次会话内仍生效。 */ }
}

/** 写入该大类动过的参数 token，返回写入的 token 名供调用方记账清理。 */
export function applyFamilyCustom(root: HTMLElement, family: Family, mode: ResolvedMode): string[] {
  const custom = readFamilyCustom(family)
  const written: string[] = []
  for (const [id, value] of Object.entries(custom.params)) {
    const knob = knobFor(id)
    if (!knob) continue
    const css = knob.format(value)
    if (root.style.getPropertyValue(knob.token) !== css) root.style.setProperty(knob.token, css)
    written.push(knob.token)
  }
  if (custom.palette) {
    const palettes2 = readCustomPalettes(localStorage.getItem(customPalettesKey))
    /* 材质与旧版的表面/文字/边框归主题自己管，品牌配色只换强调色一族。 */
    const tokens = accentTokens(paletteColors(custom.palette, palettes2, mode), mode)
    for (const [token, value] of Object.entries(tokens)) {
      if (root.style.getPropertyValue(token) !== value) root.style.setProperty(token, value)
      written.push(token)
    }
  }
  return written
}

/** 合并写入参数补丁：undefined 的参数项表示回默认（连同键一起删）；palette 不传则保持现状。 */
export function writeFamilyCustom(family: Family, patch: {params?: Record<string, number | undefined>; palette?: Palette}) {
  const current = readFamilyCustom(family)
  const merged: Record<string, number> = {...current.params}
  for (const [id, value] of Object.entries(patch.params ?? {})) {
    /* undefined 表示这一项回默认：连同键一起丢掉。 */
    if (value === undefined) delete merged[id]
    else merged[id] = value
  }
  save(family, {params: merged, palette: patch.palette ?? current.palette})
}

/** 只保留 keep 认可的旋钮，其余回默认。 */
function clearFamilyKnobs(family: Family, keep: (id: string) => boolean) {
  const current = readFamilyCustom(family)
  save(family, {params: Object.fromEntries(Object.entries(current.params).filter(([id]) => keep(id))), palette: current.palette})
}

/** 单个参数回默认；品牌配色保留。 */
export const clearFamilyKnob = (family: Family, id: string) => clearFamilyKnobs(family, kept => kept !== id)
/** 清掉某一区域的全部自定义参数；品牌配色保留。 */
export const clearFamilyRegion = (family: Family, region: RegionId) => clearFamilyKnobs(family, id => !id.startsWith(`${region}.`))

/** 品牌配色回到「跟随主题」：清掉选择，由主题自带配色接管。 */
export function clearFamilyPalette(family: Family) {
  const current = readFamilyCustom(family)
  save(family, {params: current.params})
}

/** 整档重置该大类：自定义参数与品牌配色一并删除。 */
export function resetFamilyCustom(family: Family) {
  try { localStorage.removeItem(knobsKey(family)) } catch { /* 忽略：内联 token 由 applyTheme 清理。 */ }
}

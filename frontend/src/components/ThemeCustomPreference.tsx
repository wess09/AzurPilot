import { lazy, Suspense, useEffect, useState, type CSSProperties } from 'react'
import { useApp } from '../app/context'
import { applyCustomLayer, THEME_FAMILY } from '../app/theme'
import { MaterialDetailModal } from './MaterialDetailModal'
import { clearFamilyPalette, readFamilyCustom, writeFamilyCustom, type FamilyCustom } from '../app/themeCustom'
import { REGIONS, regionKnobs, regionLabels, type RegionId, type RegionKnob } from '../app/themeKnobs'
import { AppWindow, Frame, LayoutGrid, Layers, Menu as MenuIcon, RotateCcw, SlidersHorizontal, type LucideIcon } from 'lucide-react'
import { openMaterialInspector } from '../app/materialInspectorState'

const MockInstancePreview = lazy(() => import('./MockInstancePreview').then(module => ({default: module.MockInstancePreview})))

import { PaletteSwatches } from './PaletteSwatches'
import type { UiKey } from '../i18n'

type Ui = (key: UiKey, params?: Record<string, string | number>) => string

/** 每个区域一个图标，芯片上用它代替文字前缀，窄面板里更省宽度。 */
const REGION_ICONS: Record<RegionId, LucideIcon> = {surface: Layers, plate: LayoutGrid, inset: Frame, control: SlidersHorizontal, modal: AppWindow, menu: MenuIcon}

/** 滑块当前位置：用户动过就按存的值；否则尽量读主题自身的取值，读不出数值时用目录给的标称位置。 */
function knobPosition(knob: RegionKnob, stored: number | undefined) {
  if (stored !== undefined) return stored
  /* 主题取值要从计算样式里读；没有 DOM 时（静态渲染）退回标称位置。 */
  const raw = typeof document === 'undefined' ? '' : getComputedStyle(document.documentElement).getPropertyValue(knob.token).trim()
  if (!new RegExp(`^\\d+(\\.\\d+)?${knob.unit}$`).test(raw)) return knob.fallback
  /* 超出量程时给标称位置：夹到端点会谎称「当前就在最大值」。 */
  const value = Number.parseFloat(raw)
  return value < knob.min || value > knob.max ? knob.fallback : value
}

type PanelProps = {
  regions: readonly RegionId[]
  custom: FamilyCustom
  ui: Ui
  onKnob: (id: string, value: number) => void
  onResetKnob: (id: string) => void
  onResetRegion: (region: RegionId) => void
  onResetAll: () => void
  onRegionChange?: (region: RegionId) => void
}

/** 二级菜单的内容：先选作用的区域，下面只列这一区域的滑块，避免把全部滑块挤在一屏。
    区域用一排可换行的芯片表示，选中项实心，该区域有自定义值时另带一个小圆点。 */
export function MaterialDetailPanel({regions, custom, ui, onKnob, onResetKnob, onResetRegion, onResetAll, initialRegion, onRegionChange}: PanelProps & {initialRegion?: RegionId}) {
  const [region, setRegion] = useState<RegionId>(initialRegion ?? regions[0])
  const dirtyIn = (target: RegionId) => Object.keys(custom.params).some(id => id.startsWith(`${target}.`))
  const knobs = regionKnobs.filter(knob => knob.region === region)
  const selectRegion = (next: RegionId) => {
    setRegion(next)
    onRegionChange?.(next)
  }
  return <>
    <div className="material-detail-body">
      <div className="field-row material-scope-row">
        <div className="field-label"><label>{ui('settings.materialDetailScope')}</label></div>
        <div className="field-control">
          <div className="material-scope-chips" role="tablist" aria-label={ui('settings.materialDetailScope')}>
            {regions.map((item, index) => {
              const Icon = REGION_ICONS[item]
              const move = (delta: number) => selectRegion(regions[(index + delta + regions.length) % regions.length])
              return (
                <button
                  key={item}
                  type="button"
                  role="tab"
                  aria-selected={region === item}
                  tabIndex={region === item ? 0 : -1}
                  className={`scope-chip ${region === item ? 'active' : ''}`}
                  onClick={() => selectRegion(item)}
                  onKeyDown={event => {
                    if (event.key === 'ArrowRight') { event.preventDefault(); move(1) }
                    if (event.key === 'ArrowLeft') { event.preventDefault(); move(-1) }
                  }}
                >
                  <Icon size={13} className="scope-chip-icon" />
                  <span>{ui(regionLabels[item])}</span>
                  {dirtyIn(item) && <span className="scope-chip-dot" aria-hidden="true" />}
                </button>
              )
            })}
          </div>
        </div>
      </div>
      {knobs.map(knob => {
        const stored = custom.params[knob.id]
        const value = knobPosition(knob, stored)
        const label = `${ui(regionLabels[region])} ${ui(knob.labelKey)}`
        return <div className="field-row knob-row" key={knob.id}>
          <div className="field-label"><label htmlFor={`ui-knob-${knob.id}`}>{ui(knob.labelKey)}</label></div>
          <div className="field-control knob-control">
            <input
              id={`ui-knob-${knob.id}`}
              type="range"
              aria-label={label}
              min={knob.min}
              max={knob.max}
              step={knob.step}
              value={value}
              /* 已填充比例：滑块轨道的进度渐变按它绘制。 */
              style={{['--knob-fill']: `${Math.round(((value - knob.min) / (knob.max - knob.min)) * 100)}%`} as CSSProperties}
              /* 值没变就不落盘：写盘会把这一项标成「已调过」。 */
              onChange={event => { const next = Number(event.target.value); if (next !== value) onKnob(knob.id, next) }}
            />
            <span className="knob-value">{value}{knob.unit}</span>
            <button type="button" className="knob-reset" title={ui('settings.resetItem')} aria-label={`${ui('settings.resetItem')} · ${label}`} disabled={stored === undefined} onClick={() => onResetKnob(knob.id)}><RotateCcw size={14} aria-hidden="true"/></button>
          </div>
        </div>
      })}
    </div>
    <div className="material-detail-actions">
      <button type="button" className="text-button" disabled={!dirtyIn(region)} onClick={() => onResetRegion(region)}><RotateCcw size={14} aria-hidden="true"/>{ui('settings.customReset')}</button>
      <button type="button" className="text-button" onClick={onResetAll}><RotateCcw size={14} aria-hidden="true"/>{ui('settings.customResetAll')}</button>
    </div>
  </>
}

/** 有材质轴的家族专属的自定义外观：一级界面只放主题色与二级菜单入口，全部材质滑块都在二级菜单里。
    区域只是控件挂载位置的归类（不想调的人不用管），每一区都能独立调、也能单独还原。 */
export function ThemeCustomPreference() {
  const {ui, material, instances} = useApp()
  const family = THEME_FAMILY
  const [custom, setCustom] = useState<FamilyCustom>(() => readFamilyCustom(family))
  const [detail, setDetail] = useState(false)
  const [preview, setPreview] = useState(false)
  /* 切换大类后要换成那一套已存的值。 */
  useEffect(() => setCustom(readFamilyCustom(family)), [family])
  const regions = REGIONS
  if (!regions.length) return null
  const refresh = () => { applyCustomLayer(); setCustom(readFamilyCustom(family)) }
  const brand = custom.palette
  const touched = Object.keys(custom.params).length
  return <>
    <div className="field-row palette-field">
      <div className="field-label">
        <label>{ui('settings.brandColor')}</label>
        <p>{ui('settings.brandColorHelp')}</p>
      </div>
      <div className="field-control palette-control">
        {/* 第一项是「原版色」：选它等于清掉覆盖，回到该大类自带的强调色。 */}
        <PaletteSwatches stock value={brand} onChange={palette => { if (palette) writeFamilyCustom(family, {palette}); else clearFamilyPalette(family); refresh() }} legend={ui('settings.brandColor')}/>
      </div>
    </div>
    {/* 材质旋钮只对玻璃材质有意义：普通材质没有材质层，调了也看不见。 */}
    {material === 'glass' && <div className="field-row">
      <div className="field-label">
        <label>{ui('settings.materialDetail')}</label>
        <p>{ui('settings.materialDetailHelp')}</p>
      </div>
      <div className="field-control field-actions">
        <button type="button" className="button" onClick={() => setDetail(true)}>{ui('settings.materialDetailOpen')}{touched > 0 ? ` (${touched})` : ''}</button>
        <button type="button" className="button" onClick={() => { openMaterialInspector(); const first = instances[0]?.name; window.location.hash = first ? `/i/${first}/overview` : '/' }}>{ui('settings.materialLiveOnInstance')}</button>
      </div>
    </div>}
    {detail && <MaterialDetailModal onClose={() => setDetail(false)} onChange={refresh}/>}
    {preview && <Suspense fallback={null}><MockInstancePreview onClose={() => setPreview(false)}/></Suspense>}
  </>
}

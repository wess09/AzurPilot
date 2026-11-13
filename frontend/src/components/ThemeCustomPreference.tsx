/**
 * @fileoverview 材质细节面板：按区域收纳玻璃材质的滑块，供弹窗与悬浮检查器复用。
 */

import { useState } from 'react'
import { AppWindow, Frame, LayoutGrid, Layers, Menu as MenuIcon, RotateCcw, SlidersHorizontal, type LucideIcon } from 'lucide-react'
import { regionKnobs, regionLabels, type RegionId, type RegionKnob } from '../app/themeKnobs'
import type { FamilyCustom } from '../app/themeCustom'
import { Button } from './ui/button'
import { Slider } from './ui/slider'
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

/**
 * 二级菜单的内容：先选作用的区域，下面只列这一区域的滑块，避免把全部滑块挤在一屏。
 * 区域用一排可换行的芯片表示，选中项实心，该区域有自定义值时另带一个小圆点。
 */
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
            <Slider
              id={`ui-knob-${knob.id}`}
              aria-label={label}
              min={knob.min}
              max={knob.max}
              step={knob.step}
              value={[value]}
              /* 值没变就不落盘：写盘会把这一项标成「已调过」。 */
              onValueChange={([next]) => { if (next !== value) onKnob(knob.id, next) }}
            />
            <span className="knob-value">{value}{knob.unit}</span>
            <Button type="button" variant="ghost" size="icon-xs" title={ui('settings.resetItem')} aria-label={`${ui('settings.resetItem')} · ${label}`} disabled={stored === undefined} onClick={() => onResetKnob(knob.id)}><RotateCcw size={14} aria-hidden="true"/></Button>
          </div>
        </div>
      })}
    </div>
    <div className="material-detail-actions">
      <Button type="button" variant="ghost" size="xs" disabled={!dirtyIn(region)} onClick={() => onResetRegion(region)}><RotateCcw size={14} aria-hidden="true"/>{ui('settings.customReset')}</Button>
      <Button type="button" variant="ghost" size="xs" onClick={onResetAll}><RotateCcw size={14} aria-hidden="true"/>{ui('settings.customResetAll')}</Button>
    </div>
  </>
}

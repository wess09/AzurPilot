/**
 * @fileoverview 全量调色板面板：列出界面里的每一个颜色槽位，逐项改、逐项还原。
 *
 * 改动即时写到根节点的 CSS 变量上，所以弹窗后面的页面本身就在实时预览；
 * 明暗两套分别存档，顶部的明暗切换改的是真正的主题模式，看到的就是那一套。
 */
import { useEffect, useMemo, useState, useSyncExternalStore, type CSSProperties } from 'react'
import { Palette, RotateCcw, Search } from 'lucide-react'
import { useApp } from '../app/context'
import { applyCustomLayer, applyTheme, getThemePreference, subscribeTheme } from '../app/theme'
import {
  clearColorOverrides, colorGroups, colorGroupLabels, colorHex, colorSlots,
  countColorOverrides, currentColorValue, readColorOverrides, writeColorOverride,
  type ColorSlot,
} from '../app/colorPalette'
import type { ResolvedMode } from '../app/palettes'
import { SegmentedControl } from './SegmentedControl'
import { Modal } from './ui'

/** 十六进制输入：只有凑满合法六位才落盘，离开输入框时回到真实值，避免半截色值留在界面上。 */
function HexInput({value, label, onCommit}: {value: string; label: string; onCommit: (value: string) => void}) {
  const [draft, setDraft] = useState(value)
  const [editing, setEditing] = useState(false)
  const shown = editing ? draft : value
  return <input
    className="color-slot-hex"
    value={shown}
    maxLength={7}
    spellCheck={false}
    aria-label={`${label} hex`}
    onFocus={() => { setEditing(true); setDraft(value) }}
    onChange={event => {
      const next = event.target.value.trim()
      setDraft(next)
      if (colorHex.test(next)) onCommit(next)
    }}
    onBlur={() => { setEditing(false); setDraft(value) }}
  />
}

function SlotRow({slot, override, fallback, onPick, onReset}: {
  slot: ColorSlot
  override?: string
  fallback: string
  onPick: (value: string) => void
  onReset: () => void
}) {
  const {ui} = useApp()
  const value = override ?? fallback
  const name = ui(slot.label)
  return <div className={`color-slot${override ? ' dirty' : ''}`}>
    <label className="color-slot-chip" style={{'--slot-color': value} as CSSProperties} title={name}>
      <input type="color" value={colorHex.test(value) ? value : '#000000'} aria-label={name} onChange={event => onPick(event.target.value)}/>
    </label>
    <span className="color-slot-name">{name}</span>
    <code className="color-slot-token">{slot.token}</code>
    <HexInput value={value} label={name} onCommit={onPick}/>
    <button type="button" className="color-slot-reset" title={ui('settings.colorPaletteResetOne')} aria-label={`${ui('settings.colorPaletteResetOne')} · ${name}`} disabled={!override} onClick={onReset}>
      <RotateCcw size={13} aria-hidden="true"/>
    </button>
  </div>
}

function ColorPaletteModal({mode, onMode, onClose}: {mode: ResolvedMode; onMode: (mode: ResolvedMode) => void; onClose: () => void}) {
  const {ui} = useApp()
  const [query, setQuery] = useState('')
  /* 覆盖表是本地状态：写盘后立刻重算，不必等主题广播。 */
  const [overrides, setOverrides] = useState(() => readColorOverrides()[mode] ?? {})
  /* 切换明暗后另一套覆盖表要整体换掉，否则会把浅色的改动写在深色上。 */
  useEffect(() => setOverrides(readColorOverrides()[mode] ?? {}), [mode])
  /* 明暗切换后重取主题自带取值；改色不改变主题值，所以只在模式变化时重算。 */
  const fallback = useMemo(() => Object.fromEntries(colorSlots.map(slot => [slot.token, currentColorValue(slot.token) ?? '#000000'])), [mode])
  const needle = query.trim().toLowerCase()
  const matches = colorSlots.filter(slot => !needle || ui(slot.label).toLowerCase().includes(needle) || slot.token.includes(needle))
  const dirty = Object.keys(overrides).length

  const commit = (token: string, value: string | null) => {
    setOverrides(writeColorOverride(mode, token, value)[mode] ?? {})
    applyCustomLayer()
  }

  return <Modal title={ui('settings.colorPalette')} onClose={onClose} className="color-palette-modal">
    <div className="color-palette-toolbar">
      <SegmentedControl className="color-palette-mode" label={ui('settings.colorPaletteEditing')} value={mode} onChange={onMode} options={[
        {value: 'light', label: ui('settings.themeLight')},
        {value: 'dark', label: ui('settings.themeDark')},
      ]}/>
      <label className="color-palette-search">
        <Search size={14} aria-hidden="true"/>
        <input value={query} placeholder={ui('settings.colorPaletteSearch')} aria-label={ui('settings.colorPaletteSearch')} spellCheck={false} onChange={event => setQuery(event.target.value)}/>
      </label>
    </div>
    <div className="color-palette-sample" aria-hidden="true">
      <span className="status running">RUNNING</span>
      <span className="status updating">QUEUED</span>
      <span className="status error">FAILED</span>
      <button type="button" className="button primary" tabIndex={-1}>Primary</button>
      <span className="muted">Aa 12,480</span>
      <code className="lvl-error">ERROR</code>
      <code className="lvl-info">INFO</code>
    </div>
    <div className="color-palette-body">
      {colorGroups.map(group => {
        const slots = matches.filter(slot => slot.group === group)
        if (!slots.length) return null
        return <section className="color-slot-group" key={group}>
          <h3>{ui(colorGroupLabels[group])}<span>{slots.filter(slot => overrides[slot.token]).length || ''}</span></h3>
          {slots.map(slot => <SlotRow
            key={slot.token}
            slot={slot}
            override={overrides[slot.token]}
            fallback={fallback[slot.token]}
            onPick={value => commit(slot.token, value)}
            onReset={() => commit(slot.token, null)}
          />)}
        </section>
      })}
      {!matches.length && <p className="empty">{ui('settings.colorPaletteEmpty')}</p>}
    </div>
    <div className="color-palette-actions">
      <p>{dirty ? ui('settings.colorPaletteCount', {count: dirty}) : ui('settings.colorPaletteLive')}</p>
      <button type="button" className="button" disabled={!dirty} onClick={() => {
        setOverrides(clearColorOverrides(mode)[mode] ?? {})
        applyCustomLayer()
      }}><RotateCcw size={14} aria-hidden="true"/>{ui('settings.colorPaletteResetAll')}</button>
      <button type="button" className="button primary" onClick={onClose}>{ui('common.close')}</button>
    </div>
  </Modal>
}

/** 设置页上的入口：显示当前明暗下改过几项，点开就是全量调色板。 */
export function ColorPalettePreference() {
  const {ui} = useApp()
  const {resolvedMode} = useSyncExternalStore(subscribeTheme, getThemePreference, getThemePreference)
  const [open, setOpen] = useState(false)
  const [revision, setRevision] = useState(0)
  const dirty = useMemo(() => countColorOverrides(resolvedMode), [resolvedMode, revision, open])

  const switchMode = (next: ResolvedMode) => {
    const preference = getThemePreference()
    if (preference.theme === 'minimal') applyTheme({...preference, colorMode: next})
    else applyTheme({...preference, theme: next === 'dark' ? 'legacy-dark' : 'legacy-light'})
  }

  return <>
    <div className="field-row">
      <div className="field-label">
        <label>{ui('settings.colorPalette')}</label>
        <p>{ui('settings.colorPaletteHelp')}</p>
      </div>
      <div className="field-control field-actions">
        <button type="button" className="button" onClick={() => setOpen(true)}>
          <Palette size={15} aria-hidden="true"/>{ui('settings.colorPaletteOpen')}{dirty ? ` · ${ui('settings.colorPaletteCount', {count: dirty})}` : ''}
        </button>
      </div>
    </div>
    {open && <ColorPaletteModal mode={resolvedMode} onMode={switchMode} onClose={() => { setOpen(false); setRevision(value => value + 1) }}/>}
  </>
}

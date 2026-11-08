import { useState, type CSSProperties } from 'react'
import { Plus } from 'lucide-react'
import { useApp } from '../app/context'
import { isHexColor, paletteColors, palettes, stockBrands, type CustomPalette, type Palette } from '../app/palettes'
import { Modal } from './ui'

function CustomPaletteEditor({initial, onClose}: {initial: CustomPalette; onClose: () => void}) {
  const {ui, saveCustomPalette} = useApp()
  const [draft, setDraft] = useState(initial)
  const valid = isHexColor(draft.primary) && isHexColor(draft.secondary)
  return <Modal title={ui('settings.customPalette')} onClose={onClose} className="custom-palette-modal">
    <form className="form-stack" onSubmit={event => {
      event.preventDefault()
      if (!valid) return
      saveCustomPalette(draft)
      onClose()
    }}>
      <fieldset className="custom-palette-colors">
        <legend>{ui('settings.palette')}</legend>
        {(['primary', 'secondary'] as const).map(key => {
          const color = draft[key]
          const label = ui(key === 'primary' ? 'settings.primaryColor' : 'settings.secondaryColor')
          const update = (value: string) => setDraft({...draft, [key]: value})
          return <div className="custom-color-row" key={key}>
            <label htmlFor={`palette-${key}`}>{label}</label>
            <input type="color" value={isHexColor(color) ? color : '#000000'} aria-label={`${label} ${ui('settings.colorPicker')}`} onChange={event => update(event.target.value)}/>
            <input id={`palette-${key}`} aria-label={label} value={color} maxLength={7} pattern="#[0-9a-fA-F]{6}" required spellCheck={false} aria-invalid={!isHexColor(color)} aria-describedby={!isHexColor(color) ? 'palette-color-error' : undefined} onChange={event => update(event.target.value)}/>
          </div>
        })}
      </fieldset>
      {!valid && <p id="palette-color-error" role="status">{ui('settings.paletteInvalid')}</p>}
      <div className="custom-palette-actions">
        <button type="button" className="button secondary" onClick={onClose}>{ui('common.cancel')}</button>
        <button type="submit" className="button primary" disabled={!valid}>{ui('settings.savePalette')}</button>
      </div>
    </form>
  </Modal>
}

/** 配色选择器：简约主题选择整套配色，现代主题选择品牌配色。 */
export function PaletteSwatches({value, onChange, legend, stock = false}: {value?: Palette; onChange: (palette?: Palette) => void; legend: string; stock?: boolean}) {
  const {ui, resolvedMode, customPalettes, deleteCustomPalette} = useApp()
  const [editing, setEditing] = useState<CustomPalette>()
  const selected = customPalettes.find(item => item.id === value)
  const paletteIds = [...palettes, ...customPalettes.map(item => item.id)]
  function createPalette() {
    const id = `custom:${crypto.getRandomValues(new Uint32Array(2)).join('-')}` as const
    /* 新增方案从当前选中的配色起稿；没选（跟随主题）时取预置里的第一套。 */
    const current = paletteColors(value ?? palettes[0], customPalettes, resolvedMode)
    setEditing({id, primary: current.primary, secondary: current.secondary})
  }
  /* 第一项永远是「原版色」：显示该大类自带的强调色，选了就等于跟随主题（否则用户找不到原色）。 */
  const stockColors = stockBrands[resolvedMode]
  return <>
    <fieldset className="palette-options">
      <legend>{legend}</legend>
      {stock && <label className="palette-option">
        <input type="radio" name="palette" value="" checked={value === undefined} title={ui('settings.brandStock')} aria-label={ui('settings.brandStock')} onChange={() => onChange(undefined)}/>
        <span className="palette-swatch" style={{'--accent': stockColors.primary, '--secondary': stockColors.secondary} as CSSProperties} aria-hidden="true"><i/><i/></span>
      </label>}
      {paletteIds.map(id => {
        const colors = paletteColors(id, customPalettes, resolvedMode)
        return <label className="palette-option" key={id}>
          <input type="radio" name="palette" value={id} checked={value === id} onChange={() => onChange(id)}/>
          <span className="palette-swatch" style={{'--accent': colors.primary, '--secondary': colors.secondary} as CSSProperties} aria-hidden="true"><i/><i/></span>
        </label>
      })}
      <button
        type="button"
        className="palette-add"
        disabled={customPalettes.length >= 32}
        onClick={createPalette}
        aria-label={ui('settings.addPalette')}
        title={ui('settings.addPalette')}
      >
        <Plus size={18} aria-hidden="true"/>
      </button>
    </fieldset>
    {selected && <div className="custom-palette-actions">
      <button type="button" className="text-button" onClick={() => setEditing(selected)}>{ui('settings.editPalette')}</button>
      <button type="button" className="text-button" onClick={() => deleteCustomPalette(selected.id)}>{ui('settings.deletePalette')}</button>
    </div>}
    {editing && <CustomPaletteEditor initial={editing} onClose={() => setEditing(undefined)}/>}
  </>
}

import { useEffect, useState } from 'react'
import { useApp } from '../app/context'
import { applyCustomLayer, THEME_FAMILY } from '../app/theme'
import { clearFamilyKnob, clearFamilyRegion, readFamilyCustom, resetFamilyCustom, writeFamilyCustom, type FamilyCustom } from '../app/themeCustom'
import { REGIONS } from '../app/themeKnobs'
import { MaterialDetailPanel } from './ThemeCustomPreference'
import { Modal } from './ui'

/** 材质细节二级菜单：设置页与运行总览共用同一个弹窗，谁需要就在谁那里挂一个入口。
    onChange 用于让调用方同步自己那份状态（设置页要更新入口上的已调项数）。 */
export function MaterialDetailModal({onClose, onChange}: {onClose: () => void; onChange?: () => void}) {
  const {ui} = useApp()
  const family = THEME_FAMILY
  const [custom, setCustom] = useState<FamilyCustom>(() => readFamilyCustom(family))
  useEffect(() => setCustom(readFamilyCustom(family)), [family])
  const refresh = () => { applyCustomLayer(); setCustom(readFamilyCustom(family)); onChange?.() }
  return <Modal title={ui('settings.materialDetail')} onClose={onClose} className="material-detail-modal">
    <MaterialDetailPanel
      regions={REGIONS}
      custom={custom}
      ui={ui}
      onKnob={(id, value) => { writeFamilyCustom(family, {params: {[id]: value}}); refresh() }}
      onResetKnob={id => { clearFamilyKnob(family, id); refresh() }}
      onResetRegion={region => { clearFamilyRegion(family, region); refresh() }}
      onResetAll={() => { resetFamilyCustom(family); refresh() }}
    />
  </Modal>
}


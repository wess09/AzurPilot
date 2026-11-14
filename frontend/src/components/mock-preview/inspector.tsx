/**
 * @fileoverview 悬浮/停靠材质调节面板：最小化与关闭控制、区域选择与参数调节表单。
 * 从 MockInstancePreview.tsx 原 468-552 行提取，纯搬迁未改动（仅新增导出与入参）。
 */
import type { Dispatch, SetStateAction } from 'react'
import { Minimize2, PanelRightClose, PanelRightOpen, Sliders, X } from 'lucide-react'

import type { Family } from '../../app/theme'
import { clearFamilyKnob, clearFamilyRegion, resetFamilyCustom, writeFamilyCustom } from '../../app/themeCustom'
import type { FamilyCustom } from '../../app/themeCustom'
import { REGIONS, type RegionId } from '../../app/themeKnobs'
import { MaterialDetailPanel } from '../ThemeCustomPreference'
import type { UiTranslator } from '../../i18n'

type MockInspectorParams = {
  /** 翻译函数。 */
  ui: UiTranslator
  /** 关闭预览层。 */
  onClose: () => void
  /** 面板是否停靠在右侧边缘。 */
  isDocked: boolean
  /** 切换停靠状态。 */
  setIsDocked: Dispatch<SetStateAction<boolean>>
  /** 面板是否最小化为悬浮球。 */
  isInspectorMinimized: boolean
  /** 切换最小化状态。 */
  setIsInspectorMinimized: Dispatch<SetStateAction<boolean>>
  /** 当前材质族的自定义参数。 */
  custom: FamilyCustom
  /** 材质参数变更后刷新预览层样式。 */
  refresh: () => void
  /** 当前材质族。 */
  family: Family
  /** 当前选中的调节区域。 */
  activeRegion: RegionId
  /** 切换调节区域。 */
  handleRegionSelect: (next: RegionId) => void
}

/** 渲染悬浮/停靠材质调节面板样本。 */
export function mockInspector({ui, onClose, isDocked, setIsDocked, isInspectorMinimized, setIsInspectorMinimized, custom, refresh, family, activeRegion, handleRegionSelect}: MockInspectorParams) {
  return (
      <div
        className={`mock-preview-inspector ${isDocked ? 'is-docked' : 'is-floating'} ${isInspectorMinimized ? 'is-minimized' : ''}`}
      >
        {isInspectorMinimized ? (
          <button
            type="button"
            className="inspector-expand-button"
            onClick={() => setIsInspectorMinimized(false)}
            title={ui('settings.inspectorTitle')}
          >
            <Sliders size={18} />
            <span>{ui('settings.inspectorTitle')}</span>
          </button>
        ) : (
          <div className="inspector-panel-inner">
            {/* 检视器顶栏 */}
            <div className="inspector-header">
              <div className="inspector-title">
                <Sliders size={16} style={{color: 'var(--accent)'}} />
                <strong>{ui('settings.inspectorTitle')}</strong>
                <span className="theme-tag">Google M3</span>
              </div>

              <div className="inspector-controls">
                <button
                  type="button"
                  className="icon-button"
                  onClick={() => setIsDocked(d => !d)}
                  title={isDocked ? '切换为浮动窗口' : '切换为右侧停靠'}
                >
                  {isDocked ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
                </button>
                <button
                  type="button"
                  className="icon-button"
                  onClick={() => setIsInspectorMinimized(true)}
                  title={ui('settings.inspectorMinimize')}
                >
                  <Minimize2 size={15} />
                </button>
                <button
                  type="button"
                  className="icon-button"
                  onClick={onClose}
                  title={ui('settings.closePreview')}
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            <div className="inspector-body">
              <MaterialDetailPanel
                regions={REGIONS}
                custom={custom}
                ui={ui}
                initialRegion={activeRegion}
                onRegionChange={handleRegionSelect}
                onKnob={(id, value) => {
                  writeFamilyCustom(family, {params: {[id]: value}})
                  refresh()
                }}
                onResetKnob={id => {
                  clearFamilyKnob(family, id)
                  refresh()
                }}
                onResetRegion={r => {
                  clearFamilyRegion(family, r)
                  refresh()
                }}
                onResetAll={() => {
                  resetFamilyCustom(family)
                  refresh()
                }}
              />
            </div>

            <div className="inspector-footer">
              <button type="button" className="button primary full-width" onClick={onClose}>
                {ui('settings.closePreview')}
              </button>
            </div>
          </div>
        )}
      </div>
  )
}

/**
 * 从 MockInstancePreview.tsx 原 429-464 行提取，纯搬迁未改动（仅新增导出与入参）。
 * 全真预览模拟弹窗样本：遮罩、标题、说明与确认按钮，供 modal 材质区域调节。
 */
import type { Dispatch, SetStateAction } from 'react'
import { X } from 'lucide-react'
import type { UiTranslator } from '../../i18n'

type MockSampleModalParams = {
  ui: UiTranslator
  setShowModal: Dispatch<SetStateAction<boolean>>
}

export function mockSampleModal({ui, setShowModal}: MockSampleModalParams) {
  return (
        <div
          className="mock-modal-scrim"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 110,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(0, 0, 0, 0.45)',
          }}
          onClick={e => { if (e.target === e.currentTarget) setShowModal(false) }}
        >
          <div className="modal" style={{width: '90%', maxWidth: '440px', display: 'flex', flexDirection: 'column', gap: '16px'}}>
            <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
              <h3 style={{margin: 0, fontSize: '18px', fontWeight: 650}}>{ui('settings.sampleModalTitle')}</h3>
              <button type="button" className="icon-button" onClick={() => setShowModal(false)} aria-label="Close">
                <X size={18} />
              </button>
            </div>
            <p style={{margin: 0, fontSize: '13.5px', color: 'var(--text)', opacity: 0.9, lineHeight: 1.6}}>
              {ui('settings.sampleModalBody')}
            </p>
            <div style={{padding: '12px 14px', borderRadius: 'var(--theme-control-radius, 10px)', background: 'var(--surface-muted, #f8fafc)', fontSize: '12.5px', color: 'var(--muted)'}}>
              提示：可在右侧面板中切换至「弹窗 (modal)」并调节不透明度、模糊或阴影，本弹窗将实时联动渲染。
            </div>
            <div style={{display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '4px'}}>
              <button type="button" className="button secondary" onClick={() => setShowModal(false)}>
                取消
              </button>
              <button type="button" className="button primary" onClick={() => setShowModal(false)}>
                确认
              </button>
            </div>
          </div>
        </div>
  )
}

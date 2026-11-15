/**
 * @fileoverview 全真预览顶栏样本：面包屑状态、菜单与弹窗触发点、启停控制与模拟菜单。
 * 从 MockInstancePreview.tsx 原 193-273 行提取，纯搬迁未改动（仅新增导出与入参）。
 */
import type { Dispatch, SetStateAction } from 'react'
import { FileText, MoreVertical, Pause, Play, RotateCcw, Settings, Sparkles } from 'lucide-react'
import type { UiTranslator } from '../../i18n'

type MockTopbarParams = {
  /** 翻译函数。 */
  ui: UiTranslator
  /** 模拟任务是否运行中。 */
  isRunning: boolean
  /** 切换运行状态。 */
  setIsRunning: Dispatch<SetStateAction<boolean>>
  /** 模拟菜单是否展开。 */
  showMenu: boolean
  /** 切换模拟菜单。 */
  setShowMenu: Dispatch<SetStateAction<boolean>>
  /** 打开模拟弹窗。 */
  setShowModal: Dispatch<SetStateAction<boolean>>
}

/** 渲染预览顶栏样本。 */
export function mockTopbar({ui, isRunning, setIsRunning, showMenu, setShowMenu, setShowModal}: MockTopbarParams) {
  return (
          <header className="topbar mock-preview-topbar" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
            <div className="breadcrumb" style={{display: 'flex', alignItems: 'center', gap: '10px'}}>
              <span style={{color: 'var(--muted)'}}>{ui('instance.all')}</span>
              <span style={{color: 'var(--border)'}}>/</span>
              <strong style={{fontWeight: 650, color: 'var(--text)'}}>alas (模拟实例)</strong>
              <span style={{display: 'inline-flex', alignItems: 'center', gap: '5px', padding: '2px 8px', borderRadius: '999px', fontSize: '11px', background: isRunning ? 'var(--green-soft, #e8f5e9)' : 'var(--surface-muted)', color: isRunning ? 'var(--green, #2e7d32)' : 'var(--muted)', fontWeight: 600}}>
                <span style={{width: '6px', height: '6px', borderRadius: '50%', background: isRunning ? 'var(--green, #2e7d32)' : 'var(--muted)'}} />
                {isRunning ? '运行中' : '已停止'}
              </span>
              <span className="connection-label" style={{fontSize: '11.5px', color: 'var(--muted)', marginLeft: '6px'}}>
                127.0.0.1:5555
              </span>
            </div>

            {/* 顶栏操作按钮与交互触发点 */}
            <div style={{display: 'flex', alignItems: 'center', gap: '8px', position: 'relative'}}>
              {/* 测试下拉菜单触发点 (menu 区域) */}
              <button
                type="button"
                className="button secondary"
                onClick={() => setShowMenu(prev => !prev)}
                title={ui('settings.sampleMenu')}
                style={{height: '34px', padding: '0 12px', fontSize: '12px'}}
              >
                <MoreVertical size={14} />
                <span>{ui('settings.sampleMenu')}</span>
              </button>

              {/* 模拟下拉菜单 (menu 区域) */}
              {showMenu && (
                <div
                  className="instance-menu"
                  style={{
                    position: 'absolute',
                    top: 'calc(100% + 8px)',
                    right: '180px',
                    zIndex: 99,
                    minWidth: '180px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '4px',
                  }}
                >
                  <button type="button" onClick={() => setShowMenu(false)}>
                    <Settings size={14} />
                    <span>实例详细配置</span>
                  </button>
                  <button type="button" onClick={() => setShowMenu(false)}>
                    <FileText size={14} />
                    <span>导出运行日志</span>
                  </button>
                  <button type="button" onClick={() => setShowMenu(false)}>
                    <RotateCcw size={14} />
                    <span>清除本地缓存</span>
                  </button>
                </div>
              )}

              {/* 测试弹窗触发点 (modal 区域) */}
              <button
                type="button"
                className="button secondary"
                onClick={() => setShowModal(true)}
                title={ui('settings.sampleModal')}
                style={{height: '34px', padding: '0 12px', fontSize: '12px'}}
              >
                <Sparkles size={14} />
                <span>{ui('settings.sampleModal')}</span>
              </button>

              {/* 模拟启停控制 (control 区域) */}
              <button
                type="button"
                className={`button ${isRunning ? 'danger' : 'primary'}`}
                onClick={() => setIsRunning(r => !r)}
                style={{height: '34px', padding: '0 14px', fontSize: '12.5px'}}
              >
                {isRunning ? <><Pause size={14} /><span>单次停止</span></> : <><Play size={14} /><span>立即运行</span></>}
              </button>
            </div>
          </header>
  )
}

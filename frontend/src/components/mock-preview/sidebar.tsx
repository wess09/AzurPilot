/**
 * 从 MockInstancePreview.tsx 原 121-188 行提取，纯搬迁未改动（仅新增导出与入参）。
 * 全真预览侧栏样本：品牌、主导航与任务目录，用于 sidebar 材质区域调节。
 */
import { Activity, ChevronDown, FileText, Home, LayoutDashboard, Sliders, Sword, TrendingUp } from 'lucide-react'

import { ProjectLogo } from '../ProjectLogo'
import type { UiTranslator } from '../../i18n'

export function mockSidebar(ui: UiTranslator) {
  return (
        <aside className="sidebar mock-preview-sidebar">
          <div className="sidebar-brand">
            <div className="sidebar-brand-left">
              <ProjectLogo className="brand-logo"/>
              <span className="brand-title" style={{fontSize: '15px', fontWeight: 650, letterSpacing: '-0.2px'}}>
                AzurPilot <small style={{fontSize: '11px', opacity: 0.75, fontWeight: 'normal'}}>Preview</small>
              </span>
            </div>
          </div>

          <nav className="primary-nav" aria-label="Mock Nav">
            <a href="#overview" className="active" onClick={e => e.preventDefault()}>
              <LayoutDashboard size={17} />
              {ui('nav.overview')}
            </a>
            <a href="#statistics" onClick={e => e.preventDefault()}>
              <TrendingUp size={17} />
              {ui('nav.statistics')}
            </a>
            <a href="#configs" onClick={e => e.preventDefault()}>
              <FileText size={17} />
              {ui('nav.configs')}
            </a>
            <a href="#interface" onClick={e => e.preventDefault()}>
              <Sliders size={17} />
              {ui('nav.interface')}
            </a>
          </nav>

          <div style={{marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '8px'}}>
            <div className="sidebar-label" style={{fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--muted)', padding: '0 8px'}}>
              任务目录 (Tasks)
            </div>
            <div className="task-group-button expanded" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', borderRadius: '10px'}}>
              <span style={{display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: 550}}>
                <Sword size={15} style={{color: 'var(--accent)'}} />
                主线出击 (Combat)
              </span>
              <ChevronDown size={14} style={{color: 'var(--muted)'}} />
            </div>
            <div style={{paddingLeft: '14px', display: 'flex', flexDirection: 'column', gap: '4px'}}>
              <div className="task-submenu-item active" style={{display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 10px', fontSize: '12.5px'}}>
                <span className="task-submenu-dot" style={{width: '6px', height: '6px', borderRadius: '50%', background: 'var(--accent)'}} />
                12-4 鸟海捞船
              </div>
              <div className="task-submenu-item" style={{display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 10px', fontSize: '12.5px', color: 'var(--muted)'}}>
                <span className="task-submenu-dot" style={{width: '6px', height: '6px', borderRadius: '50%', background: 'transparent' }} />
                13-4 杜威捞船
              </div>
            </div>

            <div className="task-group-button" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', borderRadius: '10px'}}>
              <span style={{display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: 550}}>
                <Activity size={15} style={{color: 'var(--accent)'}} />
                日常委托 (Commission)
              </span>
              <ChevronDown size={14} style={{transform: 'rotate(-90deg)', color: 'var(--muted)'}} />
            </div>
            <div className="task-group-button" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', borderRadius: '10px'}}>
              <span style={{display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: 550}}>
                <Home size={15} style={{color: 'var(--accent)'}} />
                后宅管理 (Dorm)
              </span>
              <ChevronDown size={14} style={{transform: 'rotate(-90deg)', color: 'var(--muted)'}} />
            </div>
          </div>
        </aside>
  )
}

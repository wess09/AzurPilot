/**
 * @fileoverview 全真模拟实例预览组件 (MockInstancePreview)。
 * 允许用户在真实的实例全景环境（包含顶栏、侧栏、资源卡、运行卡片、日志、右栏调度器以及菜单与弹窗）中，
 * 逐区域实时调整材质并获得即时视觉反馈。
 */

import { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import {
  Activity,
  Award,
  Calendar,
  ChevronDown,
  CheckCircle2,
  Clock,
  FileText,
  Fuel,
  Gem,
  Home,
  LayoutDashboard,
  Minimize2,
  MoreVertical,
  PanelRightClose,
  PanelRightOpen,
  Pause,
  Play,
  RotateCcw,
  Settings,
  Shield,
  Sliders,
  Sparkles,
  Sword,
  TrendingUp,
  X,
} from 'lucide-react'

import { useApp } from '../app/context'
import { ProjectLogo } from './ProjectLogo'
import { THEME_FAMILY } from '../app/theme'
import {
  clearFamilyKnob,
  clearFamilyRegion,
  resetFamilyCustom,
  writeFamilyCustom,
} from '../app/themeCustom'
import { REGIONS, type RegionId } from '../app/themeKnobs'
import { useFamilyCustom, useSampleLayers } from '../app/useMaterialInspector'
import { MaterialDetailPanel } from './ThemeCustomPreference'
import { ThemeWallpaper } from './ThemeWallpaper'

type MockInstancePreviewProps = {
  onClose: () => void
  initialRegion?: RegionId
}

/**
 * 材质检视器的全真预览：把一份写死的实例外壳渲染成全屏覆盖层，
 * 供用户在顶栏、侧栏、资源卡、日志等区域上调材质并即时看到效果。
 * 有 document 时经 Portal 挂到 body；焦点圈定在预览层内。
 */
export function MockInstancePreview({onClose, initialRegion}: MockInstancePreviewProps) {
  const overlayRef = useRef<HTMLDivElement>(null)
  // Tab 循环不出覆盖层、焦点逃逸即拉回；卸载时把焦点还给打开预览前的元素。
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const root = overlayRef.current
    if (!root) return
    const focusable = () => [...root.querySelectorAll<HTMLElement>('a[href], button, input, select, textarea, [tabindex]')]
      .filter(element => element.tabIndex >= 0 && !element.matches(':disabled') && element.getClientRects().length > 0)
    const focusFirst = () => (focusable()[0] ?? root).focus()
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const items = focusable()
      const current = items.indexOf(document.activeElement as HTMLElement)
      if (!items.length || current < 0 || (event.shiftKey ? current === 0 : current === items.length - 1)) {
        event.preventDefault()
        ;(event.shiftKey ? items.at(-1) ?? root : items[0] ?? root).focus()
      }
    }
    const containFocus = (event: FocusEvent) => {
      if (!root.contains(event.target as Node)) focusFirst()
    }
    focusFirst()
    document.addEventListener('keydown', trapFocus, true)
    document.addEventListener('focusin', containFocus)
    return () => {
      document.removeEventListener('keydown', trapFocus, true)
      document.removeEventListener('focusin', containFocus)
      if (previous?.isConnected) previous.focus()
    }
  }, [])
  const {ui} = useApp()
  const family = THEME_FAMILY
  const {custom, refresh} = useFamilyCustom(family)
  const {region: activeRegion, showModal, showMenu, select: handleRegionSelect, setShowModal, setShowMenu} = useSampleLayers(initialRegion ?? 'surface')

  const [isRunning, setIsRunning] = useState(true)

  const [isInspectorMinimized, setIsInspectorMinimized] = useState(false)
  const [isDocked, setIsDocked] = useState(true)
  const isDockedActive = isDocked && !isInspectorMinimized
  const overlay = (
    <div ref={overlayRef} role="dialog" aria-modal="true" aria-label={ui('settings.materialLivePreview')} tabIndex={-1} className={`mock-instance-preview-overlay legacy-shell-preview ${isDockedActive ? 'has-docked-inspector' : ''}`}>
      <ThemeWallpaper />
      {/* 全真模拟 AppShell 容器；里面的实例名、资源、任务与日志是写死的样本数据，用来撑起外壳，不随语言切换。 */}
      <div className={`app-shell modern-shell with-rail legacy-shell mock-preview-shell`}>
        {/* 侧栏 (sidebar 区域) */}
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

        {/* 主视图区域 */}
        <div className="main-shell">
          {/* 顶栏 (topbar 区域) */}
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

          {/* 内容区 */}
          <main style={{flex: 1, padding: '24px 28px', overflowY: 'auto'}}>
            <div className="overview-page" style={{display: 'flex', flexDirection: 'column', gap: '20px'}}>
              {/* 页面标题 */}
              <div className="page-title" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px'}}>
                <div style={{display: 'flex', alignItems: 'baseline', gap: '12px'}}>
                  <h1 style={{fontSize: '24px', fontWeight: 700, margin: 0}}>alas</h1>
                  <span style={{fontSize: '13px', color: 'var(--muted)'}}>碧蓝航线自动化实例 #1</span>
                </div>
                <div style={{display: 'flex', gap: '8px'}}>
                  <button type="button" className="button secondary" style={{height: '32px', padding: '0 12px', fontSize: '12px'}}>
                    <RotateCcw size={13} />
                    刷新
                  </button>
                  <button type="button" className="button secondary" style={{height: '32px', padding: '0 12px', fontSize: '12px'}}>
                    <Settings size={13} />
                    调度设置
                  </button>
                </div>
              </div>

              {/* 资源卡网格 (plate 托板区域) */}
              <div className="resource-grid" style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px'}}>
                <div className="resource-card" style={{padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '4px'}}>
                  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--muted)', fontSize: '12px'}}>
                    <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><Fuel size={14} style={{color: '#0284c7'}} />石油 (Oil)</span>
                    <span style={{fontSize: '11px', color: '#16a34a'}}>+450/h</span>
                  </div>
                  <strong style={{fontSize: '18px', fontWeight: 650, fontVariantNumeric: 'tabular-nums'}}>24,150</strong>
                  <span style={{fontSize: '11px', color: 'var(--muted)'}}>上限 25,000</span>
                </div>

                <div className="resource-card" style={{padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '4px'}}>
                  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--muted)', fontSize: '12px'}}>
                    <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><Award size={14} style={{color: '#eab308'}} />物资 (Gold)</span>
                    <span style={{fontSize: '11px', color: '#16a34a'}}>+3.8k/h</span>
                  </div>
                  <strong style={{fontSize: '18px', fontWeight: 650, fontVariantNumeric: 'tabular-nums'}}>289,400</strong>
                  <span style={{fontSize: '11px', color: 'var(--muted)'}}>上限 600,000</span>
                </div>

                <div className="resource-card" style={{padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '4px'}}>
                  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--muted)', fontSize: '12px'}}>
                    <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><Gem size={14} style={{color: '#f43f5e'}} />钻石 (Gem)</span>
                  </div>
                  <strong style={{fontSize: '18px', fontWeight: 650, fontVariantNumeric: 'tabular-nums'}}>3,420</strong>
                  <span style={{fontSize: '11px', color: 'var(--muted)'}}>储备充足</span>
                </div>

                <div className="resource-card" style={{padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '4px'}}>
                  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--muted)', fontSize: '12px'}}>
                    <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><Shield size={14} style={{color: '#8b5cf6'}} />心智魔方 (Cube)</span>
                  </div>
                  <strong style={{fontSize: '18px', fontWeight: 650, fontVariantNumeric: 'tabular-nums'}}>1,280</strong>
                  <span style={{fontSize: '11px', color: 'var(--muted)'}}>快速建造券 856</span>
                </div>
              </div>

              {/* 正在运行的任务状态卡片 (surface 底板区域) */}
              <div className="panel" style={{padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: '14px'}}>
                <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
                  <div style={{display: 'flex', alignItems: 'center', gap: '12px'}}>
                    <div style={{padding: '8px', borderRadius: '10px', background: 'var(--accent-soft, #ede9fe)', color: 'var(--accent)'}}>
                      <Sword size={20} />
                    </div>
                    <div>
                      <h3 style={{margin: 0, fontSize: '16px', fontWeight: 650}}>12-4 鸟海捞船 · 正在出击</h3>
                      <p style={{margin: '2px 0 0', fontSize: '12.5px', color: 'var(--muted)'}}>
                        第 4 战 / 共 6 战 (道中主力队战斗完毕，正在寻敌大型主力舰队)
                      </p>
                    </div>
                  </div>
                  <span style={{padding: '4px 10px', borderRadius: '8px', fontSize: '12px', background: 'var(--accent-soft)', color: 'var(--accent)', fontWeight: 600}}>
                    进行中 65%
                  </span>
                </div>

                {/* 进度条与指标 */}
                <div style={{width: '100%', height: '7px', borderRadius: '999px', background: 'var(--surface-muted, #f1f5f9)', overflow: 'hidden'}}>
                  <div style={{width: '65%', height: '100%', borderRadius: '999px', background: 'var(--accent, #6366f1)', transition: 'width 0.3s ease'}} />
                </div>

                <div style={{display: 'flex', flexWrap: 'wrap', gap: '24px', fontSize: '12.5px', color: 'var(--muted)', paddingTop: '4px'}}>
                  <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><Clock size={14} />运行耗时: 00:14:28</span>
                  <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><Calendar size={14} />预计剩余: 00:04:12</span>
                  <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><CheckCircle2 size={14} style={{color: '#16a34a'}} />战果: S胜×3 (鸟海搜寻中)</span>
                </div>
              </div>

              {/* 实时日志面板 (plate 托板 + control 控件区域) */}
              <div className="panel monitor-panel" style={{display: 'flex', flexDirection: 'column'}}>
                <div className="panel-heading" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px'}}>
                  <div style={{display: 'flex', alignItems: 'center', gap: '10px'}}>
                    <span style={{fontWeight: 650, fontSize: '14px'}}>实时运行日志</span>
                    <span style={{fontSize: '11px', color: 'var(--muted)'}}>实时流已就绪</span>
                  </div>
                  <div style={{display: 'flex', alignItems: 'center', gap: '6px'}}>
                    <button type="button" className="button secondary" style={{height: '28px', padding: '0 8px', fontSize: '11px'}}>全部</button>
                    <button type="button" className="button secondary" style={{height: '28px', padding: '0 8px', fontSize: '11px', color: '#0ea5e9'}}>INFO</button>
                    <button type="button" className="button secondary" style={{height: '28px', padding: '0 8px', fontSize: '11px', color: '#eab308'}}>WARN</button>
                  </div>
                </div>

                <div className="log-content" style={{height: '180px', minHeight: '160px', padding: '12px 18px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '4px'}}>
                  <div><span style={{color: 'var(--muted)'}}>[14:11:42]</span> <span style={{color: '#0ea5e9'}}>[INFO]</span> [Campaign] Enter campaign: 12-4 鸟海捞船模式</div>
                  <div><span style={{color: 'var(--muted)'}}>[14:11:45]</span> <span style={{color: '#0ea5e9'}}>[INFO]</span> [Combat] Fleet 1 moving to ambush grid (D, 3)</div>
                  <div><span style={{color: 'var(--muted)'}}>[14:11:50]</span> <span style={{color: '#0ea5e9'}}>[INFO]</span> [Combat] Auto combat round started. S-Rank achieved.</div>
                  <div><span style={{color: 'var(--muted)'}}>[14:12:12]</span> <span style={{color: '#22c55e'}}>[SUCCESS]</span> [Drop] Got Choukai (SSR) drop confirmed!</div>
                  <div><span style={{color: 'var(--muted)'}}>[14:12:15]</span> <span style={{color: '#0ea5e9'}}>[INFO]</span> [Emotion] Fleet 1 average emotion: 138 (Exp +20%)</div>
                  <div><span style={{color: 'var(--muted)'}}>[14:12:20]</span> <span style={{color: 'var(--accent)'}}>[Scheduler]</span> Next scheduled queue: 委托收获 in 00:07:40</div>
                </div>
              </div>
            </div>
          </main>
        </div>

        {/* 右栏 (right-rail 调度与任务队列区域) */}
        <aside className="right-rail mock-preview-rail" style={{display: 'flex', flexDirection: 'column'}}>
          <div className="right-rail-header" style={{padding: '16px 18px', borderBottom: '1px solid var(--border)'}}>
            <h4 style={{margin: 0, fontSize: '14px', fontWeight: 650, display: 'flex', alignItems: 'center', gap: '8px'}}>
              <Clock size={16} style={{color: 'var(--accent)'}} />
              调度计划 (Scheduler)
            </h4>
          </div>

          <div style={{padding: '14px', display: 'flex', flexDirection: 'column', gap: '10px'}}>
            <div className="scheduler-widget" style={{padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '6px'}}>
              <span style={{fontSize: '11.5px', color: 'var(--muted)'}}>下个调度任务</span>
              <strong style={{fontSize: '15px', color: 'var(--accent)', fontWeight: 650}}>14:20 委托收获</strong>
              <span style={{fontSize: '11.5px', color: 'var(--muted)'}}>预计倒计时: 00:07:38</span>
            </div>

            <div style={{fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--muted)', marginTop: '8px', padding: '0 4px'}}>
              队列序列 (Queue)
            </div>

            <div className="rail-task-item" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
              <span style={{fontSize: '13px', fontWeight: 500}}>14:35 演习出击</span>
              <small style={{color: 'var(--muted)'}}>00:22:38</small>
            </div>
            <div className="rail-task-item" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
              <span style={{fontSize: '13px', fontWeight: 500}}>15:00 战术研修</span>
              <small style={{color: 'var(--muted)'}}>00:47:38</small>
            </div>
            <div className="rail-task-item" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
              <span style={{fontSize: '13px', fontWeight: 500}}>16:00 后宅喂食</span>
              <small style={{color: 'var(--muted)'}}>01:47:38</small>
            </div>
          </div>
        </aside>
      </div>

      {/* 模拟弹窗 (modal 区域) */}
      {showModal && (
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
      )}

      {/* 悬浮/停靠材质调节面板 (Inspector) */}
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
    </div>
  )

  if (typeof document !== 'undefined' && document.body) {
    return createPortal(overlay, document.body)
  }
  // 没有 document 的环境（如 renderToStaticMarkup 测试）挂不了 Portal，直接返回节点本身。
  return overlay
}

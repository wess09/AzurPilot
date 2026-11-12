/**
 * @fileoverview 开发者调试工具箱页面，提供动效、状态模拟与控件预览。
 */

import { useState, useSyncExternalStore, type ReactNode } from 'react'
import { MarqueeText } from '../components/MarqueeText'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Bell, ChevronRight, CircleAlert, CirclePlay, Code2, Database, Gauge, Image, Layers3, RefreshCw, Search, Server, Settings2, Terminal, Trash2, Wrench, X } from 'lucide-react'
import type { Value } from '../api/types'
import { useApp } from '../app/context'
import { previewUpdate, simulateStatus, useDevOverride } from '../app/devOverride'
import { readMotionPrefs, resetMotionPrefs, setMotionReduced, setMotionSpeed, setMotionStrength, subscribeMotionPrefs } from '../app/motionPrefs'
import { replayLastPageTransition } from '../app/pageMotion'
import { FieldInput } from '../components/FieldInput'
import { SegmentedControl } from '../components/SegmentedControl'
import { Empty, ErrorBox, Loading, Modal, PageTitle, StatusBadge } from '../components/ui'

// 模拟状态用的文案键；与实际状态值一一对应。
const STATUS_LABELS = {running: 'status.running', stopped: 'status.stopped', error: 'status.error', updating: 'status.updating'} as const

// 故意抛异常，用来验证顶层 ErrorBoundary 的错误页。
function CrashTest(): never {
  throw new Error('DevControls crash test')
}

function DevField({id, label, help, multiline = false, children}: {id: string; label: string; help?: string; multiline?: boolean; children: ReactNode}) {
  return <div className={`field-row ${multiline ? 'field-row-multiline' : ''}`}>
    <div className="field-label"><label htmlFor={id}>{label}</label>{help && <p>{help}</p>}</div>
    <div className="field-control">{children}</div>
  </div>
}

/** 开发者调试页：动效实验室、状态/更新提示模拟、崩溃测试，以及设计令牌与全部控件的现场预览。 */
export function DevControls() {
  const {setDevMode, notify, ui} = useApp()
  const navigate = useNavigate()
  const [text, setText] = useState('AzurPilot')
  const [number, setNumber] = useState(25548)
  const [password, setPassword] = useState('developer')
  const [select, setSelect] = useState<Value>('Auto')
  const [dateTime, setDateTime] = useState<Value>('2026-09-15 09:00:00')
  const [month, setMonth] = useState('2026-09')
  const [toggle, setToggle] = useState<Value>(true)
  const [multi, setMulti] = useState<Value>(['Alas', 'Opsi'])
  const [textarea, setTextarea] = useState<Value>(() => ui('developer.textareaSample'))
  const [yaml, setYaml] = useState<Value>('Scheduler:\n  Enable: true\n  SuccessInterval: 30')
  const [segment, setSegment] = useState<'logs' | 'preview'>('logs')
  const [modalOpen, setModalOpen] = useState(false)
  const [demoTab, setDemoTab] = useState('resources')
  const [throwing, setThrowing] = useState(false)
  const override = useDevOverride()
  const motionPrefs = useSyncExternalStore(subscribeMotionPrefs, readMotionPrefs, readMotionPrefs)
  const statusLabel = override.status ? ui(STATUS_LABELS[override.status]) : ''

  function disableDevMode() {
    setDevMode(false)
    notify(ui('developer.disabled'))
    navigate('/', {replace: true})
  }

  return <>
    <PageTitle title={ui('developer.pageTitle')} actions={<button className="button secondary" onClick={disableDevMode}><X size={15}/>{ui('developer.exit')}</button>}/>

    <section className="panel dev-intro">
      <div><Code2 size={20}/><div><strong>{ui('developer.playground')}</strong><p>{ui('developer.playgroundHint')}</p></div></div>
      <span className="small-label">{ui('developer.only')}</span>
    </section>

    <section className="panel config-group dev-quick-tools">
      <div className="panel-heading"><div><Wrench size={18}/><h2 aria-label={ui('developer.quickTools')} data-text={ui('developer.quickTools')}>{ui('developer.quickTools')}</h2></div><span className="small-label">{ui('developer.only')}</span></div>
      <div className="dev-control-block">
        <div className="dev-control-label"><strong>{ui('developer.simulateIcons')}</strong><span>{ui('developer.simulateIconsHint')}</span></div>
        <div className="dev-button-row">
          <button type="button" className="button secondary" onClick={() => simulateStatus('running')}><CirclePlay size={15}/>{ui('developer.simulateRunning')}</button>
          <button type="button" className="button secondary" onClick={() => simulateStatus('error')}><CircleAlert size={15}/>{ui('developer.simulateError')}</button>
          <button type="button" className="button secondary" onClick={() => simulateStatus('updating')}><RefreshCw size={15}/>{ui('developer.simulateUpdating')}</button>
          <button type="button" className="button" disabled={!override.status} onClick={() => simulateStatus(null)}>{ui('developer.simulateClear')}</button>
        </div>
        <p className="dev-hint" role="status">{override.status ? ui('developer.simulating', {status: statusLabel}) : ui('developer.simulateIdleHint')}</p>
      </div>
      <div className="dev-control-block">
        <div className="dev-control-label"><strong>{ui('developer.updateNotice')}</strong><span>{ui('developer.updateNoticeHint')}</span></div>
        <div className="dev-button-row">
          <button type="button" className="button secondary" aria-pressed={override.updatePreview} onClick={() => previewUpdate(!override.updatePreview)}><Bell size={15}/>{ui('developer.updateNoticeToggle')}</button>
        </div>
      </div>
      <div className="dev-control-block">
        <div className="dev-control-label"><strong>{ui('developer.throwTest')}</strong><span>{ui('developer.throwTestHint')}</span></div>
        <div className="dev-button-row">
          <button type="button" className="button danger subtle" onClick={() => setThrowing(true)}><CircleAlert size={15}/>{ui('developer.throwTest')}</button>
        </div>
      </div>
    </section>
    {throwing && <CrashTest/>}

    <section className="panel config-group">
      <div className="panel-heading"><div><Gauge size={18}/><h2 aria-label={ui('developer.motionLab')} data-text={ui('developer.motionLab')}>{ui('developer.motionLab')}</h2></div><span className="small-label">{ui('developer.liveTuning')}</span></div>
      <div className="dev-control-block">
        <div className="dev-control-label"><strong>{ui('developer.motionSpeed')}</strong><span>{ui('developer.motionSpeedHint')}</span></div>
        <div className="dev-button-row">
          {([[1, '1×'], [2, '0.5×'], [4, '0.25×']] as const).map(([value, label]) => <button key={value} type="button" className="button secondary" aria-pressed={motionPrefs.speed === value} onClick={() => setMotionSpeed(value)}>{label}</button>)}
        </div>
      </div>
      <div className="dev-control-block">
        <div className="dev-control-label"><strong>{ui('developer.motionStrength')}</strong></div>
        <div className="dev-button-row">
          <button type="button" className="button secondary" aria-pressed={motionPrefs.strength === 'standard'} onClick={() => setMotionStrength('standard')}>{ui('developer.motionStandard')}</button>
          <button type="button" className="button secondary" aria-pressed={motionPrefs.strength === 'strong'} onClick={() => setMotionStrength('strong')}>{ui('developer.motionStrong')}</button>
        </div>
      </div>
      <div className="dev-control-block">
        <div className="dev-control-label"><strong>{ui('developer.motionReduced')}</strong></div>
        <div className="dev-button-row">
          <button type="button" className="button secondary" aria-pressed={motionPrefs.reduced} onClick={() => setMotionReduced(!motionPrefs.reduced)}>{ui('developer.motionReducedToggle')}</button>
          <button type="button" className="button secondary" onClick={() => replayLastPageTransition()}>{ui('developer.motionReplay')}</button>
          <button type="button" className="button secondary" onClick={() => resetMotionPrefs()}>{ui('developer.motionReset')}</button>
        </div>
      </div>
      <p className="dev-hint">{ui('developer.motionHint')}</p>
    </section>

    <section className="panel config-group">
      <div className="panel-heading"><div><Layers3 size={18}/><h2 aria-label={ui('developer.layers')} data-text={ui('developer.layers')}>{ui('developer.layers')}</h2></div></div>
      <div className="dev-surface-grid">
        <div className="dev-surface-sample dev-surface-plain"><span>{ui('developer.tokenSurface')}</span><strong>{ui('developer.surfacePlain')}</strong><small>var(--surface)</small></div>
        <div className="dev-surface-sample dev-surface-muted"><span>{ui('developer.tokenMuted')}</span><strong>{ui('developer.surfaceMuted')}</strong><small>var(--surface-muted)</small></div>
        <div className="dev-surface-sample dev-surface-accent"><span>{ui('developer.tokenAccent')}</span><strong>{ui('developer.surfaceAccent')}</strong><small>var(--accent-soft)</small></div>
        <div className="dev-surface-sample dev-surface-glass"><span>{ui('developer.backdropGlass')}</span><strong>{ui('developer.surfaceGlass')}</strong></div>
      </div>
      <div className="dev-shadow-grid">
        {[[ui('developer.shadowNone'), 'none'], [ui('developer.shadowLight'), '0 4px 14px #00000010'], [ui('developer.shadowPanel'), 'var(--glass-shadow)'], [ui('developer.shadowFloating'), '0 18px 56px #0003'], [ui('developer.shadowModal'), '0 24px 100px #0003']].map(([label, value]) => <div key={label} className="dev-shadow-sample" style={{boxShadow: value}}><strong>{label}</strong><code>{value}</code></div>)}
      </div>
      <div className="dev-radius-grid">
        {[0, 6, 10, 14, 18, 22, 26, 32, 999].map(value => <div key={value}><span style={{borderRadius: `${value}px`}}/><small>{value === 999 ? ui('developer.pill') : `${value}px`}</small></div>)}
      </div>
    </section>

    <section className="panel config-group">
      <div className="panel-heading"><h2 aria-label={ui('developer.colorsTokens')} data-text={ui('developer.colorsTokens')}>{ui('developer.colorsTokens')}</h2></div>
      <div className="dev-token-grid">
        {[
          [ui('developer.tokenText'), '--text'], [ui('developer.tokenMuted'), '--muted'], [ui('developer.tokenAccent'), '--accent'], [ui('developer.tokenAccentSoft'), '--accent-soft'],
          [ui('developer.tokenSurface'), '--surface'], [ui('developer.tokenSurfaceMuted'), '--surface-muted'], [ui('developer.tokenBorder'), '--border'], [ui('developer.tokenGlassTint'), '--glass-tint'],
          [ui('developer.tokenGlassEdge'), '--glass-edge'], [ui('developer.tokenGreen'), '--green'], [ui('developer.tokenRed'), '--red'], [ui('developer.tokenBackground'), '--bg'],
        ].map(([label, token]) => <div className="dev-token" key={token}><span style={{background: `var(${token})`}}/><div><strong>{label}</strong><code>var({token})</code></div></div>)}
      </div>
    </section>

    <section className="panel config-group">
      <div className="panel-heading"><h2 aria-label={ui('developer.typography')} data-text={ui('developer.typography')}>{ui('developer.typography')}</h2></div>
      <div className="dev-type-grid">
        <div><span className="small-label">{ui('developer.typePageTitle')}</span><h1>{ui('developer.samplePageTitle')}</h1></div>
        <div><span className="small-label">{ui('developer.typeSectionHeading')}</span><h2>{ui('developer.sampleSectionHeading')}</h2></div>
        <div><span className="small-label">{ui('developer.typeCardHeading')}</span><h3>{ui('developer.sampleCardHeading')}</h3></div>
        <div><span className="small-label">{ui('developer.typeBody')}</span><p>{ui('developer.sampleBody')}</p></div>
        <div><span className="small-label">{ui('developer.typeMuted')}</span><p className="muted">{ui('developer.sampleMuted')}</p></div>
        <div><span className="small-label">{ui('developer.typeCode')}</span><code>Scheduler.Enable = true</code></div>
        <div><span className="small-label">{ui('developer.numberLabel')}</span><strong className="dev-numeric">12,345.67 / 99.8%</strong></div>
        <div><span className="small-label">{ui('developer.ellipsisLabel')}</span><div className="dev-ellipsis">{ui('developer.ellipsisSample')}</div></div>
      </div>
    </section>

    <section className="panel config-group">
      <div className="panel-heading"><div><Code2 size={18}/><h2 aria-label={ui('developer.buttons')} data-text={ui('developer.buttons')}>{ui('developer.buttons')}</h2></div></div>
      <div className="dev-control-block">
        <div className="dev-control-label"><strong>{ui('developer.buttonStyles')}</strong><span>{ui('developer.buttonStylesHint')}</span></div>
        <div className="dev-button-row">
          <button className="button">{ui('developer.buttonDefault')}</button>
          <button className="button primary">{ui('developer.buttonPrimary')}</button>
          <button className="button secondary">{ui('developer.buttonSecondary')}</button>
          <button className="button danger"><Trash2 size={15}/>{ui('developer.buttonDanger')}</button>
          <button className="button danger subtle">{ui('developer.buttonDangerSubtle')}</button>
          <button className="button primary" disabled>{ui('developer.buttonDisabled')}</button>
        </div>
      </div>
      <div className="dev-control-block">
        <div className="dev-control-label"><strong>{ui('developer.lightActions')}</strong><span>{ui('developer.lightActionsHint')}</span></div>
        <div className="dev-button-row">
          <button className="icon-button" aria-label={ui('nav.settings')}><Settings2 size={18}/></button>
          <button className="icon-button" aria-label={ui('common.close')}><X size={18}/></button>
          <button className="text-button">{ui('developer.textButton')}</button>
          <button className="button secondary" onClick={() => setModalOpen(true)}>{ui('developer.openModal')}</button>
        </div>
      </div>
    </section>

    <section className="panel config-group">
      <div className="panel-heading"><h2 aria-label={ui('developer.formControls')} data-text={ui('developer.formControls')}>{ui('developer.formControls')}</h2></div>
      <DevField id="dev-text" label={ui('developer.textInput')} help={ui('developer.textInputHelp')}>
        <FieldInput id="dev-text" label={ui('developer.textInput')} value={text} onChange={value => setText(String(value ?? ''))}/>
      </DevField>
      <DevField id="dev-number" label={ui('developer.numberInput')} help={ui('developer.numberInputHelp')}>
        <FieldInput id="dev-number" label={ui('developer.numberInput')} type="number" value={number} onChange={value => setNumber(Number(value))}/>
      </DevField>
      <DevField id="dev-password" label={ui('developer.passwordInput')}>
        <FieldInput id="dev-password" label={ui('developer.passwordInput')} type="password" value={password} onChange={value => setPassword(String(value ?? ''))}/>
      </DevField>
      <DevField id="dev-select" label={ui('developer.selectInput')} help={ui('developer.selectInputHelp')}>
        <FieldInput id="dev-select" label={ui('developer.selectInput')} value={select} options={['Auto', 'ADB', 'Nemulator']} onChange={setSelect}/>
      </DevField>
      <DevField id="dev-datetime" label={ui('developer.dateTime')}>
        <FieldInput id="dev-datetime" label={ui('developer.dateTime')} type="datetime" value={dateTime} onChange={setDateTime}/>
      </DevField>
      <DevField id="dev-month" label={ui('developer.month')}>
        <input id="dev-month" aria-label={ui('developer.month')} type="month" value={month} onChange={event => setMonth(event.target.value)}/>
      </DevField>
      <DevField id="dev-toggle" label={ui('developer.toggle')} help={ui('developer.toggleHelp')}>
        <div className="dev-inline-controls">
          <FieldInput id="dev-toggle" label={ui('developer.toggle')} type="bool" value={toggle} onChange={setToggle}/>
          <FieldInput id="dev-toggle-off" label={ui('developer.toggleOff')} type="bool" value={false} onChange={() => undefined}/>
          <FieldInput id="dev-toggle-disabled" label={ui('developer.toggleDisabled')} type="bool" value={true} disabled onChange={() => undefined}/>
        </div>
      </DevField>
      <DevField id="dev-multi" label={ui('developer.multiSelect')} help={ui('developer.multiSelectHelp')}>
        <FieldInput id="dev-multi" label={ui('developer.multiSelect')} type="multiselect" value={multi} options={['Alas', 'Opsi', 'Commission', 'Event']} onChange={setMulti}/>
      </DevField>
      <DevField id="dev-disabled" label={ui('developer.disabledInput')}>
        <FieldInput id="dev-disabled" label={ui('developer.disabledInput')} value={ui('developer.disabledValue')} disabled onChange={() => undefined}/>
      </DevField>
      <DevField id="dev-invalid" label={ui('developer.invalidInput')} help={ui('developer.invalidInputHelp')}>
        <FieldInput id="dev-invalid" label={ui('developer.invalidInput')} value="invalid-value" invalid onChange={() => undefined}/>
        <div id="dev-invalid-status" className="edit-status edit-error" role="alert"><CircleAlert size={14} aria-hidden="true"/>{ui('developer.invalidInputMessage')}</div>
      </DevField>
      <DevField id="dev-search" label={ui('developer.iconInput')}>
        <div className="input-icon"><Search size={15}/><input id="dev-search" aria-label={ui('developer.iconInput')} placeholder={ui('developer.searchPlaceholder')}/></div>
      </DevField>
      <DevField id="dev-textarea" label={ui('developer.textarea')} multiline>
        <FieldInput id="dev-textarea" label={ui('developer.textarea')} type="textarea" value={textarea} onChange={setTextarea}/>
      </DevField>
      <DevField id="dev-yaml" label={ui('developer.yamlEditor')} help={ui('developer.yamlHelp')} multiline>
        <FieldInput id="dev-yaml" label={ui('developer.yamlEditor')} type="yaml" value={yaml} onChange={setYaml}/>
      </DevField>
    </section>

    <section className="panel config-group">
      <div className="panel-heading"><h2 aria-label={ui('developer.selectorsStatus')} data-text={ui('developer.selectorsStatus')}>{ui('developer.selectorsStatus')}</h2></div>
      <div className="dev-control-block">
        <div className="dev-control-label"><strong>{ui('developer.segmented')}</strong><span>{ui('developer.segmentedHint')}</span></div>
        <SegmentedControl label={ui('developer.segmentedLabel')} value={segment} onChange={setSegment} options={[
          {value: 'logs', label: <><Terminal size={15}/>{ui('monitor.logs')}</>},
          {value: 'preview', label: <><Image size={15}/>{ui('monitor.preview')}</>},
        ]}/>
      </div>
      <div className="dev-control-block">
        <div className="dev-control-label"><strong>{ui('developer.statusBadges')}</strong><span>{ui('developer.statusBadgesHint')}</span></div>
        <div className="dev-button-row">
          <StatusBadge status="running"/><StatusBadge status="stopped"/><StatusBadge status="error"/><StatusBadge status="updating"/>
          <span className="count-badge">12</span><span className="live-label"><i/>{ui('developer.live')}</span><span className="update-notice"><Bell size={13}/>{ui('nav.newVersion')}</span>
        </div>
      </div>
      <div className="dev-control-block">
        <div className="dev-control-label"><strong>{ui('developer.statsTabs')}</strong><span>{ui('developer.statsTabsHint')}</span></div>
        <SegmentedControl label={ui('developer.statsTabsLabel')} value={demoTab} onChange={setDemoTab} options={[
          {value: 'resources', label: ui('developer.tabResources')},
          {value: 'loot', label: ui('developer.tabLoot')},
          {value: 'action', label: ui('developer.tabAction')},
          {value: 'commission', label: ui('developer.tabCommission')},
        ]}/>
      </div>
    </section>

    <section className="panel config-group">
      <div className="panel-heading"><h2 aria-label={ui('developer.layout')} data-text={ui('developer.layout')}>{ui('developer.layout')}</h2></div>
      <div className="dev-layout-grid">
        <div className="dev-nav-preview">
          <span className="small-label">{ui('nav.primary')}</span>
          <nav className="primary-nav">
            <a href="#dev-nav" onClick={event => event.preventDefault()}><Server size={18}/>{ui('developer.navNormal')}</a>
            <a href="#dev-nav" className="active" onClick={event => event.preventDefault()}><Database size={18}/>{ui('developer.navCurrent')}<span className="nav-pill">DEV</span></a>
            <a href="#dev-nav" onClick={event => event.preventDefault()}><Settings2 size={18}/>{ui('developer.navHover')}</a>
          </nav>
          <div className="task-group-button expanded"><Layers3 size={18} className="task-group-icon"/><MarqueeText className="task-group-title" text={ui('developer.taskGroup')}/><ChevronRight size={13} className="task-group-arrow"/></div>
          <div className="task-submenu-list dev-submenu-list">
            <a className="task-submenu-item active" href="#dev-sub" onClick={event => event.preventDefault()}><span className="task-submenu-dot"/><MarqueeText className="task-submenu-item-text" text={ui('developer.submenuCurrent')}/></a>
            <a className="task-submenu-item" href="#dev-sub" onClick={event => event.preventDefault()}><span className="task-submenu-dot"/><MarqueeText className="task-submenu-item-text" text={ui('developer.submenuNormal')}/></a>
          </div>
        </div>
        <div className="dev-card-preview">
          <span className="small-label">{ui('developer.instanceCard')}</span>
          <div className="instance-card panel">
            <div className="instance-card-heading"><span className="home-instance-icon"><Server size={22}/></span><StatusBadge status="running"/></div>
            <h3>dev-instance</h3><div className="instance-device"><span>ADB</span><span>127.0.0.1:5555</span></div>
            <div className="instance-card-footer"><span>{ui('developer.instanceRunning')}</span><ArrowRight size={17}/></div>
          </div>
        </div>
        <div className="dev-metric-preview">
          <span className="small-label">{ui('developer.metricCards')}</span>
          <div className="summary-metrics stat-metrics">
            <section><span>{ui('resource.Coin')}</span><strong>52,840<small>/ 600,000</small></strong></section>
            <section><span>{ui('resource.Oil')}</span><strong>14,320<small>/ 25,000</small></strong></section>
            <section><span>{ui('developer.runCount')}</span><strong>128<small>{ui('developer.times')}</small></strong></section>
          </div>
        </div>
      </div>
    </section>

    <section className="panel config-group">
      <div className="panel-heading"><h2 aria-label={ui('developer.dataTables')} data-text={ui('developer.dataTables')}>{ui('developer.dataTables')}</h2></div>
      <div className="statistics-table dev-table-preview">
        <div className="table-toolbar"><div className="input-icon"><Search size={14}/><input aria-label={ui('stats.searchPlaceholder')} placeholder={ui('stats.searchPlaceholder')}/></div><span>{ui('stats.records', {count: 3})}</span></div>
        <div className="table-scroll">
          <table><thead><tr><th>{ui('stats.time')}</th><th>{ui('developer.tableTask')}</th><th>{ui('developer.tableStatus')}</th><th>{ui('developer.tableDuration')}</th></tr></thead><tbody>
            <tr><td>09:18:02</td><td>{ui('developer.demoMainline')}</td><td><span className="status running"><i/>{ui('developer.demoCompleted')}</span></td><td>01:42</td></tr>
            <tr><td>09:15:43</td><td>{ui('developer.demoResearch')}</td><td><span className="status updating"><i/>{ui('developer.demoSync')}</span></td><td>00:18</td></tr>
            <tr><td>09:12:10</td><td>{ui('developer.demoCommission')}</td><td><span className="status stopped"><i/>{ui('developer.demoIdle')}</span></td><td>00:06</td></tr>
          </tbody></table>
        </div>
      </div>
      <div className="dev-scroll-sample"><div>{Array.from({length: 12}, (_, index) => <p key={index}><code>{String(index + 1).padStart(2, '0')}</code> {ui('developer.scrollSample')}</p>)}</div></div>
    </section>

    <section className="panel config-group">
      <div className="panel-heading"><h2 aria-label={ui('developer.feedback')} data-text={ui('developer.feedback')}>{ui('developer.feedback')}</h2></div>
      <div className="dev-feedback-grid">
        <div><span className="small-label">{ui('developer.errorLabel')}</span><ErrorBox message={ui('developer.errorMessage')} retry={() => notify(ui('developer.retryTriggered'))}/></div>
        <div><span className="small-label">{ui('developer.loadingLabel')}</span><div className="dev-state-box"><Loading/></div></div>
        <div><span className="small-label">{ui('developer.emptyLabel')}</span><div className="dev-state-box"><Empty icon={<CircleAlert size={34}/>} title={ui('developer.emptyTitle')}>{ui('developer.emptyHint')}</Empty></div></div>
      </div>
    </section>

    {modalOpen && <Modal title={ui('developer.modalPreview')} onClose={() => setModalOpen(false)}><div className="form-stack"><p className="muted">{ui('developer.modalHint')}</p><label>{ui('developer.sampleInput')}<input defaultValue="AzurPilot Dev Mode"/></label><div className="dev-button-row"><button className="button secondary" onClick={() => setModalOpen(false)}>{ui('common.cancel')}</button><button className="button primary" onClick={() => setModalOpen(false)}>{ui('common.confirm')}</button></div></div></Modal>}
  </>
}

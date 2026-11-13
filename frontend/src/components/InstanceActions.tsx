/**
 * @fileoverview 实例资源卡片设置入口与选项弹窗。
 */

import { useState, useSyncExternalStore } from 'react'
import { Settings2 } from 'lucide-react'
import type { Resource } from '../api/types'
import { useApp } from '../app/context'
import { readDashboardPrefs, setDashboardPref, subscribeDashboardPrefs, type DashboardPrefs } from '../app/dashboardPrefs'
import type { UiKey } from '../i18n'
import { FieldInput } from './FieldInput'
import { ResourceSettings } from './ResourceCards'
import { Modal } from './ui'

const DASHBOARD_OPTIONS: {key: keyof DashboardPrefs; label: UiKey; help: UiKey}[] = [
  {key: 'fitCards', label: 'dashboard.fitCards', help: 'dashboard.fitCardsHelp'},
  {key: 'fitText', label: 'dashboard.fitText', help: 'dashboard.fitTextHelp'},
  {key: 'dense', label: 'dashboard.dense', help: 'dashboard.denseHelp'},
  {key: 'merged', label: 'dashboard.merged', help: 'dashboard.mergedHelp'},
  {key: 'totalFirst', label: 'dashboard.totalFirst', help: 'dashboard.totalFirstHelp'},
  {key: 'dogIcon', label: 'dashboard.dogIcon', help: 'dashboard.dogIconHelp'},
]
/** 实例卡片上的设置齿轮：打开「仪表盘」弹窗，调整仪表盘选项与资源卡片显隐。 */
export function InstanceActions({resources, selectedResources, onResourcesChange}: {resources: Resource[]; selectedResources: string[]; onResourcesChange: (keys: string[]) => void}) {
  const [open, setOpen] = useState(false)
  const {ui} = useApp()
  // 无障碍名称用「仪表盘设置」，可见文字在紧凑下换成「资源卡片设置」。
  return <><button className="button" aria-label={ui('instance.settings')} title={ui('instance.settings')} onClick={() => setOpen(true)}><Settings2 size={16}/></button>{open && <InstanceSettings resources={resources} selectedResources={selectedResources} onResourcesChange={onResourcesChange} onClose={() => setOpen(false)}/>}</>
}

function InstanceSettings({resources, selectedResources, onResourcesChange, onClose}: {resources: Resource[]; selectedResources: string[]; onResourcesChange: (keys: string[]) => void; onClose: () => void}) {
  const {ui} = useApp()
  const dashboardPrefs = useSyncExternalStore(subscribeDashboardPrefs, readDashboardPrefs, readDashboardPrefs)
  return <Modal title={ui('instance.dashboard')} onClose={onClose}><div className="form-stack">
    <div className="dashboard-options">{DASHBOARD_OPTIONS.map(option => <div className="dashboard-option" key={option.key}>
      <div className="dashboard-option-label"><strong>{ui(option.label)}</strong><span>{ui(option.help)}</span></div>
      <FieldInput id={`dashboard-${option.key}`} label={ui(option.label)} value={dashboardPrefs[option.key]} onChange={value => setDashboardPref(option.key, value === true)}/>
    </div>)}</div>
    <ResourceSettings resources={resources} selected={selectedResources} onChange={onResourcesChange}/>
  </div></Modal>
}

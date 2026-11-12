/**
 * @fileoverview 配置实例管理页面，提供实例列表概览、导出、导入与删除。
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Download, FileJson, MonitorSmartphone, Play, Plus, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { useApp, useConnection } from '../app/context'
import { CreateInstance } from '../app/App'
import { taskLabel } from '../components/taskNavItems'
import { ActionGroup, Empty, ErrorBox, Loading, StatusBadge } from '../components/ui'

/** 把配置写成 json 文件下载。内容即配置本体（含 Alas 段），与导入接口期望的格式一致。 */
function downloadJson(filename: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

/**
 * 配置管理：列出全部配置实例，提供概览 / 导出 / 删除，以及新建与导入的入口。
 *
 * 页头把实例计数摘要与新建/导入按钮锚定在同一行（按钮不孤悬右上角）；
 * 实例卡片走响应式网格，动作条满宽等分、永不孤儿换行；数据未加载时先给加载占位，不闪空态。
 *
 * 删除要带 revision（磁盘 JSON 的 SHA-256），所以先取一次配置再删。
 */
export function ConfigManager() {
  const {instances, instancesLoaded, t, ui, notify, refresh} = useApp()
  const connection = useConnection()
  const [creating, setCreating] = useState<null | 'new' | 'import'>(null)
  const [busy, setBusy] = useState('')
  const [confirming, setConfirming] = useState('')
  const [error, setError] = useState('')

  const notReady = connection !== 'ready'
  const actions = <>
    <button className="button secondary" disabled={notReady} onClick={() => setCreating('import')}><FileJson size={15}/>{ui('config.import')}</button>
    <button className="button primary" disabled={notReady} onClick={() => setCreating('new')}><Plus size={16}/>{ui('config.create')}</button>
  </>

  async function exportConfig(name: string) {
    setBusy(name); setError('')
    try {
      const config = await api.request('config.export', {instance: name})
      downloadJson(`${name}.json`, config)
      notify(ui('config.exported', {name}))
    } catch (error) { setError((error as Error).message) } finally { setBusy('') }
  }

  async function remove(name: string) {
    setBusy(name); setError('')
    try {
      const config = await api.request('config.get', {instance: name})
      await api.request('instances.delete', {instance: name, revision: config.revision})
      await refresh()
      notify(ui('instance.backupNotice'))
    } catch (error) { setError((error as Error).message) } finally { setBusy(''); setConfirming('') }
  }

  return <div className="settings-page">
    <header className="config-head">
      <h1 className="sr-only">{ui('nav.configs')}</h1>
      {instancesLoaded && <span className="config-head-summary">{ui('config.count', {count: instances.length})}</span>}
      <ActionGroup>{actions}</ActionGroup>
    </header>
    {error && <ErrorBox message={error}/>}
    {!instancesLoaded ? <Loading/> : instances.length ? <div className="config-grid">
      {instances.map(item => <section className="panel config-group config-card" key={item.name}>
        <div className="config-card-head">
          <h2 role="heading" aria-level={2}>{item.name}</h2>
          <StatusBadge status={item.status}/>
        </div>
        <div className="config-card-meta">
          <span className="config-card-server"><MonitorSmartphone size={13}/>{item.server !== 'disabled' ? t(`Emulator.ServerName.${item.server}`) : ui('common.notSet')}</span>
          <span className="config-card-serial">{item.serial}</span>
        </div>
        {item.currentTask && <div className="config-card-task"><Play size={12}/>{taskLabel(item.currentTask, ui, t)}</div>}
        {confirming === item.name && <p className="config-card-hint">{ui('instance.deletePrompt', {name: item.name})}</p>}
        <div className="config-card-foot">
          <Link className="button primary" to={`/i/${item.name}/overview`}><ArrowRight size={15}/>{ui('config.overview')}</Link>
          <button className="button secondary" disabled={busy === item.name} onClick={() => void exportConfig(item.name)}><Download size={15}/>{ui('config.export')}</button>
          {confirming === item.name
            ? <button className="button danger" disabled={busy === item.name} onClick={() => void remove(item.name)}><Trash2 size={15}/>{ui('instance.deleteConfirm')}</button>
            : <button className="button danger subtle" onClick={() => setConfirming(item.name)}><Trash2 size={15}/>{ui('instance.delete')}</button>}
        </div>
      </section>)}
    </div>
      : <div className="config-empty">
        <Empty icon={<FileJson size={30}/>} title={ui('config.empty')}>{ui('config.emptyHint')}</Empty>
        <ActionGroup className="config-empty-actions">{actions}</ActionGroup>
      </div>}
    {creating && <CreateInstance onClose={() => setCreating(null)} startWithImport={creating === 'import'}/>}
  </div>
}

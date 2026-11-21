/**
 * @fileoverview 系统版本更新与 Git 提交历史检查页面。
 */

import { useCallback, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { ArrowDown, ArrowUp, Check, CircleAlert, Copy, Download, GitBranch, GitCommitHorizontal, RefreshCw, TriangleAlert, X } from 'lucide-react'
import { api } from '../api/client'
import type { UpdaterState } from '../app/updater'
import { useApp, useConnection } from '../app/context'
import { usePageRead } from '../app/usePageRead'
import { ActionGroup, Empty, Modal, PageTitle, Panel, PanelHeading } from '../components/ui'
import { LoadBoundary } from '../components/ui/load-boundary'
import { localeForLanguage, type UiKey } from '../i18n'
import './Updater.css'

/** 后端更新状态字符串 → 界面文案键；'run update' 与 apply 共用一条文案。 */
const states: Record<string, UiKey> = {idle: 'updater.state.idle', android: 'updater.state.android', available: 'updater.state.available', fetch: 'updater.state.fetch', checking: 'updater.state.checking', apply: 'updater.state.apply', start: 'updater.state.start', wait: 'updater.state.wait', 'run update': 'updater.state.apply', reload: 'updater.state.reload', failed: 'updater.state.failed', finish: 'updater.state.finish', cancel: 'updater.state.cancel'}

/**
 * 更新器页：本地与上游 HEAD 概览、提交历史分页列表与抓取/应用/取消操作。
 * 状态数据取自 outlet 上下文（UpdaterState），本组件只负责展示与触发。
 *
 * 操作按钮收进居中内容列顶部（.updater-head，与下方卡片左右边缘对齐），不再孤悬屏幕角落；
 * 本地/上游 HEAD 双列并排；哈希为纯等宽文本 + 复制按钮，不做输入框的样子。
 */
export function Updater() {
  const {data, error: statusError, refresh} = useOutletContext<UpdaterState>()
  const {ui} = useApp()
  const connection = useConnection()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [confirmMismatch, setConfirmMismatch] = useState(false)
  const [copiedSha, setCopiedSha] = useState('')
  const local = data?.localHead, upstream = data?.upstreamHead
  async function act(method: 'updater.fetch' | 'updater.apply' | 'updater.cancel') {
    setBusy(true); setError('')
    try {await api.request(method, {}); refresh()}
    catch (error) {setError((error as Error).message)} finally {setBusy(false)}
  }
  /** 复制哈希到剪贴板；按钮图标短暂换成对勾作为反馈。 */
  function copySha(sha: string) {
    void navigator.clipboard?.writeText(sha)
    setCopiedSha(sha)
    window.setTimeout(() => setCopiedSha(value => value === sha ? '' : value), 1500)
  }
  // SHA 不匹配时更新会重置掉本地独有的提交，先弹窗确认再执行。
  function requestUpdate() {
    if (data?.shaMismatch) setConfirmMismatch(true)
    else void act('updater.apply')
  }
  const disabled = busy || connection !== 'ready' || !data || data.busy
  const stateLabel = states[data?.state ?? '']
  const statusLabel = !local || !upstream ? ui('updater.noVersion') : data?.state === 'failed' ? ui('updater.state.failed') : data?.available && !data.busy ? ui('updater.state.available') : stateLabel ? ui(stateLabel) : data?.state
  return <div className="settings-page">
    {!data?.managedByAndroid && <header className="updater-head">
      <PageTitle title={ui('nav.updater')} placement="screen-reader"/>
      {data && <span className={`updater-head-summary${data.available && !data.busy ? ' update-available' : ''}`}><GitBranch size={14}/>{statusLabel}</span>}
      <ActionGroup>
        <button className="button secondary" disabled={disabled} onClick={() => void act('updater.fetch')}><RefreshCw size={16} className={data?.state === 'fetch' || data?.state === 'checking' ? 'spin' : ''}/>{ui('updater.fetch')}</button>
        <button className="button primary" disabled={disabled || !data?.canApply} onClick={requestUpdate}><Download size={16}/>{ui('updater.update')}</button>
        {data?.canCancel && <button className="button secondary" disabled={busy || connection !== 'ready'} onClick={() => void act('updater.cancel')}><X size={16}/>{ui('updater.cancel')}</button>}
      </ActionGroup>
    </header>}
    <LoadBoundary ready={!!data} error={error || statusError || data?.error} retry={refresh}>
    {data && <>
      {data.managedByAndroid && <Panel compact><p className="panel-note">{ui('updater.androidManaged')}</p></Panel>}
      <div className="head-grid">
        {[
          {label: ui('updater.localHead'), sha: local, isLocal: true},
          {label: ui('updater.upstreamHead'), sha: upstream, isLocal: false},
        ].map(({label, sha, isLocal}) => <Panel compact className="head-card" key={label}>
          <div className="panel-heading">
            <div><h2 role="heading" aria-level={2}>{label}</h2></div>
            {isLocal && <div className="update-summary">
              <span className={data.available ? 'update-available' : ''}>{data.busy ? <RefreshCw size={15} className="spin"/> : data.state === 'failed' || !upstream ? <CircleAlert size={15}/> : <Check size={15}/>} {statusLabel}</span>
              {data.ahead > 0 && <span title={ui('updater.localAhead')}><ArrowUp size={14}/>{data.ahead}</span>}
              {data.behind > 0 && <span title={ui('updater.localBehind')}><ArrowDown size={14}/>{data.behind}</span>}
            </div>}
          </div>
          <div className="head-sha-row">
            <code className="head-sha" title={sha ?? ''}>{sha ?? ui('common.notFetched')}</code>
            {sha && <button type="button" className="icon-button head-sha-copy" title={ui('common.copy')} aria-label={`${ui('common.copy')} · ${label}`} onClick={() => copySha(sha)}>
              {copiedSha === sha ? <Check size={14}/> : <Copy size={14}/>}
            </button>}
          </div>
        </Panel>)}
      </div>
      {data.shaMismatch ? <p className="mismatch-note" role="alert"><TriangleAlert size={15}/><span>{ui('updater.shaMismatch.banner')}</span></p>
        : data.ahead > 0 && <p className="muted">{ui('updater.aheadCommits', {count: data.ahead})}</p>}
      {!data.managedByAndroid && <CommitList key={JSON.stringify([local, upstream])} local={local} upstream={upstream} branch={data.branch}/>}
      {confirmMismatch && <Modal title={ui('updater.shaMismatch.title')} onClose={() => setConfirmMismatch(false)}>
        <p>{ui('updater.shaMismatch.body', {count: data?.ahead ?? 0})}</p>
        <ul className="mismatch-reasons">
          <li>{ui('updater.shaMismatch.reasonMirror')}</li>
          <li>{ui('updater.shaMismatch.reasonLocal')}</li>
        </ul>
        <div className="multi-options">
          <button className="button" onClick={() => setConfirmMismatch(false)}>{ui('common.cancel')}</button>
          <button className="button primary" disabled={busy} onClick={() => {setConfirmMismatch(false); void act('updater.apply')}}>{ui('updater.shaMismatch.confirm')}</button>
        </div>
      </Modal>}
    </>}</LoadBoundary>
  </div>
}

function CommitList({local, upstream, branch}: {local?: string | null; upstream?: string | null; branch: string}) {
  const {ui, language} = useApp()
  const connection = useConnection()
  const [offset, setOffset] = useState(0)
  const load = useCallback(() => api.request('updater.commits', {offset, limit: 50}), [offset])
  const {data: history, ready, error, busy, reload} = usePageRead(String(offset), connection === 'ready' && local !== undefined, load)
  return <Panel className="commit-panel">
    <PanelHeading icon={<GitCommitHorizontal size={18}/>} title={ui('updater.commits')} actions={<div className="branch-summary"><span className="count-badge">{history?.total ?? '—'}</span><GitBranch size={16}/><span>{branch}</span></div>}/>
    <LoadBoundary ready={ready} error={error} retry={reload}>
        {history?.entries.length ? <div className="commit-list">{history.entries.map(commit => <article className="commit-row" key={commit.sha}>
          <GitCommitHorizontal className="commit-node" size={18}/><div className="commit-detail"><div className="commit-subject">{commit.message.split('\n')[0]}{commit.sha === local && <span className="commit-ref local">{ui('updater.localHead')}</span>}{commit.sha === upstream && <span className="commit-ref upstream">{ui('updater.upstreamHead')}</span>}</div>
          {commit.message.includes('\n') && <details><summary>{ui('updater.expandDetails')}</summary><pre>{commit.message.slice(commit.message.indexOf('\n')).trim()}</pre></details>}
          <div className="commit-meta"><span>{commit.author}</span><time dateTime={commit.date}>{new Date(commit.date).toLocaleString(localeForLanguage(language))}</time></div></div>
          <code className="commit-sha-chip" title={commit.sha}>{commit.sha.slice(0, 7)}</code>
        </article>)}</div> : <Empty title={ui('updater.noCommits')}/>}
        <div className="commit-pagination"><span>{history?.total ? `${offset + 1}–${Math.min(offset + 50, history.total)} / ${history.total}` : '0'}</span><button className="button" disabled={busy || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 50))}>{ui('common.previous')}</button><button className="button" disabled={busy || !history?.hasMore} onClick={() => setOffset(value => value + 50)}>{ui('common.next')}</button></div>
    </LoadBoundary>
  </Panel>
}

import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { ArrowDown, ArrowUp, Check, CircleAlert, Download, GitBranch, GitCommitHorizontal, RefreshCw, TriangleAlert, X } from 'lucide-react'
import { api } from '../api/client'
import type { CommitHistory } from '../api/types'
import type { UpdaterState } from '../app/updater'
import { useApp, useConnection } from '../app/context'
import { Empty, ErrorBox, Loading, Modal, PageTitle } from '../components/ui'
import { localeForLanguage, type UiKey } from '../i18n'

const states: Record<string, UiKey> = {idle: 'updater.state.idle', android: 'updater.state.android', available: 'updater.state.available', fetch: 'updater.state.fetch', checking: 'updater.state.checking', apply: 'updater.state.apply', start: 'updater.state.start', wait: 'updater.state.wait', 'run update': 'updater.state.apply', reload: 'updater.state.reload', failed: 'updater.state.failed', finish: 'updater.state.finish', cancel: 'updater.state.cancel'}

export function Updater() {
  const {data, error: statusError, refresh} = useOutletContext<UpdaterState>()
  const {ui, language} = useApp()
  const connection = useConnection()
  const [history, setHistory] = useState<CommitHistory>()
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [confirmMismatch, setConfirmMismatch] = useState(false)
  const local = data?.localHead, upstream = data?.upstreamHead
  useEffect(() => {setOffset(0)}, [local, upstream])
  useEffect(() => {
    if (connection !== 'ready' || local === undefined || data?.managedByAndroid) return
    let active = true
    setLoading(true); setError('')
    void api.request('updater.commits', {offset, limit: 50}).then(value => {
      if (active) setHistory(value)
    }).catch(error => {if (active) setError(error.message)}).finally(() => {if (active) setLoading(false)})
    return () => {active = false}
  }, [connection, data?.managedByAndroid, local, upstream, offset, retry])
  async function act(method: 'updater.fetch' | 'updater.apply' | 'updater.cancel') {
    setBusy(true); setError('')
    try {await api.request(method, {}); refresh()}
    catch (error) {setError((error as Error).message)} finally {setBusy(false)}
  }
  /* SHA 不匹配时更新会重置掉本地独有的提交，先弹窗确认再执行。 */
  function requestUpdate() {
    if (data?.shaMismatch) setConfirmMismatch(true)
    else void act('updater.apply')
  }
  const disabled = busy || connection !== 'ready' || !data || data.busy
  const statusLabel = !local || !upstream ? ui('updater.noVersion') : data?.state === 'failed' ? ui('updater.state.failed') : data?.available && !data.busy ? ui('updater.state.available') : states[data?.state ?? ''] ? ui(states[data?.state ?? '']) : data?.state
  return <>
    <PageTitle title={ui('nav.updater')} actions={data?.managedByAndroid ? undefined : <><button className="button" disabled={disabled} onClick={() => void act('updater.fetch')}><RefreshCw size={16} className={data?.state === 'fetch' || data?.state === 'checking' ? 'spin' : ''}/>{ui('updater.fetch')}</button><button className="button primary" disabled={disabled || !data?.canApply} onClick={requestUpdate}><Download size={16}/>{ui('updater.update')}</button>{data?.canCancel && <button className="button" disabled={busy || connection !== 'ready'} onClick={() => void act('updater.cancel')}><X size={16}/>{ui('updater.cancel')}</button>}</>}/>
    {(error || statusError || data?.error) && <ErrorBox message={error || statusError || data?.error || ''} retry={() => {refresh(); setRetry(value => value + 1)}}/>}
    {!data ? <Loading/> : <>
      {data.managedByAndroid && <section className="panel"><p>{ui('updater.androidManaged')}</p></section>}
      <div className="head-grid">{[
        {label: ui('updater.localHead'), sha: local, isLocal: true},
        {label: ui('updater.upstreamHead'), sha: upstream, isLocal: false},
      ].map(({label, sha, isLocal}) => <div className="panel head-card" key={label}>
        <div className="head-card-header">
          <span><GitCommitHorizontal size={18}/>{label}</span>
          {isLocal && <div className="update-summary">
            <span className={data.available ? 'update-available' : ''}>{data.busy ? <RefreshCw size={15} className="spin"/> : data.state === 'failed' || !upstream ? <CircleAlert size={15}/> : <Check size={15}/>} {statusLabel}</span>
            {data.ahead > 0 && <span title={ui('updater.localAhead')}><ArrowUp size={14}/>{data.ahead}</span>}
            {data.behind > 0 && <span title={ui('updater.localBehind')}><ArrowDown size={14}/>{data.behind}</span>}
          </div>}
        </div>
        <code title={sha ?? ''}>{sha ?? ui('common.notFetched')}</code>
      </div>)}</div>
      {data.shaMismatch ? <p className="mismatch-note" role="alert"><TriangleAlert size={15}/><span>{ui('updater.shaMismatch.banner')}</span></p>
        : data.ahead > 0 && <p className="muted">{ui('updater.aheadCommits', {count: data.ahead})}</p>}
      {!data.managedByAndroid && <section className="panel commit-panel"><div className="panel-heading"><div><GitCommitHorizontal size={18}/><h2>{ui('updater.commits')}</h2><span className="count-badge">{history?.total ?? '—'}</span></div>
        <div className="branch-summary"><GitBranch size={16}/><span>{data.branch}</span></div>
      </div>
        {loading ? <Loading/> : history?.entries.length ? <div className="commit-list">{history.entries.map(commit => <article className="commit-row" key={commit.sha}>
          <GitCommitHorizontal className="commit-node" size={18}/><div className="commit-detail"><div className="commit-subject">{commit.message.split('\n')[0]}{commit.sha === local && <span className="commit-ref">{ui('updater.localHead')}</span>}{commit.sha === upstream && <span className="commit-ref upstream">{ui('updater.upstreamHead')}</span>}</div>
          {commit.message.includes('\n') && <details><summary>{ui('updater.expandDetails')}</summary><pre>{commit.message.slice(commit.message.indexOf('\n')).trim()}</pre></details>}
          <div className="commit-meta"><code title={commit.sha}>{commit.sha.slice(0, 10)}</code><span>{commit.author}</span><time dateTime={commit.date}>{new Date(commit.date).toLocaleString(localeForLanguage(language))}</time></div></div>
        </article>)}</div> : <Empty title={ui('updater.noCommits')}/>}
        <div className="commit-pagination"><span>{history?.total ? `${offset + 1}–${Math.min(offset + 50, history.total)} / ${history.total}` : '0'}</span><button className="button" disabled={loading || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 50))}>{ui('common.previous')}</button><button className="button" disabled={loading || !history?.hasMore} onClick={() => setOffset(value => value + 50)}>{ui('common.next')}</button></div>
      </section>}
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
    </>}
  </>
}

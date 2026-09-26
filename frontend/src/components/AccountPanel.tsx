import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { Parameters } from '../api/generated'
import type { AccountStatus } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { FieldInput } from './FieldInput'
import { Modal } from './ui'
import { accountText } from './accountText'

export function AccountPanel({instance}: {instance: string}) {
  const {language, notify, ui} = useApp()
  const text = accountText[language]
  const connection = useConnection()
  const [status, setStatus] = useState<AccountStatus>()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [label, setLabel] = useState('')
  const [pending, setPending] = useState<{action: Parameters['accounts.manage']['action']; title: string; extra: Partial<Parameters['accounts.manage']>}>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const epoch = useRef(0)
  const passwordInput = useRef<HTMLInputElement>(null)
  useEffect(() => {
    // 原生 dialog 打开后再聚焦，避免 showModal 将焦点重置到关闭按钮。
    if (!pending) return
    const frame = requestAnimationFrame(() => passwordInput.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [pending])
  const hide = () => {
    setStatus(value => value ? {...value, profiles: undefined, selected: undefined} : value)
    setPassword(''); setConfirm(''); setNewPassword(''); setLabel(''); setPending(undefined)
  }
  useEffect(() => {
    const current = ++epoch.current
    setStatus(undefined); setPassword(''); setConfirm(''); setNewPassword(''); setLabel(''); setPending(undefined); setError(''); setBusy(false)
    if (connection === 'ready') void api.request('accounts.status', {instance}).then(value => {
      if (epoch.current === current) setStatus(value)
    }).catch(error => { if (epoch.current === current) setError((error as Error).message) })
    return () => { epoch.current++ }
  }, [instance, connection])
  useEffect(() => {
    const hideOnLeave = () => { if (document.hidden) hide() }
    document.addEventListener('visibilitychange', hideOnLeave)
    const timer = status?.profiles ? window.setTimeout(hide, 60_000) : undefined
    return () => { document.removeEventListener('visibilitychange', hideOnLeave); window.clearTimeout(timer) }
  }, [status?.profiles])
  const run = async (action: Parameters['accounts.manage']['action'], extra: Partial<Parameters['accounts.manage']> = {}) => {
    if ((action === 'create' && password !== confirm) || (action === 'password' && newPassword !== confirm)) {
      setError(text.mismatch); return
    }
    const current = epoch.current
    setBusy(true); setError('')
    const params = {instance, action, password, new_password: action === 'password' ? newPassword : '', ...extra}
    hide()
    try {
      const result = await api.request('accounts.manage', params)
      if (epoch.current === current) { setStatus(result); if (action !== 'list') notify(text.done) }
    } catch (error) {
      if (epoch.current === current) {
        setError((error as Error).message)
        if (error instanceof ApiError && error.code === 'VAULT_DESTROYED') {
          const result = await api.request('accounts.status', {instance}).catch(() => undefined)
          if (result && epoch.current === current) setStatus(result)
        }
      }
    }
    finally { if (epoch.current === current) setBusy(false) }
  }
  const ask = (action: Parameters['accounts.manage']['action'], title: string, extra: Partial<Parameters['accounts.manage']> = {}) => {
    setPassword(''); setConfirm(''); setNewPassword(''); setLabel(''); setError('')
    setPending({action, title, extra})
  }
  const cancel = () => { setPassword(''); setConfirm(''); setNewPassword(''); setLabel(''); setPending(undefined) }
  const disabled = busy || connection !== 'ready' || !status
  const canSubmit = !disabled && !!password && (!(pending?.action === 'create' || pending?.action === 'password') || !!confirm) && (pending?.action !== 'password' || !!newPassword)
  return <section className="panel config-group" aria-label={text.title} data-testid="account-panel">
    <div className="panel-heading"><div><span className="group-indicator"/><h2>{text.title}</h2></div></div>
    <div className="field-row"><div className="field-label"><p>{text.help}</p><p>{text.security}</p></div></div>
    {error && <p className="field-row" role="alert">{error}</p>}
    {status?.destroyed && <p className="field-row" role="alert">{text.destroyed}</p>}
    {status && <>
      {status.initialized && <div className="field-row"><span>{status.unlocked ? text.unlocked : text.locked} · {status.local_bound ? text.localBound : status.tpm_bound ? text.bound : text.unbound}</span></div>}
      {!status.initialized ? <div className="field-row"><button className="button primary" disabled={disabled} onClick={() => ask('create', text.create)}>{text.create}</button></div> : <>
        <div className="field-row"><div className="field-label"><span className="field-name">{text.enable}</span><p>{text.enabledHelp}</p></div><div className="field-control"><FieldInput id="account-enabled" label={text.enable} value={status.enabled} disabled={disabled} onChange={value => ask('enable', text.enable, {enabled: !!value})}/></div></div>
        {!status.local_bound && (status.tpm_available || status.tpm_bound) && <div className="field-row"><div className="field-label"><p>{text.tpmHelp}</p></div><div className="field-control"><button className="button" disabled={disabled} onClick={() => ask(status.tpm_bound ? 'unbind_tpm' : 'bind_tpm', status.tpm_bound ? text.unbind : text.tpm)}>{status.tpm_bound ? text.unbind : text.tpm}</button></div></div>}
        {!status.tpm_bound && (!status.tpm_available || status.local_bound) && <div className="field-row"><div className="field-label"><span className="field-name">{text.localWarning}</span><p>{text.localHelp}</p></div><div className="field-control"><button className="button" disabled={disabled} onClick={() => ask(status.local_bound ? 'unbind_local' : 'bind_local', status.local_bound ? text.unbindLocal : text.local)}>{status.local_bound ? text.unbindLocal : text.local}</button></div></div>}
        <div className="field-row" style={{display: 'flex', flexWrap: 'wrap', gap: 8}}>
          <button className="button" disabled={disabled} onClick={() => ask('capture', text.capture)}>{text.capture}</button>
          <button className="button" disabled={disabled} onClick={() => ask('list', text.list)}>{text.list}</button>
          <button className="button" disabled={disabled} onClick={() => ask('unlock', text.unlock)}>{text.unlock}</button>
          <button className="button" disabled={disabled} onClick={() => void run('lock')}>{text.lock}</button>
          <button className="button" disabled={disabled} onClick={() => ask('password', text.change)}>{text.change}</button>
        </div>
        <div className="field-row"><p>{text.hidden}</p></div>
        {status.profiles && <>
          {!status.profiles.length && <div className="field-row"><p>{text.empty}</p></div>}
          {status.profiles.map(profile => <div className="field-row" key={profile.id}>
            <div className="field-label"><span className="field-name">{profile.label}{status.selected === profile.id && ` · ${text.selected}`}</span>{profile.users.map(user => <p key={user.uid}>{user.name} · UID {user.uid}</p>)}</div>
            <div className="field-control" style={{display: 'flex', flexWrap: 'wrap', gap: 8}}>
              <button className="button primary" disabled={disabled} onClick={() => ask('select', text.switch, {profile: profile.id})}>{text.switch}</button>
              <button className="button" disabled={disabled} onClick={() => ask('delete', text.delete, {profile: profile.id})}>{text.delete}</button>
            </div>
          </div>)}
          <div className="field-row"><button className="button" onClick={hide}>{text.hide}</button></div>
        </>}
      </>}
    </>}
    {pending && <Modal title={pending.title} onClose={cancel}>
      <form className="form-stack" onSubmit={event => { event.preventDefault(); if (canSubmit) void run(pending.action, {...pending.extra, ...(pending.action === 'capture' ? {label} : {})}) }}>
        <label htmlFor="account-password">{text.password}<input ref={passwordInput} id="account-password" type="password" autoComplete="new-password" maxLength={256} value={password} onChange={event => setPassword(event.target.value)} /></label>
        {pending.action === 'password' && <label htmlFor="account-new-password">{text.newPassword}<input id="account-new-password" type="password" autoComplete="new-password" maxLength={256} value={newPassword} onChange={event => setNewPassword(event.target.value)} /></label>}
        {(pending.action === 'create' || pending.action === 'password') && <label htmlFor="account-confirm">{text.confirm}<input id="account-confirm" type="password" autoComplete="new-password" maxLength={256} value={confirm} onChange={event => setConfirm(event.target.value)} /></label>}
        {pending.action === 'capture' && <label htmlFor="account-label">{text.label}<input id="account-label" autoComplete="off" maxLength={64} value={label} onChange={event => setLabel(event.target.value)} /></label>}
        {(pending.action === 'bind_tpm' || pending.action === 'unbind_tpm') && <p>{text.tpmHelp}</p>}
        {(pending.action === 'bind_local' || pending.action === 'unbind_local') && <div><strong>{text.localWarning}</strong><p>{text.localHelp}</p></div>}
        {error && <p role="alert">{error}</p>}
        <div style={{display: 'flex', justifyContent: 'flex-end', gap: 8}}>
          <button type="button" className="button secondary" onClick={cancel}>{ui('common.cancel')}</button>
          <button type="submit" className="button primary" disabled={!canSubmit}>{ui('common.confirm')}</button>
        </div>
      </form>
    </Modal>}
  </section>
}

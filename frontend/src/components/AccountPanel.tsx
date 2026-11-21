/**
 * @fileoverview 账号管理与密码设置面板组件。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { Parameters } from '../api/generated'
import { useApp, useConnection } from '../app/context'
import { usePageRead } from '../app/usePageRead'
import { FieldInput } from './FieldInput'
import { ErrorBox, Modal, Panel, PanelHeading } from './ui'
import { LoadBoundary } from './ui/load-boundary'
import { Input } from './ui/input'
import { accountText } from './accountText'

/**
 * 账号保险库面板：展示保险库状态并管理初始化、解锁/锁定、TPM 与本地绑定、档案切换与删除。
 * 敏感操作先经 Modal 二次确认；epoch 计数器丢弃实例/连接切换后迟到的旧回包；
 * 保险库被销毁（VAULT_DESTROYED）时自动重拉状态刷新界面。
 *
 * @param instance 目标实例 ID；实例或连接变化时重新拉取状态。
 */
export function AccountPanel({instance}: {instance: string}) {
  const {language, notify, ui} = useApp()
  const text = accountText[language]
  const connection = useConnection()
  const loadStatus = useCallback(() => api.request('accounts.status', {instance}), [instance])
  const read = usePageRead(JSON.stringify([instance, connection]), connection === 'ready', loadStatus)
  const {data: status, setData: setStatus} = read
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [label, setLabel] = useState('')
  const [pending, setPending] = useState<{action: Parameters['accounts.manage']['action']; title: string; extra: Partial<Parameters['accounts.manage']>}>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const epoch = useRef(0)
  const privacyEpoch = useRef(0)
  const passwordInput = useRef<HTMLInputElement>(null)
  useEffect(() => {
    // 原生 dialog 打开后再聚焦，避免 showModal 将焦点重置到关闭按钮。
    if (!pending) return
    const frame = requestAnimationFrame(() => passwordInput.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [pending])
  const clearFields = useCallback(() => { setPassword(''); setConfirm(''); setNewPassword(''); setLabel(''); setPending(undefined) }, [])
  const hasVisibleProfiles = status?.profiles !== undefined || status?.selected !== undefined
  const hide = useCallback(() => {
    privacyEpoch.current++
    if (hasVisibleProfiles) setStatus(value => value ? {...value, profiles: undefined, selected: undefined} : value)
    clearFields()
  }, [hasVisibleProfiles, setStatus, clearFields])
  useEffect(() => {
    epoch.current++
    clearFields(); setError(''); setBusy(false)
    return () => { epoch.current++ }
  }, [instance, connection, clearFields])
  useEffect(() => {
    const hideOnLeave = () => { if (document.hidden) hide() }
    document.addEventListener('visibilitychange', hideOnLeave)
    const timer = status?.profiles ? window.setTimeout(hide, 60_000) : undefined
    return () => { document.removeEventListener('visibilitychange', hideOnLeave); window.clearTimeout(timer) }
  }, [status?.profiles, hide])
  const run = async (action: Parameters['accounts.manage']['action'], extra: Partial<Parameters['accounts.manage']> = {}) => {
    if ((action === 'create' && password !== confirm) || (action === 'password' && newPassword !== confirm)) {
      setError(text.mismatch); return
    }
    const current = epoch.current
    setBusy(true); setError('')
    const params = {instance, action, password, new_password: action === 'password' ? newPassword : '', ...extra}
    read.invalidate()
    hide()
    const privacy = privacyEpoch.current
    try {
      const result = await api.request('accounts.manage', params)
      if (epoch.current === current) {
        const visible = privacy === privacyEpoch.current && !document.hidden
        setStatus(visible ? result : {...result, profiles: undefined, selected: undefined})
        if (action !== 'list') notify(text.done)
      }
    } catch (error) {
      if (epoch.current === current) {
        setError((error as Error).message)
        if (error instanceof ApiError && error.code === 'VAULT_DESTROYED') {
          await read.reloadAndWait().catch(() => undefined)
        }
      }
    }
    finally { if (epoch.current === current) setBusy(false) }
  }
  const ask = (action: Parameters['accounts.manage']['action'], title: string, extra: Partial<Parameters['accounts.manage']> = {}) => {
    clearFields(); setError('')
    setPending({action, title, extra})
  }
  const cancel = () => clearFields()
  const disabled = busy || connection !== 'ready' || !status
  const canSubmit = !disabled && !!password && (!(pending?.action === 'create' || pending?.action === 'password') || !!confirm) && (pending?.action !== 'password' || !!newPassword)
  return <Panel compact aria-label={text.title} data-testid="account-panel">
    <PanelHeading title={text.title} icon={<span className="group-indicator"/>}/>
    <div className="field-row"><div className="field-label"><p>{text.help}</p><p>{text.security}</p></div></div>
    {error && <ErrorBox message={error}/>}
    {status?.destroyed && <p className="field-row" role="alert">{text.destroyed}</p>}
    <LoadBoundary ready={read.ready} error={read.error} retry={read.reload}>
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
    </LoadBoundary>
    {pending && <Modal title={pending.title} onClose={cancel}>
      <form className="form-stack" onSubmit={event => { event.preventDefault(); if (canSubmit) void run(pending.action, {...pending.extra, ...(pending.action === 'capture' ? {label} : {})}) }}>
        <label htmlFor="account-password">{text.password}<Input ref={passwordInput} id="account-password" type="password" autoComplete="new-password" maxLength={256} value={password} onChange={event => setPassword(event.target.value)}/></label>
        {pending.action === 'password' && <label htmlFor="account-new-password">{text.newPassword}<Input id="account-new-password" type="password" autoComplete="new-password" maxLength={256} value={newPassword} onChange={event => setNewPassword(event.target.value)}/></label>}
        {(pending.action === 'create' || pending.action === 'password') && <label htmlFor="account-confirm">{text.confirm}<Input id="account-confirm" type="password" autoComplete="new-password" maxLength={256} value={confirm} onChange={event => setConfirm(event.target.value)}/></label>}
        {pending.action === 'capture' && <label htmlFor="account-label">{text.label}<Input id="account-label" autoComplete="off" maxLength={64} value={label} onChange={event => setLabel(event.target.value)}/></label>}
        {(pending.action === 'bind_tpm' || pending.action === 'unbind_tpm') && <p>{text.tpmHelp}</p>}
        {(pending.action === 'bind_local' || pending.action === 'unbind_local') && <div><strong>{text.localWarning}</strong><p>{text.localHelp}</p></div>}
        {error && <p role="alert">{error}</p>}
        <div style={{display: 'flex', justifyContent: 'flex-end', gap: 8}}>
          <button type="button" className="button secondary" onClick={cancel}>{ui('common.cancel')}</button>
          <button type="submit" className="button primary" disabled={!canSubmit}>{ui('common.confirm')}</button>
        </div>
      </form>
    </Modal>}
  </Panel>
}

/**
 * @fileoverview 启动器卡片：展示启动器连接状态，并切换 Windows 开机自启动。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useApp, useConnection } from '../app/context'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'
import { Field, FieldContent, FieldDescription, FieldLabel } from '../pages/settings-ui/field'
import { Switch } from '../pages/settings-ui/switch'
import { api, ApiError } from '../api/client'
import type { LauncherStatus } from '../api/types'

/** 状态行取值：面板状态机。 */
export type Phase = 'loading' | 'remote' | 'unsupported' | 'disconnected' | 'ready' | 'setting' | 'failed'

/** 状态行文案：状态机 + 后端字段 → 界面用语。 */
export function launcherStatusText(phase: Phase, state: {enabled: boolean; pending: boolean; detail: string}, t: (key: string) => string) {
  if (phase === 'loading') return t('Gui.Launcher.Loading')
  if (phase === 'remote') return t('Gui.Launcher.RemoteUnavailable')
  if (phase === 'unsupported') return t('Gui.Launcher.Unsupported')
  if (phase === 'disconnected') return t('Gui.Launcher.Disconnected')
  if (phase === 'setting') return t('Gui.Launcher.Setting')
  if (phase === 'failed') return `${t('Gui.Launcher.Failed')}：${state.detail}`
  const flag = state.pending ? t('Gui.Launcher.Loading') : state.enabled ? t('Gui.Launcher.Enabled') : t('Gui.Launcher.Disabled')
  return `${t('Gui.Launcher.Connected')} · ${flag}`
}

/**
 * 启动器卡片：连接就绪后读取 launcher.status 并监听 launcher 事件，驱动自启开关的状态机。
 *
 * 自启切换是乐观更新：先翻开关进入 setting，等后端命令回执（pending/failed/expired）落定；
 * 经远程隧道拿不到启动器（LOCAL_ONLY）时停在 remote 态。
 */
export function LauncherCard() {
  const {t} = useApp()
  const connection = useConnection()
  const command = useRef<string | undefined>(undefined)
  const [phase, setPhase] = useState<Phase>('loading')
  const [enabled, setEnabled] = useState(false)
  // 已连上启动器但还没拿到自启状态：状态行显示「已连接 · 正在读取」。
  const [pending, setPending] = useState(false)
  const [detail, setDetail] = useState('')
  const busy = useRef(false)

  const applyState = useCallback((data: LauncherStatus) => {
    if (!data.connected) { command.current = undefined; setPhase('disconnected'); return }
    if (!data.autostart.supported) { setPhase('unsupported'); return }
    const current = command.current ? data.commands.find(item => item.id === command.current) : undefined
    if (current?.status === 'pending') { setPhase('setting'); return }
    command.current = undefined
    setEnabled(data.autostart.enabled === true)
    setPending(data.autostart.enabled === null)
    if (current?.status === 'failed' || current?.status === 'expired') {
      setDetail(current.error?.message ?? current.status)
      setPhase('failed')
    } else { setPhase('ready') }
  }, [])

  const read = useCallback(async () => {
    try { applyState(await api.request('launcher.status', {})) }
    catch (error) {
      if (error instanceof ApiError && error.code === 'LOCAL_ONLY') { setPhase('remote'); return }
      setDetail(error instanceof Error ? error.message : String(error))
      setPhase('failed')
    }
  }, [applyState])

  const toggle = useCallback(async () => {
    if (busy.current || command.current) return
    busy.current = true
    const target = !enabled
    setEnabled(target); setPhase('setting')
    try {
      const result = await api.request('launcher.autostart.set', {enabled: target})
      command.current = result.commandId
      await read()
    } catch (error) {
      setEnabled(!target)
      setDetail(error instanceof Error ? error.message : String(error))
      setPhase('failed')
    } finally { busy.current = false }
  }, [enabled, read])

  useEffect(() => {
    if (connection === 'ready') void read()
    else { command.current = undefined; setPhase('loading') }
  }, [connection, read])
  useEffect(() => api.onEvent(event => {
    if (event.topic === 'launcher') applyState(event.data as LauncherStatus)
  }), [applyState])

  const status = launcherStatusText(phase, {enabled, pending, detail}, t)

  return (
    <Card>
      <CardHeader>
        <CardTitle role="heading" aria-level={2}>{t('Gui.Launcher.StartupTitle')}</CardTitle>
      </CardHeader>
      <CardContent>
        <Field orientation="horizontal" data-disabled={phase !== 'ready' || undefined}>
          <FieldContent>
            <FieldLabel htmlFor="launcher-autostart">{t('Gui.Launcher.AutoStart')}</FieldLabel>
            <FieldDescription id="launcher-autostart-description">{t('Gui.Launcher.AutoStartHelp')}</FieldDescription>
            <p role={phase === 'failed' ? 'alert' : 'status'}>{status}</p>
          </FieldContent>
          <Switch id="launcher-autostart" checked={enabled} disabled={phase !== 'ready'}
            aria-label={t('Gui.Launcher.AutoStart')} aria-describedby="launcher-autostart-description"
            onCheckedChange={() => { void toggle() }}/>
        </Field>
      </CardContent>
    </Card>
  )
}

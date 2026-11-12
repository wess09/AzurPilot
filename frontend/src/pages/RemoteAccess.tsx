/**
 * @fileoverview 远程访问隧道状态与 WebUI 部署设置页面。
 *
 * 版式：顶部一张远程访问地址卡（状态胶囊 + 地址 + 密码提示），配对是独立的兄弟卡片，
 * 不再嵌套在地址卡里（拆掉「卡中卡」），下面是部署分组。
 */

import { useRef, useState } from 'react'
import { AlertCircle, Check, Copy } from 'lucide-react'
import { useApp } from '../app/context'
import { Alert, AlertDescription } from '../components/ui/alert'
import { Button } from '../components/ui/button'
import { DeployGroups } from '../components/DeployGroups'
import { useDeploySettings } from '../app/useDeploySettings'
import { remoteStatus } from '../app/remoteStatus'
import { REMOTE_ACCESS_GROUPS } from '../app/settingsGroups'
import { Spinner } from './settings-ui/spinner'
import {PairingPanel} from '../remote/PairingPanel'

/** 远程访问页：顶部是当前可直接打开的地址与密码提示，下面是配对卡与远程访问/WebUI 设置。 */
export function RemoteAccess() {
  const {ui} = useApp()
  const {data, error, edits, queue} = useDeploySettings(true)
  const [copied, setCopied] = useState(false)
  const addressRef = useRef<HTMLElement>(null)

  const status = remoteStatus(data?.remote?.state, data?.remote?.enabled ?? false)
  const address = data?.remote?.address ?? ''
  const stateLabel = {
    disabled: ui('remote.stateDisabled'),
    starting: ui('remote.stateStarting'),
    ready: ui('remote.stateReady'),
    failed: ui('remote.stateFailed'),
  }[status]

  async function copy() {
    try {
      await navigator.clipboard.writeText(address)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // 局域网 http 等非安全上下文没有剪贴板权限，退化成选中地址让用户手动复制。
      const node = addressRef.current
      if (!node) return
      const range = document.createRange()
      range.selectNodeContents(node)
      const selection = window.getSelection()
      selection?.removeAllRanges()
      selection?.addRange(range)
    }
  }

  return <>
    <h1 className="legacy-sr-title">{ui('nav.remote')}</h1>
    <div className="settings-page">
      {error && <Alert variant="destructive"><AlertCircle/><AlertDescription>{error}</AlertDescription></Alert>}
      {edits.storageError && <Alert variant="destructive"><AlertCircle/><AlertDescription>{edits.storageError}</AlertDescription></Alert>}
      <section className="panel config-group remote-address-card">
        <div className="panel-heading">
          <div>
            <h2 role="heading" aria-level={2}>{ui('remote.title')}</h2>
          </div>
          {/* 状态指示用浅色胶囊 + 圆点：与可点击的实底按钮区分开 */}
          <span className={`remote-badge remote-badge-${status}`}><span className="tiny-dot"/>{stateLabel}</span>
        </div>
        {address ? <>
          <div className="remote-address">
            <code ref={addressRef}>{address}</code>
            <Button type="button" variant="outline" size="sm" aria-label={ui('remote.copy')} onClick={copy}>
              {copied ? <Check size={16}/> : <Copy size={16}/>}
              {copied ? ui('remote.copied') : ui('remote.copy')}
            </Button>
          </div>
          {/* 密码提示紧跟地址：它说明的就是这个地址的使用条件 */}
          <p className="remote-hint">{ui('remote.passwordHint')}</p>
        </> : null}
        {!address && status === 'disabled' && <p className="panel-note">{ui('remote.disabledHint')}</p>}
        {data?.remote?.error && <p className="panel-note">{data.remote.error}</p>}
      </section>
      <PairingPanel ready={!!address && data?.remote?.state === 'cloudflare_ready'}/>
      {!data ? (
        <span role="status" className="remote-loading">
          <Spinner aria-hidden="true"/>{ui('common.loading')}
        </span>
      ) : (
        <DeployGroups data={data} only={REMOTE_ACCESS_GROUPS} edits={edits} queue={queue} />
      )}
    </div>
  </>
}

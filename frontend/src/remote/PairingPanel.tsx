/**
 * @fileoverview AP 配对入口：标准二维码和六码共用服务器的一次性配对记录。
 *
 * 二维码卡片四周保留 32px 静区（QR 规范的 Quiet Zone ≥ 4X），避免周围图形干扰扫码识别。
 */
import { useEffect, useState } from 'react'
import {
  Check,
  CheckCircle2,
  Clock,
  Copy,
  QrCode,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  Trash2,
} from 'lucide-react'
import { PairingQr, pairingQrPayload } from './PairingQr'
import { PairingScanGuide } from './PairingScanGuide'
import { api } from '../api/client'
import type { RemoteClient, RemotePairing } from '../api/types'
import { useApp } from '../app/context'
import { pairCopy } from './i18n'
import './pairing.css'

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 忽略剪贴板权限异常并尝试降级。
  }
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    const successful = document.execCommand('copy')
    document.body.removeChild(textarea)
    return successful
  } catch {
    return false
  }
}

/**
 * 远程配对面板：生成二维码与六位配对码，等待手机端认领。
 *
 * pending 期间每 2 秒轮询 remote.pair.status，`claimed`（配对成功）或过期后结束等待；
 * 重新生成前先撤销上一次配对的客户端，失败也不阻断，旧凭据本就可能已失效。
 */
export function PairingPanel({ ready }: { ready: boolean }) {
  const { language } = useApp()
  const copy = pairCopy[language]
  const [pairing, setPairing] = useState<RemotePairing>()
  const [state, setState] = useState('')
  const [remaining, setRemaining] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [copiedCode, setCopiedCode] = useState(false)
  const [copiedLink, setCopiedLink] = useState(false)
  const [clients, setClients] = useState<RemoteClient[]>([])

  useEffect(() => {
    let active = true
    if (ready) {
      void api
        .request('remote.clients', {})
        .then((items) => {
          if (active) setClients(items)
        })
        .catch(() => {})
    }
    return () => {
      active = false
    }
  }, [ready])

  // 1 秒本地倒计时。
  useEffect(() => {
    if (!pairing || state !== 'pending') return
    const interval = setInterval(() => {
      const left = Math.max(0, pairing.expires_at - Math.floor(Date.now() / 1000))
      setRemaining(left)
      if (left <= 0) {
        setState('expired')
      }
    }, 1000)
    return () => clearInterval(interval)
  }, [pairing, state])

  // 2 秒向服务端轮询配对状态。
  useEffect(() => {
    if (!pairing || state !== 'pending') return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const update = async () => {
      const left = Math.max(0, pairing.expires_at - Math.floor(Date.now() / 1000))
      if (!left) {
        if (active) {
          setError('')
          setState('expired')
        }
        return
      }
      try {
        const result = await api.request('remote.pair.status', { id: pairing.id })
        if (!active) return
        setError('')
        if (result.state !== 'pending') {
          setState(result.state)
          if (result.state === 'claimed') {
            setClients(await api.request('remote.clients', {}))
          }
          return
        }
      } catch (err) {
        if (active) setError((err as Error).message)
      }
      if (active) timer = setTimeout(update, 2000)
    }
    void update()
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [pairing, state])

  async function start() {
    setBusy(true)
    setError('')
    setState('')
    setCopiedCode(false)
    setCopiedLink(false)
    try {
      if (pairing && state !== 'claimed' && pairing.client_id) {
        try {
          await api.request('remote.revoke', { id: pairing.client_id })
        } catch {
          // 忽略失效凭据撤销失败。
        }
      }
      const next = await api.request('remote.pair.create', {})
      setPairing(next)
      setRemaining(Math.max(0, next.expires_at - Math.floor(Date.now() / 1000)))
      setState('pending')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function revoke(id: string) {
    try {
      await api.request('remote.revoke', { id })
      setClients((previous) => previous.filter((item) => item.id !== id))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function handleCopyCode() {
    if (!pairing) return
    const ok = await copyText(pairing.code)
    if (ok) {
      setCopiedCode(true)
      setTimeout(() => setCopiedCode(false), 2000)
    }
  }

  async function handleCopyLink() {
    if (!pairing) return
    try {
      const payload = pairingQrPayload(pairing.particle_secret)
      const ok = await copyText(payload)
      if (ok) {
        setCopiedLink(true)
        setTimeout(() => setCopiedLink(false), 2000)
      }
    } catch {
      // 忽略 payload 格式错误。
    }
  }

  return (
    <section className="panel config-group remote-pairing">
      <div className="panel-heading pairing-header">
        <div className="pairing-header-left">
          <QrCode size={18} className="pairing-header-icon" />
          <h2>{copy.title}</h2>
        </div>
        <button
          type="button"
          className={pairing ? 'button secondary pairing-action-trigger' : 'button primary pairing-action-trigger'}
          disabled={!ready || busy}
          onClick={() => void start()}
        >
            {busy ? (
              copy.busy
            ) : pairing ? (
              <>
                <RefreshCw size={14} className={busy ? 'spin' : ''} />
                <span>{copy.refresh}</span>
              </>
            ) : (
              copy.start
            )}
          </button>
      </div>

      {!ready && (
        <div className="pairing-unready-notice">
          <Clock size={16} />
          <p>{copy.ready}</p>
        </div>
      )}

      {error && <p className="pairing-error-text" role="alert">{error}</p>}

      {/* 空态引导收敛为标题下的一行副标题：入口统一到右上角「开始配对」，不再放第二个主按钮 */}
      {ready && !pairing && <p className="pairing-subtitle">{copy.hint}</p>}

      {pairing && (
        <div className="pairing-session" role="status" aria-live="polite">
          {state === 'pending' && (
            <div className="pairing-stage">
              {/* 大号纯白二维码卡片：四向严格满足 32px 物理安全间距 */}
              <div className="pairing-qr-column">
                <div className="pairing-qr-wrapper">
                  <PairingQr secret={pairing.particle_secret} label={copy.qr} />
                </div>
              </div>

              {/* 右侧（桌面端并排，移动端自适应折行）配对指引与操作区 */}
              <div className="pairing-info-column">
                <div className="pairing-guide-block">
                  <h3 className="pairing-guide-title">{copy.hint}</h3>
                </div>

                <div className="pairing-code-wrapper">
                  <button
                    type="button"
                    className="pairing-code-badge"
                    onClick={() => void handleCopyCode()}
                    title={copy.copyCode}
                    aria-label={pairing.code}
                  >
                    <code className="pairing-code">
                      {pairing.code.slice(0, 3)} {pairing.code.slice(3)}
                    </code>
                    <span className="pairing-code-copy-icon">
                      {copiedCode ? <Check size={18} /> : <Copy size={18} />}
                    </span>
                  </button>
                </div>

                <div className="pairing-actions">
                  <button
                    type="button"
                    className="button secondary pairing-pill-btn"
                    onClick={() => void handleCopyCode()}
                  >
                    {copiedCode ? <Check size={14} /> : <Copy size={14} />}
                    <span>{copiedCode ? copy.copiedCode : copy.copyCode}</span>
                  </button>
                  <button
                    type="button"
                    className="button secondary pairing-pill-btn"
                    onClick={() => void handleCopyLink()}
                  >
                    {copiedLink ? <Check size={14} /> : <Copy size={14} />}
                    <span>{copiedLink ? copy.copiedPayload : copy.copyPayload}</span>
                  </button>
                </div>

                <div className="pairing-meta-info">
                  <div className="pairing-countdown-line">
                    <Clock size={14} className="countdown-icon" />
                    <span>
                      {copy.waiting} · <strong>{remaining}</strong> {copy.remaining}
                    </span>
                  </div>
                  <div className="pairing-security-line">
                    <ShieldCheck size={13} />
                    <span>{copy.singleUseHint}</span>
                  </div>
                </div>
              </div>
              <PairingScanGuide label={copy.scanGuide} />
            </div>
          )}

          {state === 'claimed' && (
            <div className="pairing-status-card pairing-claimed-card">
              <CheckCircle2 size={44} className="pairing-claimed-icon" />
              <h3>{copy.connected}</h3>
              <p className="muted">{copy.connectedHint}</p>
            </div>
          )}

          {state === 'expired' && (
            <div className="pairing-status-card pairing-expired-card">
              <Clock size={44} className="pairing-expired-icon" />
              <h3>{copy.expired}</h3>
              <p className="muted">{copy.singleUseHint}</p>
              <button
                type="button"
                className="button primary pairing-pill-btn"
                onClick={() => void start()}
                disabled={busy}
              >
                <RefreshCw size={14} />
                <span>{copy.regenerate}</span>
              </button>
            </div>
          )}
        </div>
      )}

      <div className="pairing-clients-section">
        <div className="pairing-clients-header">
          <div className="pairing-clients-title">
            <Smartphone size={16} />
            <h3>{copy.devices}</h3>
            {clients.length > 0 && (
              <span className="pairing-count-badge">{clients.length}</span>
            )}
          </div>
        </div>

        {clients.length === 0 ? (
          <div className="pairing-no-clients">
            <p className="muted">{copy.noDevices}</p>
          </div>
        ) : (
          <div className="pairing-clients-list">
            {clients.map((item, index) => (
              <div className="pairing-device-item" key={item.id}>
                <div className="pairing-device-icon-wrap">
                  <Smartphone size={18} />
                </div>
                <div className="pairing-device-details">
                  <div className="pairing-device-title-row">
                    <strong className="pairing-device-name">
                      {copy.deviceClient} #{index + 1}
                    </strong>
                  </div>
                  <div className="pairing-device-meta">
                    <Clock size={12} />
                    <span>
                      {new Date(item.created_at * 1000).toLocaleString(
                        language,
                      )}
                    </span>
                  </div>
                </div>
                {/* 破坏性动作缩成图标按钮：hover 转红，避免像普通次要操作一样被顺手点中 */}
                <div className="pairing-device-action">
                  <button
                    type="button"
                    className="icon-button pairing-revoke-btn"
                    onClick={() => void revoke(item.id)}
                    title={copy.revoke}
                    aria-label={`${copy.revoke} · ${copy.deviceClient} #${index + 1}`}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

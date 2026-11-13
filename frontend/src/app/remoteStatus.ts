/**
 * @fileoverview 远程访问后端连接状态归并与展示模型。
 */

/** 远程访问状态在界面上的四档归并。 */
type RemoteState = 'disabled' | 'starting' | 'ready' | 'failed'

/** 已有可用地址：等待连接、直连、中继、SSH 转发。 */
const READY = new Set(['waiting_peer', 'direct_p2p', 'turn_relay', 'ssh_forward', 'cloudflare_ready'])
/** 还在连信令或重连，地址尚未可用。 */
const STARTING = new Set(['starting', 'signaling', 'reconnecting'])

/**
 * 把后端连接状态串归并成界面展示用的四档。
 *
 * 状态取值见 `module/runtime/remote_access.py` 各 provider 的
 * `get_connection_state()`；未知取值一律按失败处理，避免界面显示成正常。
 */
export function remoteStatus(state: string | undefined, enabled: boolean): RemoteState {
  if (!enabled) return 'disabled'
  if (READY.has(state ?? '')) return 'ready'
  if (STARTING.has(state ?? '')) return 'starting'
  return 'failed'
}

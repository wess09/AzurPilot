/**
 * @fileoverview 即时配置编辑队列，管理乐观更新、防抖提交与服务端回执合并。
 */

import { ApiError } from '../api/client'
import type { Value } from '../api/types'
import { translateCurrentUi } from '../i18n'

export interface Edit {
  /** 字段上显示的草稿原文，可能未通过校验。 */
  value: Value
  /** 实际提交给服务端的值，缺省场景与 value 相同；需要转换的（如字符串数字转数值）由调用方传入。 */
  payload: Value
  /** 单调递增的输入版本号：旧响应只确认与自己相同版本的输入。 */
  sequence: number
  status: 'queued' | 'saving' | 'saved' | 'error'
  error?: string
  /** false 表示永久失败（参数非法等），不自动重试，等用户改值后重新入队。 */
  retryable?: boolean
  /** 服务端确认这次提交的时刻。 */
  readyAt?: number
}

/** 提交成功到显示「已保存」之间的静默期：敲键本身有间隔，太快显示会在打字过程中反复闪。 */
const SAVED_QUIET_MS = 700
/** 「已保存」显示后的最短停留。 */
const SAVED_VISIBLE_MS = 800
/** useSyncExternalStore 的快照：未结算条目与草稿持久化失败的提示文本。 */
export interface EditSnapshot { edits: Record<string, Edit>; storageError: string }
interface Transport {
  ready: () => boolean
  send: (path: string, value: Value) => Promise<unknown>
}

/** 页面之外的字段队列：先保留输入，再提交；旧响应只能确认自己的输入版本。 */
export class EditQueue {
  private state: EditSnapshot = {edits: {}, storageError: ''}
  private listeners = new Set<() => void>()
  private sequence = 0
  private running?: Promise<void>
  private retryTimer?: ReturnType<typeof setTimeout>
  private settleTimer?: ReturnType<typeof setTimeout>
  private retryDelay = 1000

  constructor(private key: string, private transport: Transport, private storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>) {
    try {
      const saved = JSON.parse(storage?.getItem(key) ?? '{}') as Record<string, Edit>
      for (const [path, edit] of Object.entries(saved)) {
        if (!edit || typeof edit.sequence !== 'number' || !('value' in edit)) continue
        // 服务端已明确拒绝、内容又为空的草稿没有可修正的东西，却会把字段永久钉死：
        // 字段本来就是空的，用户再清空也不会触发输入事件，草稿永远换不掉。
        // 丢弃它，字段回到配置里的值；非空的错误原文照旧保留给用户修正。
        if (edit.status === 'error' && !edit.retryable && (edit.value === '' || edit.value === null)) continue
        this.sequence = Math.max(this.sequence, edit.sequence)
        this.state.edits[path] = {...edit, status: edit.status === 'error' && !edit.retryable ? 'error' : 'queued'}
      }
    } catch { this.state.storageError = translateCurrentUi('edit.draftReadError') }
  }

  getSnapshot = () => this.state
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  /** 提交刚成功、还在静默期内：算作未到期。 */
  private idle(edit: Edit) {
    return edit.status === 'saved' && Date.now() - (edit.readyAt ?? 0) < SAVED_QUIET_MS
  }

  /** 按当前条目算出最近一个到期时刻：静默期满并停留够时长后，自动清掉已保存条目。 */
  private schedule() {
    if (this.settleTimer) return
    const now = Date.now()
    let due = Infinity
    for (const edit of Object.values(this.state.edits)) {
      if (edit.status !== 'saved') continue
      const readyAt = edit.readyAt ?? now
      due = Math.min(due, readyAt + (now - readyAt < SAVED_QUIET_MS ? SAVED_QUIET_MS : SAVED_VISIBLE_MS))
    }
    if (due === Infinity) return
    const wait = Math.max(0, due - Date.now())
    this.settleTimer = setTimeout(() => {
      this.settleTimer = undefined
      const edits = {...this.state.edits}
      for (const [path, edit] of Object.entries(edits)) {
        if (edit.status !== 'saved' || this.idle(edit)) continue
        if (Date.now() - (edit.readyAt ?? 0) >= SAVED_QUIET_MS + SAVED_VISIBLE_MS) delete edits[path]
      }
      this.state = {...this.state, edits}
      this.publish()
      this.schedule()
    }, wait)
  }
  private publish() {
    // 仅持久化未确认的输入；每个标签页独立，避免其他页面覆盖本页草稿。
    try {
      const pending = Object.fromEntries(Object.entries(this.state.edits).filter(([, edit]) => edit.status !== 'saved'))
      if (!this.storage) throw new Error()
      if (Object.keys(pending).length) this.storage.setItem(this.key, JSON.stringify(pending))
      else this.storage.removeItem(this.key)
      this.state = {...this.state, storageError: ''}
    } catch { this.state = {...this.state, storageError: translateCurrentUi('edit.draftPersistError')} }
    this.listeners.forEach(listener => listener())
  }

  private replace(path: string, edit: Edit) {
    this.state = {...this.state, edits: {...this.state.edits, [path]: edit}}
    this.publish()
  }

  /** 字段提交成功后收到的服务端配置。 */
  onSaved?: (data: unknown) => void

  /** 记录一次输入并尝试提交：payload 缺省等于 value；传入 error 时以错误态入队、不提交，等用户修正。 */
  change(path: string, value: Value, payload: Value = value, error?: string) {
    this.replace(path, {value, payload, sequence: ++this.sequence, status: error ? 'error' : 'queued', error})
    void this.flush()
  }

  retry = () => {
    clearTimeout(this.retryTimer)
    this.retryTimer = undefined
    for (const [path, edit] of Object.entries(this.state.edits)) {
      if (edit.status === 'error' && edit.retryable) this.replace(path, {...edit, status: 'queued', error: undefined})
    }
    void this.flush()
  }

  /** 运行工具前等候队列排空；格式错误保留在原字段，不允许带旧配置启动。 */
  async settled() {
    await this.flush()
    if (Object.values(this.state.edits).some(edit => edit.status !== 'saved')) {
      throw new Error(translateCurrentUi('edit.unsaved'))
    }
  }

  /** 排空队列；已有排空在进行时返回同一个 Promise，不重复启动。 */
  flush(): Promise<void> {
    if (this.running) return this.running
    this.running = this.drain().finally(() => { this.running = undefined })
    return this.running
  }

  private async drain() {
    while (this.transport.ready()) {
      const next = Object.entries(this.state.edits)
        .filter(([, edit]) => edit.status === 'queued')
        .sort((a, b) => a[1].sequence - b[1].sequence)[0]
      if (!next) return
      const [path, edit] = next
      this.replace(path, {...edit, status: 'saving'})
      try {
        const response = await this.transport.send(path, edit.payload)
        this.retryDelay = 1000
        if (this.state.edits[path]?.sequence === edit.sequence) {
          this.onSaved?.(response)
          this.replace(path, {...edit, status: 'saved', readyAt: Date.now()})
          this.schedule()
        }
      } catch (error) {
        const permanent = error instanceof ApiError && ['INVALID_PARAMS', 'READ_ONLY', 'NOT_FOUND', 'CONFIG_INVALID'].includes(error.code)
        if (this.state.edits[path]?.sequence === edit.sequence) {
          this.replace(path, {...edit, status: 'error', error: (error as Error).message, retryable: !permanent})
        }
        if (!permanent && !this.retryTimer) {
          this.retryTimer = setTimeout(this.retry, this.retryDelay)
          this.retryDelay = Math.min(15000, this.retryDelay * 2)
        }
      }
    }
  }
}

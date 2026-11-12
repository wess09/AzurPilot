/**
 * @fileoverview 存在 localStorage 里的界面偏好：读出、写入并通知订阅者。
 */

/** 造一组「读 / 订阅 / 写」访问器；写入后通知所有订阅者，存储不可用时本次会话内仍生效。 */
export function prefStore<T extends string>(key: string, parse: (raw: string | null) => T) {
  const listeners = new Set<() => void>()
  return {
    read: (): T => {
      try {
        return parse(localStorage.getItem(key))
      } catch {
        return parse(null)
      }
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    write: (value: T) => {
      try {
        localStorage.setItem(key, value)
      } catch { /* 存储不可用时本次会话内仍生效。 */ }
      listeners.forEach(listener => listener())
    },
  }
}

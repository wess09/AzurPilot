/**
 * @fileoverview 资源数值展示域：数值行排版与同步记录时间的过久判定文案。
 * 从 ResourceCards.tsx 原 73-91 行提取，纯搬迁未改动。
 */
/** 资源数值行：数值加可选的小字后缀排版。 */
export function ResourceValue({value, suffix}: {value: string; suffix?: string}) {
  return <div className="resource-value">
    <span className="resource-value-content"><span>{value}</span>{suffix && <small>/ {suffix}</small>}</span>
  </div>
}

// 记录时间：当日给时分秒，跨日给月日与小时；超过一年标记为过久。
const RECORD_STALE_MS = 365 * 24 * 60 * 60 * 1000

/** 同步记录时间文案：当日给时分秒，跨日给月日与小时；无法解析或超一年分别返回空文本与过久标记。 */
export function recordText(value: string | undefined): {text: string; stale: boolean} {
  const at = value ? new Date(value) : null
  if (!at || Number.isNaN(at.getTime())) return {text: '', stale: false}
  if (Date.now() - at.getTime() > RECORD_STALE_MS) return {text: '', stale: true}
  const pad = (count: number) => String(count).padStart(2, '0')
  const now = new Date()
  const sameDay = at.getFullYear() === now.getFullYear() && at.getMonth() === now.getMonth() && at.getDate() === now.getDate()
  const text = sameDay ? `${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}` : `${pad(at.getMonth() + 1)}-${pad(at.getDate())}-${pad(at.getHours())}`
  return {text, stale: false}
}

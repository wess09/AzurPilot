/**
 * 从 SchedulerProgram.tsx 原 57-103 行提取，纯搬迁未改动（仅新增导出）。
 * JSON 编辑域：草稿随外部值重置，失焦时解析；解析失败显示错误并保留输入。
 */
import {useCallback, useEffect, useLayoutEffect, useRef, useState} from 'react'

/** JSON 编辑域：草稿随外部值重置，失焦时解析；解析失败显示错误并保留输入。 */
export function JsonField({label, value, onChange}: {label: string; value: unknown; onChange: (value: unknown) => void}) {
  const serialized = JSON.stringify(value ?? null, null, 2)
  const [draft, setDraft] = useState(serialized)
  const [error, setError] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {setDraft(serialized); setError('')}, [serialized])

  const autoResize = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.max(el.scrollHeight + 4, 72)}px`
  }, [])

  useLayoutEffect(() => {
    const input = textareaRef.current
    if (!input) return
    autoResize()
    let width = input.clientWidth
    let frame = 0
    const observer = new ResizeObserver(() => {
      if (input.clientWidth !== width) {
        width = input.clientWidth
        cancelAnimationFrame(frame)
        frame = requestAnimationFrame(autoResize)
      }
    })
    observer.observe(input)
    return () => {observer.disconnect(); cancelAnimationFrame(frame)}
  }, [draft, autoResize])

  const calculatedRows = Math.min(Math.max((draft.match(/\n/g)?.length ?? 0) + 1, 3), 40)

  return <label onMouseEnter={autoResize}>{label}<textarea
    ref={textareaRef}
    className="program-json"
    rows={calculatedRows}
    value={draft}
    onFocus={autoResize}
    onChange={e => {setDraft(e.target.value); autoResize()}}
    onBlur={() => {
      try {onChange(JSON.parse(draft)); setError('')} catch {setError('请填写有效的 JSON 值')}
    }}
  />{error && <small role="alert">{error}</small>}</label>
}

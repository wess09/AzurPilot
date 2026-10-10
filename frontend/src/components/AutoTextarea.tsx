/**
 * @fileoverview 根据内容自动撑开高度的文本输入框组件。
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react'

export function AutoTextarea({id, value, disabled, onChange, label, invalid}: {
  id: string; value: string; label?: string; invalid?: boolean; disabled?: boolean; onChange: (value: string) => void
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const [draft, setDraft] = useState(value)
  const [editing, setEditing] = useState(false)
  useEffect(() => { if (!editing) setDraft(value) }, [value, editing])

  useLayoutEffect(() => {
    const input = ref.current!
    const resize = () => {
      // 先收起再测量，删除内容时也能缩回一行；scrollHeight 包含自动换行。
      input.style.height = '0px'
      const style = getComputedStyle(input)
      input.style.height = `${input.scrollHeight + parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth)}px`
    }
    resize()
    let width = input.clientWidth
    let frame = 0
    const observer = new ResizeObserver(() => {
      if (input.clientWidth !== width) {
        width = input.clientWidth
        cancelAnimationFrame(frame)
        // 延迟到下一帧写入高度，避免在观察回调中触发浏览器的尺寸反馈循环。
        frame = requestAnimationFrame(resize)
      }
    })
    observer.observe(input)
    return () => {observer.disconnect(); cancelAnimationFrame(frame)}
  }, [draft])

  return (
    <textarea
      aria-label={label}
      aria-invalid={invalid || undefined}
      aria-describedby={invalid ? `${id}-status` : undefined}
      ref={ref}
      id={id}
      value={draft}
      rows={1}
      disabled={disabled}
      spellCheck={false}
      onFocus={() => setEditing(true)}
      onChange={event => setDraft(event.target.value)}
      onBlur={() => {
        setEditing(false)
        if (draft !== value) onChange(draft)
      }}
    />
  )
}

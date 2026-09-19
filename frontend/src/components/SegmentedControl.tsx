import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

import { useApp } from '../app/context'
import { usesMaterial } from '../app/theme'

type Option<T extends string> = {value: T; label: ReactNode}

/** 共用监控页的分段样式，按实际按钮尺寸定位滑块。 */
export function SegmentedControl<T extends string>({label, value, options, onChange, className = ''}: {
  label: string
  value: T
  options: Option<T>[]
  onChange: (value: T) => void
  className?: string
}) {
  const {theme} = useApp()
  const simple = !usesMaterial(theme)
  const ref = useRef<HTMLDivElement>(null)
  const [indicator, setIndicator] = useState({x: 0, y: 0, width: 0, height: 0})
  useLayoutEffect(() => {
    const control = ref.current
    if (!control || simple) return
    const update = () => {
      const active = control.querySelector<HTMLButtonElement>('[aria-selected="true"]')
      if (active) setIndicator({x: active.offsetLeft, y: active.offsetTop, width: active.offsetWidth, height: active.offsetHeight})
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(control)
    control.querySelectorAll('button').forEach(button => observer.observe(button))
    return () => observer.disconnect()
  }, [value, options, simple])
  return <div ref={ref} className={`monitor-segmented ${className}`.trim()} role="tablist" aria-label={label}>
    {/* 测量后才挂载滑块，避免从零尺寸向选中项播放入场过渡。 */}
    {!simple && indicator.width > 0 && <span className="segmented-indicator" aria-hidden="true" style={{transform: `translate3d(${indicator.x}px, ${indicator.y}px, 0)`, width: indicator.width, height: indicator.height}}/>}
    {options.map((option, index) => <button type="button" key={option.value} role="tab" aria-selected={value === option.value} tabIndex={value === option.value ? 0 : -1} onClick={() => onChange(option.value)} onKeyDown={event => {
      const next = event.key === 'ArrowRight' ? (index + 1) % options.length : event.key === 'ArrowLeft' ? (index - 1 + options.length) % options.length : event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : -1
      if (next < 0) return
      event.preventDefault()
      onChange(options[next].value)
      const button = ref.current?.querySelectorAll<HTMLButtonElement>('button')[next]
      button?.focus({preventScroll: true})
      button?.scrollIntoView({block: 'nearest', inline: 'nearest'})
    }}>{option.label}</button>)}
  </div>
}

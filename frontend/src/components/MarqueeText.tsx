/**
 * @fileoverview 溢出文本横向跑马灯动画组件。
 */

import { useEffect, useRef, useState } from 'react'
import { syncMarquee } from '../app/marquee'

/**
 * 单行任务标题：超出容器宽度时从右至左滚动（灯带），放得下则维持原来的省略号截断。
 * className 挂最外层，沿用调用方已有的 flex、省略号等规则。
 */
export function MarqueeText({ text, className }: { text: string; className?: string }) {
  const container = useRef<HTMLSpanElement>(null)
  const copy = useRef<HTMLSpanElement>(null)
  const [scrolling, setScrolling] = useState(false)

  useEffect(() => {
    const measure = () => setScrolling(syncMarquee(container.current, copy.current))
    measure()
    /* 侧栏折叠、窗口缩放都会改容器宽度，只量一次不够。 */
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(measure)
    if (observer && container.current) observer.observe(container.current)
    return () => observer?.disconnect()
  }, [text])

  return (
    <span className={className} ref={container}>
      <span className="marquee-track">
        <span className="marquee-copy" ref={copy}>{text}</span>
        {scrolling && <span className="marquee-copy" aria-hidden="true">{text}</span>}
      </span>
    </span>
  )
}

/**
 * @fileoverview 扫码操作示意图：演示手机取景扫码过程，动画只在图示可见且页面在前台时播放（配对等待卡片内挂载）。
 */

import { useEffect, useRef, useState } from 'react'
import { QrCode } from 'lucide-react'
import './pairing-scan-guide.css'

/** 渲染扫码示意图；label 作为 figure 的无障碍名称。 */
export function PairingScanGuide({ label }: { label: string }) {
  const ref = useRef<HTMLElement>(null)
  const [playing, setPlaying] = useState(false)

  // 动画只在可见时播：IntersectionObserver 管出视口，visibilitychange 管切后台，两处任一失效即暂停。
  useEffect(() => {
    const element = ref.current
    if (!element) return
    let visible = false
    const update = () => setPlaying(visible && !document.hidden)
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      update()
    })
    observer.observe(element)
    document.addEventListener('visibilitychange', update)
    return () => {
      observer.disconnect()
      document.removeEventListener('visibilitychange', update)
    }
  }, [])

  return (
    <figure ref={ref} className="pairing-scan-guide" data-playing={playing} role="img" aria-label={label}>
      {/* 图中只使用二维码图标；真实配对码保持静止，示意成功与实际连接状态无关。 */}
      <svg className="pairing-scan-scene" viewBox="0 0 240 200" aria-hidden="true" focusable="false">
        <ellipse cx="124" cy="183" rx="89" ry="7" fill="currentColor" opacity=".07" />
        <rect className="pairing-scan-source" x="20" y="42" width="116" height="116" rx="12" />
        <QrCode x="42" y="64" width="72" height="72" strokeWidth="1.5" />
        <g className="pairing-scan-phone">
          <rect className="pairing-scan-phone-body" x="111" y="15" width="104" height="168" rx="20" />
          <rect className="pairing-scan-screen" x="117" y="21" width="92" height="156" rx="15" />
          <rect x="145" y="27" width="36" height="5" rx="2.5" fill="currentColor" opacity=".4" />
          <rect className="pairing-scan-viewfinder" x="125" y="52" width="76" height="88" rx="10" />
          <g className="pairing-scan-target">
            <QrCode x="139" y="72" width="48" height="48" strokeWidth="1.5" />
          </g>
          <path className="pairing-scan-corners" d="M136 72v-8h8m38 0h8v8m0 48v8h-8m-38 0h-8v-8" />
          <rect className="pairing-scan-line" x="132" y="67" width="62" height="2" rx="1" />
          <g className="pairing-scan-check">
            <circle cx="163" cy="96" r="19" fill="var(--accent)" />
            <path d="m154 96 6 6 12-13" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </g>
          <rect x="148" y="165" width="30" height="3" rx="1.5" fill="currentColor" opacity=".25" />
        </g>
      </svg>
    </figure>
  )
}

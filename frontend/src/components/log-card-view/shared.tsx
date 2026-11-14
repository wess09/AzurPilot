/**
 * 从 LogCardView.tsx 原 188-214 行提取，纯搬迁未改动。
 * 日志卡片域的共享轻量 helper 与复制按钮。
 */

import {
  useState,
} from 'react'
import {
  Check,
  Copy,
} from 'lucide-react'

function CopyButton({ text, label = '复制' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  function handleCopy(e: React.MouseEvent) {
    e.stopPropagation()
    void navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button className="card-btn-action" onClick={handleCopy} title="复制内容">
      {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
      <span>{copied ? '已复制' : label}</span>
    </button>
  )
}

export { CopyButton }

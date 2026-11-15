/** @fileoverview Markdown 视图的按需加载封装：代码分割引入 katex 与 highlight.js。 */

import { lazy, Suspense } from 'react'
import { useApp } from '../app/context'

const MarkdownView = lazy(() => import('./MarkdownView').then(module => ({default: module.MarkdownView})))

/** Markdown 渲染连同 katex、highlight.js 一起按需加载。 */
export function LazyMarkdown({content, className = ''}: {content: string; className?: string}) {
  const {ui} = useApp()
  return (
    <Suspense fallback={<div role="status" className={className}>{ui('common.loading')}</div>}>
      <MarkdownView content={content} className={className} />
    </Suspense>
  )
}

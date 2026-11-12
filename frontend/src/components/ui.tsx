/**
 * @fileoverview 通用 UI 基础原子组件（按钮、弹窗、加载状态、错误框等）。
 */

import type { ReactNode } from 'react'
import { AlertCircle, LoaderCircle } from 'lucide-react'
import type { Status } from '../api/types'
import { useApp } from '../app/context'
import { Alert, AlertDescription } from './ui/alert'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from './ui/dialog'
import { Empty as EmptyState, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from './ui/empty'

const STATUS_VARIANTS = {
  running: 'default',
  stopped: 'secondary',
  error: 'destructive',
  updating: 'outline',
} as const

/** 实例状态徽章：按 Status 映射颜色与 i18n 文案。 */
export function StatusBadge({status}: {status: Status}) {
  const {ui} = useApp()
  return <Badge variant={STATUS_VARIANTS[status]}>{{running: ui('status.running'), stopped: ui('status.stopped'), error: ui('status.error'), updating: ui('status.updating')}[status]}</Badge>
}

/** 空态占位：图标 + 标题 + 可选描述，统一排版。 */
export function Empty({icon, title, children}: {icon?: ReactNode; title: string; children?: ReactNode}) {
  return <EmptyState>
    <EmptyHeader>
      {icon && <EmptyMedia variant="icon">{icon}</EmptyMedia>}
      <EmptyTitle>{title}</EmptyTitle>
      {children && <EmptyDescription>{children}</EmptyDescription>}
    </EmptyHeader>
  </EmptyState>
}

/** 区域级加载占位：旋转图标 + 「加载中」文案，带 role=status 供读屏识别。 */
export function Loading() {
  const {ui} = useApp()
  return <div data-slot="loading" role="status" className="flex min-h-[230px] items-center justify-center gap-2.5 text-muted-foreground">
    <LoaderCircle className="animate-spin" size={22}/>{ui('common.loading')}
  </div>
}

/** 错误提示框：destructive Alert，可带重试按钮。 */
export function ErrorBox({message, retry}: {message: string; retry?: () => void}) {
  const {ui} = useApp()
  return <Alert variant="destructive">
    <AlertCircle/>
    <AlertDescription>
      <span>{message}</span>
      {retry && <Button variant="outline" size="sm" className="mt-2" onClick={retry}>{ui('common.retry')}</Button>}
    </AlertDescription>
  </Alert>
}

/** 简易弹窗：挂载即打开，点遮罩或 Esc 触发 onClose，关闭由调用方卸载完成。 */
export function Modal({title, children, onClose, className = ''}: {title: string; children: ReactNode; onClose: () => void; className?: string}) {
  return <Dialog open onOpenChange={open => {if (!open) onClose()}}>
    <DialogContent className={className}>
      <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>
      {children}
    </DialogContent>
  </Dialog>
}

/** 页面动作组：控件外面包一层容器，挂载位置由调用方决定。 */
export function ActionGroup({children, className = ''}: {children: ReactNode; className?: string}) {
  return <div className={`flex flex-wrap items-center gap-2.5 ${className}`.trim()}>{children}</div>
}

/** 页头：左侧标题、右侧动作区。 */
export function PageTitle({title, actions, className = ''}: {title: string; actions?: ReactNode; className?: string}) {
  return <div className={`flex items-center justify-between gap-4.5 ${className}`.trim()}>
    <h1 aria-label={title} className="page-title-heading text-3xl font-bold tracking-tight">{title}</h1>
    {actions && <ActionGroup>{actions}</ActionGroup>}
  </div>
}

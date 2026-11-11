/**
 * @fileoverview 通用 UI 基础原子组件（按钮、弹窗、加载状态、错误框等）。
 */

import type { ReactNode } from 'react'
import { AlertCircle, LoaderCircle } from 'lucide-react'
import type { Status } from '../api/types'
import { useApp } from '../app/context'
import { useDevOverride } from '../app/devOverride'
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

export function StatusBadge({status, simulate = false}: {status: Status; simulate?: boolean}) {
  const {ui} = useApp()
  /* 实例列表上的徽章跟随开发者工具的「模拟状态」；控件预览里的徽章不跟随。 */
  const override = useDevOverride().status
  const shown = simulate && override ? override : status
  return <Badge variant={STATUS_VARIANTS[shown]}>{{running: ui('status.running'), stopped: ui('status.stopped'), error: ui('status.error'), updating: ui('status.updating')}[shown]}</Badge>
}

export function Empty({icon, title, children}: {icon?: ReactNode; title: string; children?: ReactNode}) {
  return <EmptyState>
    <EmptyHeader>
      {icon && <EmptyMedia variant="icon">{icon}</EmptyMedia>}
      <EmptyTitle>{title}</EmptyTitle>
      {children && <EmptyDescription>{children}</EmptyDescription>}
    </EmptyHeader>
  </EmptyState>
}

export function Loading() {
  const {ui} = useApp()
  return <div data-slot="loading" role="status" className="flex min-h-[230px] items-center justify-center gap-2.5 text-muted-foreground">
    <LoaderCircle className="animate-spin" size={22}/>{ui('common.loading')}
  </div>
}

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

export function Modal({title, children, onClose, className = ''}: {title: string; children: ReactNode; onClose: () => void; className?: string}) {
  return <Dialog open onOpenChange={open => {if (!open) onClose()}}>
    <DialogContent className={className}>
      <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>
      {children}
    </DialogContent>
  </Dialog>
}

/** 页面动作组：控件外面包一层容器，挂载位置由调用方决定。 */
export function ActionGroup({children}: {children: ReactNode}) {
  return <div className="flex flex-wrap items-center gap-2.5">{children}</div>
}

export function PageTitle({title, actions, className = ''}: {title: string; actions?: ReactNode; className?: string}) {
  return <div className={`flex items-center justify-between gap-4.5 ${className}`.trim()}>
    <h1 aria-label={title} className="text-3xl font-bold tracking-tight">{title}</h1>
    {actions && <ActionGroup>{actions}</ActionGroup>}
  </div>
}

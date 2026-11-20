/** @fileoverview shadcn/ui 表格：原生 table 语义元素加统一分隔线与 hover 底色。 */

import * as React from "react"

import { isLanguage, translateCurrentUi, translateUi } from "../../i18n"
import { cn } from "../../lib/utils"
import "./table.css"

/** Shared horizontal viewport for tables and other wide content. */
function TableViewport({ children, className, scrollLabel }: {children: React.ReactNode; className?: string; scrollLabel?: string}) {
  const containerRef = React.useRef<HTMLDivElement>(null)
  const containerId = React.useId()
  const [scroll, setScroll] = React.useState({ max: 0, left: 0 })
  const [controlLabel, setControlLabel] = React.useState(() => translateCurrentUi("table.horizontalScroll"))
  const updateScroll = React.useCallback(() => {
    const container = containerRef.current
    if (!container) return
    const max = Math.max(0, container.scrollWidth - container.clientWidth)
    const left = Math.max(0, Math.min(max, container.scrollLeft))
    setScroll(previous => previous.max === max && previous.left === left ? previous : { max, left })
  }, [])

  React.useLayoutEffect(() => {
    const container = containerRef.current
    if (!container) return
    updateScroll()
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(updateScroll)
    observer?.observe(container)
    const content = container.firstElementChild
    if (content) observer?.observe(content)
    window.addEventListener("resize", updateScroll)
    return () => {
      observer?.disconnect()
      window.removeEventListener("resize", updateScroll)
    }
  }, [updateScroll])
  // Content can change without changing the table's observed border box.
  React.useLayoutEffect(updateScroll)

  React.useEffect(() => {
    const updateLabel = () => {
      const language = document.documentElement.lang
      if (isLanguage(language)) setControlLabel(translateUi(language, "table.horizontalScroll"))
    }
    updateLabel()
    const observer = new MutationObserver(updateLabel)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] })
    return () => observer.disconnect()
  }, [])

  return (
    <>
      {scroll.max > 0 && <input
        data-slot="table-scroll-control"
        className="table-scroll-control"
        type="range"
        min={0}
        max={scroll.max}
        step="any"
        value={scroll.left}
        aria-label={scrollLabel ? `${scrollLabel} — ${controlLabel}` : controlLabel}
        aria-controls={containerId}
        onChange={event => {
          if (containerRef.current) containerRef.current.scrollLeft = Number(event.currentTarget.value)
          updateScroll()
        }}
      />}
      <div ref={containerRef} id={containerId} onScroll={updateScroll} data-slot="table-container" className={cn("relative w-full overflow-x-auto", className)} role={scrollLabel ? "region" : undefined} aria-label={scrollLabel} tabIndex={scrollLabel ? 0 : undefined}>
        {children}
      </div>
    </>
  )
}

/** 表格：外层容器支持横向滚动。 */
function Table({ className, scrollLabel, ...props }: React.ComponentProps<"table"> & {scrollLabel?: string}) {
  return <TableViewport scrollLabel={scrollLabel}>
    <table data-slot="table" className={cn("w-full caption-bottom text-sm", className)} {...props} />
  </TableViewport>
}

/** 表头容器：底部分隔线。 */
function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("[&_tr]:border-b", className)}
      {...props}
    />
  )
}

/** 表体容器：末行无分隔线。 */
function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  )
}

/** 行：hover 与 selected 状态显示 muted 底色。 */
function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "hover:bg-muted/50 data-[state=selected]:bg-muted border-b transition-colors",
        className
      )}
      {...props}
    />
  )
}

/** 表头单元格。 */
function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "text-foreground h-10 px-2 text-left align-middle font-medium whitespace-nowrap [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
        className
      )}
      {...props}
    />
  )
}

/** 数据单元格。 */
function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "p-2 align-middle whitespace-nowrap [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
        className
      )}
      {...props}
    />
  )
}

export { Table, TableViewport, TableHeader, TableBody, TableHead, TableRow, TableCell }

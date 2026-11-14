"use client"

/** @fileoverview shadcn/ui 表单标签：Radix 封装，随相邻控件禁用态联动。 */

import * as React from "react"
import { cn } from "../../lib/utils"
import { Label as LabelPrimitive } from "radix-ui"

/** 表单标签：所在分组的控件禁用时自动降透明度。 */
function Label({
  className,
  ...props
}: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      data-slot="label"
      className={cn(
        "flex items-center gap-2 text-sm leading-none font-medium select-none group-data-[disabled=true]:pointer-events-none group-data-[disabled=true]:opacity-50 peer-disabled:cursor-not-allowed peer-disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
}

export { Label }

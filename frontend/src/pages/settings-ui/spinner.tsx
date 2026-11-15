/**
 * @fileoverview 设置页加载指示器（旋转 Loader2 图标）。
 */

import { Loader2Icon } from "lucide-react"
import { cn } from "../../lib/utils"

/** 加载指示器：固定 role=status 与 Loading 文案，尺寸由 className 覆盖。 */
function Spinner({ className, ...props }: React.ComponentProps<"svg">) {
  return (
    <Loader2Icon
      role="status"
      aria-label="Loading"
      className={cn("size-4 animate-spin", className)}
      {...props}
    />
  )
}

export { Spinner }

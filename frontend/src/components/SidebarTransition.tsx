/**
 * @fileoverview 侧边栏内容切换过渡动画组件。
 */

import { useMemo, type ReactNode } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { motionReducedActive } from '../app/motionPrefs'

interface SidebarTransitionProps {
  /** 区分视图状态的唯一键，例如 'global' 或 `instance:${instance}` */
  viewKey: string
  /** 切换中的侧边栏内容。 */
  children: ReactNode
}

/**
 * 侧边栏内容切换过渡组件：
 * 基于 motion (Framer Motion) 为侧边栏在「全局主导航」与「实例导航/任务树」之间的切换
 * 提供平滑自然的进入（Enter）、退出（Exit）动效。
 */
export function SidebarTransition({ viewKey, children }: SidebarTransitionProps) {
  const isReduced = motionReducedActive()

  // 动效变体：新内容自左侧滑入，旧内容向右侧滑出并淡出。
  const variants = useMemo(() => {
    if (isReduced) {
      return {
        initial: { opacity: 1 },
        animate: { opacity: 1 },
        exit: { opacity: 1 },
      }
    }

    const shiftX = 12

    return {
      initial: { opacity: 0, x: -shiftX },
      animate: { opacity: 1, x: 0 },
      exit: { opacity: 0, x: shiftX },
    }
  }, [isReduced])

  const transition = useMemo(() => {
    if (isReduced) return { duration: 0 }
    return {
      duration: 0.22,
      ease: [0.16, 1, 0.3, 1] as const, // 与 motion.css 的 --ease-emphasized 同一条曲线
    }
  }, [isReduced])

  return (
    <div className="sidebar-transition-wrap">
      <AnimatePresence mode="wait" initial={true}>
        <motion.div
          key={viewKey}
          className="sidebar-transition-pane"
          initial="initial"
          animate="animate"
          exit="exit"
          variants={variants}
          transition={transition}
          style={{ willChange: 'opacity, transform' }}
        >
          {children}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

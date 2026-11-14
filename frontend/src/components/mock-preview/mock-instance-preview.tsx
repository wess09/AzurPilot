/**
 * 从 MockInstancePreview.tsx 原组件骨架（65-77、106-120、425-427、553-561 行）组装，
 * 各段落正文逐字搬迁至同目录域文件，调用位置与顺序和原文件保持一致。
 * 全真模拟实例预览主组件：组装外壳各区域与材质调节面板，有 document 时经 Portal 挂到 body。
 */
import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { useApp } from '../../app/context'
import { THEME_FAMILY } from '../../app/theme'
import type { RegionId } from '../../app/themeKnobs'
import { useFamilyCustom, useSampleLayers } from '../../app/useMaterialInspector'
import { ThemeWallpaper } from '../ThemeWallpaper'

import { useFocusTrap } from './use-focus-trap'
import { mockSidebar } from './sidebar'
import { mockTopbar } from './topbar'
import { mockOverviewContent } from './overview-content'
import { mockRightRail } from './right-rail'
import { mockSampleModal } from './sample-modal'
import { mockInspector } from './inspector'

type MockInstancePreviewProps = {
  onClose: () => void
  initialRegion?: RegionId
}

/**
 * 材质检视器的全真预览：把一份写死的实例外壳渲染成全屏覆盖层，
 * 供用户在顶栏、侧栏、资源卡、日志等区域上调材质并即时看到效果。
 * 有 document 时经 Portal 挂到 body；焦点圈定在预览层内。
 */
export function MockInstancePreview({onClose, initialRegion}: MockInstancePreviewProps) {
  const overlayRef = useRef<HTMLDivElement>(null)
  useFocusTrap(overlayRef)
  const {ui} = useApp()
  const family = THEME_FAMILY
  const {custom, refresh} = useFamilyCustom(family)
  const {region: activeRegion, showModal, showMenu, select: handleRegionSelect, setShowModal, setShowMenu} = useSampleLayers(initialRegion ?? 'surface')

  const [isRunning, setIsRunning] = useState(true)

  const [isInspectorMinimized, setIsInspectorMinimized] = useState(false)
  const [isDocked, setIsDocked] = useState(true)
  const isDockedActive = isDocked && !isInspectorMinimized
  const overlay = (
    <div ref={overlayRef} role="dialog" aria-modal="true" aria-label={ui('settings.materialLivePreview')} tabIndex={-1} className={`mock-instance-preview-overlay legacy-shell-preview ${isDockedActive ? 'has-docked-inspector' : ''}`}>
      <ThemeWallpaper />
      {/* 全真模拟 AppShell 容器；里面的实例名、资源、任务与日志是写死的样本数据，用来撑起外壳，不随语言切换。 */}
      <div className={`app-shell modern-shell with-rail legacy-shell mock-preview-shell`}>
        {/* 侧栏 (sidebar 区域) */}
        {mockSidebar(ui)}
        {/* 主视图区域 */}
        <div className="main-shell">
          {/* 顶栏 (topbar 区域) */}
          {mockTopbar({ui, isRunning, setIsRunning, showMenu, setShowMenu, setShowModal})}
          {/* 内容区 */}
          {mockOverviewContent()}
        </div>
        {/* 右栏 (right-rail 调度与任务队列区域) */}
        {mockRightRail()}
      </div>
      {/* 模拟弹窗 (modal 区域) */}
      {showModal && mockSampleModal({ui, setShowModal})}
      {/* 悬浮/停靠材质调节面板 (Inspector) */}
      {mockInspector({ui, onClose, isDocked, setIsDocked, isInspectorMinimized, setIsInspectorMinimized, custom, refresh, family, activeRegion, handleRegionSelect})}
    </div>
  )

  if (typeof document !== 'undefined' && document.body) {
    return createPortal(overlay, document.body)
  }
  // 没有 document 的环境（如 renderToStaticMarkup 测试）挂不了 Portal，直接返回节点本身。
  return overlay
}

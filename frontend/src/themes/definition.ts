/**
 * @fileoverview 主题组件契约：主题通过组件槽位替换工作台的壳层、导航与页面视图。
 */
import type { ComponentType, ReactNode } from 'react'
import type { Language } from '../i18n'
import type { SchedulerPanelProps } from '../components/useSchedulerControls'
import type { OverviewViewProps } from '../pages/Overview'

/** 传给导航视图的通用 props；内置导航与插件导航共用同一形状。 */
export interface NavigationProps {
  /** 当前实例名；全局页面为 undefined。 */
  instance?: string
  /** 导航点击后的回调，用于移动端点击链接后收起抽屉。 */
  onNavigate?: () => void
  /** 是否显示公告未读徽标。 */
  announcementUnread?: boolean
  /** 是否显示更新可用徽标。 */
  updateAvailable?: boolean
  /** 插件导航视图不可用时的内置回退内容。 */
  fallback?: ReactNode
}

/** 传给壳层组件的 props；在导航 props 之上补充页面级信息。 */
export interface ShellProps extends NavigationProps {
  /** 页面内容，由路由渲染。 */
  children: ReactNode
  /** 当前页面标题，展示在工具栏。 */
  pageTitle: string
  /** 打开「新建实例」交互。 */
  onCreate: () => void
}

/** 主题可替换的组件槽位全集；未声明的槽位回落到内置实现。 */
export interface ThemeComponents {
  /** 应用壳层。 */
  Shell: ComponentType<ShellProps>
  /** 主导航视图。 */
  Navigation: ComponentType<NavigationProps>
  /** 总览页视图。 */
  Overview: ComponentType<OverviewViewProps>
  /** 总览页内的调度面板。 */
  SchedulerPanel: ComponentType<SchedulerPanelProps>
}

/**
 * 收敛主题默认导出的类型，让未声明的槽位保持可选并获得 prop 检查。
 *
 * @param theme - 主题描述对象。
 * @returns 原对象，仅附加类型信息。
 */
export function defineTheme(theme: {
  id: string
  name: (language: Language) => string
  components: Partial<ThemeComponents>
}) { return theme }

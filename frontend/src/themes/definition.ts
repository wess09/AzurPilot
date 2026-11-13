import type { ComponentType, ReactNode } from 'react'
import type { Language } from '../i18n'
import type { SchedulerPanelProps } from '../components/useSchedulerControls'
import type { OverviewViewProps } from '../pages/Overview'

export interface NavigationProps {
  instance?: string
  onNavigate?: () => void
  announcementUnread?: boolean
  updateAvailable?: boolean
  fallback?: ReactNode
}

export interface ShellProps extends NavigationProps {
  children: ReactNode
  pageTitle: string
  onCreate: () => void
}

export interface ThemeComponents {
  Shell: ComponentType<ShellProps>
  Navigation: ComponentType<NavigationProps>
  Overview: ComponentType<OverviewViewProps>
  SchedulerPanel: ComponentType<SchedulerPanelProps>
}

export function defineTheme(theme: {
  id: string
  name: (language: Language) => string
  components: Partial<ThemeComponents>
}) { return theme }

/**
 * @fileoverview 前端应用主入口，初始化主题并挂载 React 根节点。
 */

import { Component, lazy, Suspense, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { createHashRouter, RouterProvider, Navigate } from 'react-router-dom'
import { App } from './app/App'
import { AppProvider } from './app/context'
import { ThemeWallpaper } from './components/ThemeWallpaper'
import { applyTheme, getThemePreference } from './app/theme'
import {StockExchangeBoundary,StockExchangeFallback} from './components/StockExchangeBoundary'
import { translateCurrentUi } from './i18n'
import './styles/legacy.css'
import './styles/minimal.css'
import './styles/shadcn.css'

// 顶层兜底与路由级兜底共用同一页：路由渲染出错时 React Router 会先接住，
// 没有 errorElement 就落到它自带的崩溃页（带堆栈），所以两级都要挂上。
function ErrorPage() {
  return <div className="welcome"><h1>{translateCurrentUi('error.pageTitle')}</h1><p>{translateCurrentUi('error.pageHint')}</p><button className="button primary" onClick={() => location.reload()}>{translateCurrentUi('error.reload')}</button></div>
}
class ErrorBoundary extends Component<{children: ReactNode}, {failed: boolean}> {
  state = {failed: false}
  static getDerivedStateFromError() { return {failed: true} }
  render() {
    if (this.state.failed) return <ErrorPage/>
    return this.props.children
  }
}
const InstanceSetup = lazy(() => import('./pages/InstanceSetup').then(module => ({default: module.InstanceSetup})))
const Overview = lazy(() => import('./pages/Overview').then(module => ({default: module.Overview})))
const TaskConfig = lazy(() => import('./pages/TaskConfig').then(module => ({default: module.TaskConfig})))
const Statistics = lazy(() => import('./pages/Statistics').then(module => ({default: module.Statistics})))
const Updater = lazy(() => import('./pages/Updater').then(module => ({default: module.Updater})))
const Announcement = lazy(() => import('./pages/Announcement').then(module => ({default: module.Announcement})))
const InterfaceSettings = lazy(() => import('./pages/InterfaceSettings').then(module => ({default: module.InterfaceSettings})))
const RemoteAccess = lazy(() => import('./pages/RemoteAccess').then(module => ({default: module.RemoteAccess})))
const Settings = lazy(() => import('./pages/Settings').then(module => ({default: module.Settings})))
const DevControls = lazy(() => import('./pages/DevControls').then(module => ({default: module.DevControls})))
const ConfigManager = lazy(() => import('./pages/ConfigManager').then(module => ({default: module.ConfigManager})))
const SchedulerProgram = lazy(() => import('./pages/SchedulerProgram').then(module => ({default: module.SchedulerProgram})))
const StockExchange = lazy(() => import('./pages/StockExchange').then(module => ({default: module.StockExchange})))
const FleetAnalysis = lazy(() => import('./pages/FleetAnalysis').then(module => ({default: module.FleetAnalysis})))
const FleetSwitch = lazy(() => import('./pages/FleetSwitch').then(module => ({default: module.FleetSwitch})))

const router = createHashRouter([
  {path: '/', element: <App/>, errorElement: <ErrorPage/>, children: [{path: 'setup', element: <InstanceSetup/>}, {path: 'announcement', element: <Announcement/>}, {path: 'interface', element: <InterfaceSettings/>}, {path: 'remote', element: <RemoteAccess/>}, {path: 'settings', element: <Settings/>}, {path: 'updater', element: <Updater/>}, {path: 'configs', element: <ConfigManager/>}, {path: 'dev', element: <DevControls/>}]},
  {path: '/i/:instance', element: <App/>, errorElement: <ErrorPage/>, children: [
    {index: true, element: <Navigate to="overview" replace/>},
    {path: 'overview', element: <Overview/>}, {path: 'task/:task', element: <TaskConfig/>},
    {path: 'resources', element: <Navigate to="../statistics?view=management" replace/>},
    {path: 'stock-exchange', element: <StockExchangeBoundary><Suspense fallback={<StockExchangeFallback/>}><StockExchange/></Suspense></StockExchangeBoundary>},
    {path: 'logs', element: <Navigate to="../overview" replace/>}, {path: 'statistics', element: <Statistics/>}, {path: 'scheduler', element: <Navigate to="../task/SchedulerProgram" replace/>}, {path: 'settings', element: <Navigate to="/settings" replace/>},
    {path: 'task/SchedulerProgram', element: <SchedulerProgram/>},
    {path: 'task/FleetAnalysis', element: <FleetAnalysis/>},
    {path: 'task/FleetSwitch', element: <FleetSwitch/>},
    {path: 'task/FleetInfo', element: <Navigate to="../FleetSwitch?tab=info" relative="path" replace/>},
    {path: 'task/FleetRotation', element: <Navigate to="../FleetSwitch?tab=rotation" relative="path" replace/>},
    {path: 'task/FleetTraining', element: <Navigate to="../FleetSwitch?tab=training" relative="path" replace/>},
    {path: 'task/FleetLevelTraining', element: <Navigate to="../FleetSwitch?tab=training" relative="path" replace/>},
    {path: 'task/FleetAffinityTraining', element: <Navigate to="../FleetSwitch?tab=training" relative="path" replace/>},
    {path: 'task/FleetEquipment', element: <Navigate to="../FleetSwitch?tab=equipment" relative="path" replace/>},
  ]},
  {path: '*', element: <Navigate to="/configs" replace/>},
])
// 在挂载前应用已保存的主题，避免首屏闪过默认外观。
applyTheme(getThemePreference())
createRoot(document.getElementById('root')!).render(<ErrorBoundary><AppProvider><ThemeWallpaper/><RouterProvider router={router}/></AppProvider></ErrorBoundary>)

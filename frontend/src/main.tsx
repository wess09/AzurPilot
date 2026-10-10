/**
 * @fileoverview 前端应用主入口，初始化主题并挂载 React 根节点。
 */

import { Component, lazy, Suspense, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { createHashRouter, RouterProvider, Navigate } from 'react-router-dom'
import { App } from './app/App'
import { AppProvider } from './app/context'
import { ThemeWallpaper } from './components/GlassMaterial'
import { applyTheme, getThemePreference } from './app/theme'
import { Overview } from './pages/Overview'
import { TaskConfig } from './pages/TaskConfig'
import { Statistics } from './pages/Statistics'
import { Home } from './pages/Home'
import { Updater } from './pages/Updater'
import { Announcement } from './pages/Announcement'
import { InterfaceSettings } from './pages/InterfaceSettings'
import { RemoteAccess } from './pages/RemoteAccess'
import { Settings } from './pages/Settings'
import { DevControls } from './pages/DevControls'
import { ConfigManager } from './pages/ConfigManager'
import {StockExchangeBoundary,StockExchangeFallback} from './stock/OverviewLink'
import { translateCurrentUi } from './i18n'

/* 顶层兜底与路由级兜底共用同一页：路由渲染出错时 React Router 会先接住，
   没有 errorElement 就落到它自带的崩溃页（带堆栈），所以两级都要挂上。 */
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
const SchedulerProgram = lazy(() => import('./pages/SchedulerProgram').then(module => ({default: module.SchedulerProgram})))
const StockExchange = lazy(() => import('./pages/StockExchange').then(module => ({default: module.StockExchange})))
const MindCalculator = lazy(() => import('./pages/MindCalculator').then(module => ({default: module.MindCalculator})))

const router = createHashRouter([
  {path: '/', element: <App/>, errorElement: <ErrorPage/>, children: [{index: true, element: <Home/>}, {path: 'announcement', element: <Announcement/>}, {path: 'interface', element: <InterfaceSettings/>}, {path: 'remote', element: <RemoteAccess/>}, {path: 'settings', element: <Settings/>}, {path: 'updater', element: <Updater/>}, {path: 'configs', element: <ConfigManager/>}, {path: 'dev', element: <DevControls/>}]},
  {path: '/i/:instance', element: <App/>, errorElement: <ErrorPage/>, children: [
    {index: true, element: <Navigate to="overview" replace/>},
    {path: 'overview', element: <Overview/>}, {path: 'task/:task', element: <TaskConfig/>},
    {path: 'mind-calculator', element: <Navigate to="../task/MindCalculator" replace/>},
    {path: 'resources', element: <Navigate to="../statistics?view=management" replace/>},
    {path: 'stock-exchange', element: <StockExchangeBoundary><Suspense fallback={<StockExchangeFallback/>}><StockExchange/></Suspense></StockExchangeBoundary>},
    {path: 'logs', element: <Navigate to="../overview" replace/>}, {path: 'statistics', element: <Statistics/>}, {path: 'scheduler', element: <Navigate to="../task/SchedulerProgram" replace/>}, {path: 'settings', element: <Navigate to="/settings" replace/>},
    {path: 'task/SchedulerProgram', element: <Suspense fallback={<div>{translateCurrentUi('common.loading')}</div>}><SchedulerProgram/></Suspense>},
    {path: 'task/MindCalculator', element: <Suspense fallback={<div>{translateCurrentUi('common.loading')}</div>}><MindCalculator/></Suspense>},
  ]},
  {path: '*', element: <Navigate to="/" replace/>},
])
// 先读取偏好并加载当前主题，再挂载页面，避免简约首屏短暂请求壁纸或玻璃库。
void applyTheme(getThemePreference()).then(() => {
  createRoot(document.getElementById('root')!).render(<ErrorBoundary><AppProvider><ThemeWallpaper/><RouterProvider router={router}/></AppProvider></ErrorBoundary>)
}).catch(() => {
  const root = document.getElementById('root')!
  root.textContent = '主题加载失败，请刷新页面重试。'
})

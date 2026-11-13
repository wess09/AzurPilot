import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import { useConnection } from '../app/context'
import { pluginAsset, type InstalledPlugin } from './types'

interface PluginState {
  plugins: InstalledPlugin[]
  ready: boolean
  error: string
  refresh: () => Promise<void>
  request: (path: string, options: RequestInit) => Promise<void>
  theme?: InstalledPlugin
  themeId: string
  setTheme: (id: string) => void
}

const initial: PluginState = {
  plugins: [], ready: false, error: '', themeId: '',
  refresh: async () => {}, request: async () => {}, setTheme: () => {},
}
const PluginContext = createContext(initial)
export const usePlugins = () => useContext(PluginContext)

export function PluginProvider({children}: {children: ReactNode}) {
  const connection = useConnection()
  const [plugins, setPlugins] = useState<InstalledPlugin[]>([])
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const [themeId, setSelectedTheme] = useState(() => {
    try { return localStorage.getItem('azurpilot.apu-theme') ?? '' } catch { return '' }
  })
  const requestId = useRef(0)
  const accept = useCallback((next: InstalledPlugin[]) => {
    setPlugins(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next)
    setReady(true)
    setError('')
  }, [])
  const refresh = useCallback(async () => {
    const id = ++requestId.current
    try {
      const result = await api.request('plugins.list', {})
      if (requestId.current === id) accept(result)
    } catch (failure) {
      if (requestId.current === id) setError((failure as Error).message)
    }
  }, [accept])
  useEffect(() => {
    if (connection === 'ready') void refresh()
    if (connection === 'auth') {setPlugins([]); setReady(false); setError('')}
    return () => { requestId.current++ }
  }, [connection, refresh])
  useEffect(() => api.onEvent(event => {
    if (event.topic === 'plugins') {
      requestId.current++
      accept(event.data as InstalledPlugin[])
    }
  }), [accept])
  const request = useCallback(async (path: string, options: RequestInit) => {
    const {token} = await api.request('plugins.access', {})
    const headers = new Headers(options.headers)
    headers.set('x-azurpilot-plugin-token', token)
    const response = await fetch('./api/v1/plugins' + path, {
      ...options, headers,
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(payload.error || response.statusText)
    }
    await refresh()
  }, [refresh])
  const setTheme = useCallback((id: string) => {
    setSelectedTheme(id)
    try { localStorage.setItem('azurpilot.apu-theme', id) } catch { /* Keep the session selection. */ }
  }, [])
  const theme = plugins.find(plugin => plugin.enabled && plugin.manifest.id === themeId && plugin.manifest.theme)
  const state = useMemo(() => ({plugins, ready, error, refresh, request, theme, themeId, setTheme}),
    [plugins, ready, error, refresh, request, theme, themeId, setTheme])
  return <PluginContext.Provider value={state}>{children}</PluginContext.Provider>
}

export function PluginStyles() {
  const {theme} = usePlugins()
  useEffect(() => {
    try {
      // 记录当前主题样式的直链，index.html 在应用挂载前用它预载皮肤，避免默认主题闪现。
      // 插件停用或更新后旧链接会 404，这里写入的新记录会把缓存纠正回来。
      localStorage.setItem('azurpilot.apu-styles', JSON.stringify(theme ? {
        id: theme.manifest.id, revision: theme.revision, styles: theme.manifest.theme?.styles ?? {},
      } : null))
    } catch { /* 拿不到 localStorage 时退回应用内的常规加载。 */ }
  }, [theme])
  if (!theme) return null
  return <>{Object.entries(theme.manifest.theme?.styles ?? {}).map(([component, path]) =>
    <link key={component} rel="stylesheet" href={pluginAsset(theme, path) + '?component=' + component}/>)}</>
}

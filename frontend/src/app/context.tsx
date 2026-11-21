/**
 * @fileoverview 全局 React 上下文提供者，统合实例、配置架构、语言和主题状态。
 */

import { createContext, useCallback, useMemo, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { api } from '../api/client'
import type { Instance, Schema } from '../api/types'
import { resumeEditors } from '../config/editors'
import { detectLanguage, isLanguage, languages, localeForLanguage, translateUi, type Language, type UiTranslator } from '../i18n'
import { applyTheme, getThemePreference, subscribeTheme, type Theme, type Material } from './theme'
import { palettes, type CustomPalette, type ResolvedMode } from './palettes'
import { usePageRead } from './usePageRead'

export { languages }

/** AppProvider 对外提供的上下文值；组件一律通过 useApp() 读取。 */
export interface AppContextValue {
  instancesLoaded: boolean; instances: Instance[]; schema?: Schema; refresh: () => Promise<void>; t: (key: string) => string; ui: UiTranslator
  bootstrapError?: string; retryBootstrap?: () => void
  notify: (message: string, error?: boolean) => void
  previewEnabled: boolean; setPreviewEnabled: (enabled: boolean) => void
  theme: Theme; setTheme: (theme: Theme) => void
  material: Material; setMaterial: (material: Material) => void
  resolvedMode: ResolvedMode
  customPalettes: CustomPalette[]; saveCustomPalette: (palette: CustomPalette) => void; deleteCustomPalette: (id: CustomPalette['id']) => void
  language: Language; setLanguage: (language: Language) => void
}
/** 全局 React 上下文本体；业务代码不要直接 useContext，用 useApp() 拿已断言的非空值。 */
export const AppContext = createContext<AppContextValue | null>(null)
/** 订阅后端操作连接的状态（connecting/ready/auth/offline），登录界面与全局可编辑性由它驱动。 */
export const useConnection = () => useSyncExternalStore(api.subscribe, api.getSnapshot, api.getSnapshot)
/** 读取全局上下文；必须在 AppProvider 之内使用，Provider 外拿到 null 时这里的断言即失效。 */
export const useApp = () => useContext(AppContext)!
const EMPTY_INSTANCES: Instance[] = []
const readInstances = () => api.request('instances.list', {})

function initialLanguage(): Language {
  try {
    const saved = localStorage.getItem('azurpilot.language')
    if (isLanguage(saved)) return saved
  } catch { /* 浏览器禁用存储时使用浏览器语言。 */ }
  return detectLanguage()
}

/**
 * 全局 Provider：持有实例列表、配置架构、语言与主题偏好，连接就绪后拉取数据并订阅后端事件。
 * 应用必须包在它之内；toast 提示也由它渲染。
 */
export function AppProvider({children}: {children: ReactNode}) {
  const connection = useConnection()
  const [previewEnabled, setPreviewEnabled] = useState(false)
  const {theme, resolvedMode, customPalettes, material} = useSyncExternalStore(subscribeTheme, getThemePreference, getThemePreference)
  const [language, setLanguage] = useState<Language>(initialLanguage)
  const instancesRead = usePageRead('instances', connection === 'ready', readInstances)
  const readSchema = useCallback(() => api.request('schema.get', {language}), [language])
  // Keep the current schema available during a language change so editors stay mounted.
  const schemaRead = usePageRead('schema', connection === 'ready', readSchema)
  const {data: instances = EMPTY_INSTANCES, ready: instancesLoaded, setData: setInstances, reload: reloadInstances} = instancesRead
  const {data: schema, reload: reloadSchema} = schemaRead
  const bootstrapError = (!instancesLoaded && instancesRead.error) || (!schema && schemaRead.error) || ''
  const retryBootstrap = useCallback(() => {reloadInstances(); reloadSchema()}, [reloadInstances, reloadSchema])
  const [toast, setToast] = useState<{message: string; error: boolean}>()
  const setTheme = useCallback((theme: Theme) => applyTheme({...getThemePreference(), theme}), [])
  const setMaterial = useCallback((material: Material) => applyTheme({...getThemePreference(), material}), [])
  const saveCustomPalette = useCallback((item: CustomPalette) => {
    const current = getThemePreference()
    const customPalettes = current.customPalettes.some(palette => palette.id === item.id)
      ? current.customPalettes.map(palette => palette.id === item.id ? item : palette) : [...current.customPalettes, item]
    applyTheme({...current, customPalettes, palette: current.theme === 'minimal' ? item.id : current.palette})
  }, [])
  const deleteCustomPalette = useCallback((id: CustomPalette['id']) => {
    const current = getThemePreference()
    applyTheme({
      ...current,
      customPalettes: current.customPalettes.filter(item => item.id !== id),
      palette: current.palette === id ? palettes[0] : current.palette,
    })
  }, [])
  useEffect(() => {
    document.documentElement.lang = localeForLanguage(language)
    try { localStorage.setItem('azurpilot.language', language) } catch { /* 存储不可用时仅当前会话生效。 */ }
  }, [language])
  useEffect(() => { api.connect(); return () => api.disconnect() }, [])
  useEffect(() => { if (connection === 'ready') resumeEditors() }, [connection])
  const notify = useCallback((message: string, error = false) => setToast({message, error}), [])
  const refresh = instancesRead.reloadAndWait
  useEffect(() => {
    const refreshError = (instancesLoaded && instancesRead.error) || (schema && schemaRead.error)
    if (refreshError) notify(refreshError, true)
  }, [instancesLoaded, instancesRead.error, schema, schemaRead.error, notify])
  useEffect(() => api.onEvent(event => {
    if (event.topic !== 'instances') return
    const next = event.data as Instance[]
    // 后端每 2s 推一次快照；内容没变就留住旧引用，避免整棵消费树跟着重渲染。
    setInstances(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next)
  }), [setInstances])
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(undefined), 6000)
    return () => clearTimeout(timer)
  }, [toast])
  const t = useCallback((key: string) => {
    let value: unknown = schema?.translations
    for (const part of key.split('.')) value = value && typeof value === 'object' ? (value as Record<string, unknown>)[part] : undefined
    // 翻译缺失时回落到键的最后一段：Task.Alas.name 这类键去掉 name/_info 后缀，剩下的就是可显示的标识。
    return typeof value === 'string' && value !== key ? value : key.split('.').filter(item => item !== 'name' && item !== '_info').at(-1) ?? key
  }, [schema])
  const ui = useCallback<UiTranslator>((key, params) => translateUi(language, key, params), [language])
  // value 固定身份：provider 因 toast、连接状态等无关状态重渲染时，消费点不跟着重渲染。
  const value = useMemo(() => ({instancesLoaded, instances, schema, refresh, bootstrapError, retryBootstrap, t, ui, notify, previewEnabled, setPreviewEnabled, theme, setTheme, material, setMaterial, resolvedMode, customPalettes, saveCustomPalette, deleteCustomPalette, language, setLanguage}),
    [instancesLoaded, instances, schema, refresh, bootstrapError, retryBootstrap, t, ui, notify, previewEnabled, setPreviewEnabled, theme, setTheme, material, setMaterial, resolvedMode, customPalettes, saveCustomPalette, deleteCustomPalette, language, setLanguage])
  return <AppContext.Provider value={value}>
    {children}
    {toast && <div role={toast.error ? 'alert' : 'status'} className={`toast ${toast.error ? 'error' : ''}`} onClick={() => setToast(undefined)}>{toast.message}</div>}
  </AppContext.Provider>
}

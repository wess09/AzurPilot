/**
 * @fileoverview 应用背景图与视频偏好管理、IndexedDB 持久化存储及数据流。
 */

import { api } from '../api/client'
import type { BackgroundGalleryEntry } from '../api/types'
import { getThemePreference, subscribeTheme, type Material } from './theme'

/** `default` 只是旧记录里的档位：读入时折算成 URL 模式的内置 API，不再写回。 */
export type BackgroundSource = 'off' | 'url' | 'upload'
/** 背景媒体类型。 */
export type BackgroundKind = 'image' | 'video'

interface BackgroundPreference {
  /** 背景来源档位。 */
  source: BackgroundSource
  /** 媒体类型。 */
  kind: BackgroundKind
  /** URL 模式：一行一个随机图 API，本次生效其中一条。 */
  urls: string[]
  /** 本次生效的是第几条（0 起）。 */
  active: number
  name: string
  /** 图库模式的生效条目 id（本地上传/直链存入的图都进同一个图库）。 */
  entry?: string
  /** The old browser media key referenced by this preference. */
  legacy?: boolean
}

/** 对外发布的背景状态快照：界面经 getBackground/subscribeBackground 消费，revision 自增表示有更新。 */
export interface BackgroundSnapshot extends BackgroundPreference {
  /** 真正交给 <img>/<video> 的地址：URL 模式是解析出的直链，图库模式是服务器上的文件。 */
  assetUrl: string
  /** URL 模式解析出的直链（解析失败时为空）。 */
  directUrl: string
  /** 是否正在解析随机图 API。 */
  resolving: boolean
  urlGeneration: number
  /** 最近一次地址解析失败的信息。 */
  resolveError: string
  /** 是否正在加载图库或浏览器上传文件。 */
  loading: boolean
  /** 快照版本，每次发布状态时递增。 */
  revision: number
}

/**
 * 内置默认随机图列表：**全部实测可用**的二次元图库。
 * 只收「每次请求都出新图」的二次元随机图接口，风景/3D/必应日图之类不收。
 * R18 接口**不放进仓库**；需要时由用户自己加进地址列表。
 */
export const DEFAULT_BACKGROUND_URLS = [
  'https://api.yppp.net/api.php',
]

/** 历史上唯一的那条内置 API：只用来识别「老用户的列表还是旧默认」，从而升级成整份列表。 */
const LEGACY_DEFAULT_URL = 'https://api.yppp.net/api.php'
const STORAGE_KEY = 'azurpilot.background'

/** 背景记录按材质各存一档：玻璃用原键（老用户设置不变），普通用新键。 */
const backgroundStorageKey = (material: Material) => material === 'plain' ? `${STORAGE_KEY}.plain` : STORAGE_KEY

/** 各材质的默认档：玻璃默认铺内置随机图，普通默认关闭，用户手动改了才铺。 */
const defaultBackgroundFor = (material: Material): BackgroundSource => material === 'plain' ? 'off' : 'url'

/** 多行 API 里挑一条生效。用 crypto 取随机数，避免 Math.random 的分布争议。 */
function pickActive(count: number): number {
  if (count <= 1) return 0
  const buffer = new Uint32Array(1)
  crypto.getRandomValues(buffer)
  return (buffer[0] ?? 0) % count
}
const DATABASE_NAME = 'azurpilot-preferences'
const DATABASE_VERSION = 1
const STORE_NAME = 'media'
const UPLOAD_KEY = 'background'
const listeners = new Set<() => void>()
/** 图库文件由服务器直接提供（与模板图同一套做法），同源、无跨域。 */
export const galleryUrl = (identifier: string) => `/background-library/${encodeURIComponent(identifier)}`

const MIGRATED_KEY = 'azurpilot.background.migrated'

/** 迁移这类一次性动作的留痕，失败也不该打断用户。 */
function logger(message: string) {
  console.info(`[背景]${message}`)
}

/** 按材质读回背景记录。参数与默认档都在这里决定，界面与壁纸都从这里取。 */
export function readBackgroundPreference(material: Material): BackgroundPreference {
  const source = defaultBackgroundFor(material)
  const fallback: BackgroundPreference = {
    source, kind: 'image', urls: source === 'url' ? [...DEFAULT_BACKGROUND_URLS] : [], active: 0, name: '',
  }
  try {
    const raw = JSON.parse(localStorage.getItem(backgroundStorageKey(material)) ?? 'null') as Record<string, unknown> | null
    const kind = raw?.kind === 'image' || raw?.kind === 'video' ? raw.kind : 'image'
    const legacy = (raw?.source === 'upload' || raw?.source === 'off') && typeof raw.name === 'string' && !!raw.name && !raw.entry && raw.legacy !== false && localStorage.getItem(MIGRATED_KEY) !== '1'
    /* 关闭档保留已存的地址与图库条目，重新打开时回到关闭前的那一档。 */
    if (raw?.source === 'off') {
      return {...fallback, source: 'off', kind, urls: Array.isArray(raw.urls) ? normalizeBackgroundUrls(raw.urls.filter((item): item is string => typeof item === 'string')) : [], active: typeof raw.active === 'number' && raw.active >= 0 ? raw.active : 0, name: typeof raw.name === 'string' ? raw.name : '', entry: typeof raw.entry === 'string' ? raw.entry : undefined, legacy}
    }
    /* 旧记录：`default` 就是「用内置 API」，折成 URL 模式的一条。 */
    if (raw?.source === 'default') return {source: 'url', kind, urls: [...DEFAULT_BACKGROUND_URLS], active: pickActive(DEFAULT_BACKGROUND_URLS.length), name: ''}
    if (raw?.source === 'url') {
      /* 新记录是 urls 列表，旧记录是单条 url；两者都读。 */
      const list = Array.isArray(raw.urls)
        ? raw.urls.filter((item): item is string => typeof item === 'string')
        : typeof raw.url === 'string' ? [raw.url] : []
      const urls = normalizeBackgroundUrls(list)
      if (!urls.length) return fallback
      /* 升级：列表恰好只有"当年那一条内置 API"时补成现在的整份默认列表。
         用户自己加过的地址一律不动（只有完全等于旧默认才触发）。 */
      if (urls.length === 1 && urls[0] === LEGACY_DEFAULT_URL) {
        return {source: 'url', kind, urls: [...DEFAULT_BACKGROUND_URLS], active: pickActive(DEFAULT_BACKGROUND_URLS.length), name: ''}
      }
      const active = typeof raw.active === 'number' && raw.active >= 0 && raw.active < urls.length ? raw.active : pickActive(urls.length)
      return {source: 'url', kind, urls, active, name: ''}
    }
    if (raw?.source === 'upload' && (raw.kind === 'image' || raw.kind === 'video')) {
      return {
        source: 'upload', kind, urls: [], active: 0,
        name: typeof raw.name === 'string' ? raw.name : '',
        entry: typeof raw.entry === 'string' ? raw.entry : undefined, legacy,
      }
    }
  } catch { /* 存储不可用或旧数据损坏时使用默认背景。 */ }
  return fallback
}

/** 某条记录当前实际铺的地址（URL 模式取生效那条，其余为空）。 */
const activeBackgroundUrl = (preference: BackgroundPreference) => preference.source === 'url' ? preference.urls[preference.active] ?? '' : ''

/** 这一条地址本身就是图片/视频文件时才可直接铺；随机图 API 端点每次请求都换图，必须先解析。 */
const directMediaUrl = (url: string) => /\.(?:jpe?g|png|webp|gif|bmp|avif|mp4|webm)(?:[?#]|$)/i.test(url) ? url : ''
/** 记着上一张真正铺出来的图：解析失败时保留它，避免回退到随机端点换出新图。 */
let lastGoodAssetUrl = ''

function readActiveBackground(): BackgroundPreference {
  const {theme, material} = getThemePreference()
  return theme === 'minimal'
    ? {source: 'off', kind: 'image', urls: [], active: 0, name: ''}
    : readBackgroundPreference(material)
}

const initial = readActiveBackground()
let snapshot: BackgroundSnapshot = {
  ...initial,
  assetUrl: initial.source === 'upload' && initial.entry ? galleryUrl(initial.entry) : directMediaUrl(activeBackgroundUrl(initial)),
  directUrl: '',
  resolving: initial.source === 'url',
  urlGeneration: 0,
  resolveError: '',
  loading: initial.source === 'upload',
  revision: 0,
}
let objectUrl = ''
let uploadLoad: Promise<void> | undefined

/** 读取当前背景状态快照，供 `useSyncExternalStore` 使用。 */
export const getBackground = () => snapshot
/**
 * 订阅背景状态变化。
 *
 * @param listener 状态变化回调。
 * @returns 取消订阅函数。
 */
export const subscribeBackground = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function publish(patch: Partial<BackgroundSnapshot>) {
  snapshot = {...snapshot, ...patch, revision: snapshot.revision + 1}
  listeners.forEach(listener => listener())
}

let selectionVersion = 0
function publishSelection(patch: Partial<BackgroundSnapshot>) {
  selectionVersion++
  publish({legacy: false, ...patch})
}

export function captureBackgroundSelection() {
  const version = selectionVersion
  const {theme, material} = getThemePreference()
  return () => {
    const current = getThemePreference()
    return selectionVersion === version && current.theme === theme && current.material === material
  }
}

function savePreference(value: BackgroundPreference) {
  try { localStorage.setItem(backgroundStorageKey(getThemePreference().material), JSON.stringify(value)) } catch { /* 本次会话内仍立即生效。 */ }
}

function replaceObjectUrl(next = '') {
  if (objectUrl) URL.revokeObjectURL(objectUrl)
  objectUrl = next
}

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (!globalThis.indexedDB) return reject(new Error('当前浏览器不支持持久化文件存储。'))
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) request.result.createObjectStore(STORE_NAME)
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('无法打开背景文件存储。'))
  })
}

async function storedFile(mode: IDBTransactionMode, value?: Blob): Promise<Blob | undefined> {
  const database = await openDatabase()
  try {
    return await new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, mode)
      let result: Blob | undefined
      const request = value === undefined
        ? transaction.objectStore(STORE_NAME).get(UPLOAD_KEY)
        : transaction.objectStore(STORE_NAME).put(value, UPLOAD_KEY)
      request.onsuccess = () => { result = value === undefined ? request.result as Blob | undefined : value }
      request.onerror = () => reject(request.error ?? new Error('无法保存背景文件。'))
      transaction.onabort = () => reject(transaction.error ?? new Error('背景文件存储事务已中止。'))
      transaction.oncomplete = () => resolve(result)
    })
  } finally {
    database.close()
  }
}

async function deleteStoredFile() {
  const database = await openDatabase()
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, 'readwrite')
      const request = transaction.objectStore(STORE_NAME).delete(UPLOAD_KEY)
      request.onerror = () => reject(request.error)
      transaction.onabort = () => reject(transaction.error ?? new Error('背景文件存储事务已中止。'))
      transaction.oncomplete = () => resolve()
    })
  } finally { database.close() }
}

/** 一行一个地址：去空行、去重、逐条校验。全空时返回空数组，交给调用方回填内置默认。 */
function normalizeBackgroundUrls(values: string[]): string[] {
  const seen = new Set<string>()
  for (const value of values) {
    const trimmed = value.trim()
    if (!trimmed) continue
    seen.add(normalizeBackgroundUrl(trimmed))
  }
  return [...seen]
}

/** 校验并规范化单条背景地址：去首尾空白、要求 http(s) 协议、限长 2048；不合法时抛出对应中文错误。 */
export function normalizeBackgroundUrl(value: string): string {
  const input = value.trim()
  if (!input || input.length > 2048) throw new Error('请输入不超过 2048 个字符的背景地址。')
  let parsed: URL
  try { parsed = new URL(input) } catch { throw new Error('请输入有效的背景地址。') }
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('背景地址仅支持 HTTP 或 HTTPS。')
  return parsed.href
}

/* 切换主题或材质时读取当前背景，简约主题保留原有记录供切回时使用。 */
subscribeTheme(() => {
  const next = readActiveBackground()
  if (next.source === snapshot.source && next.kind === snapshot.kind && next.entry === snapshot.entry
    && next.active === snapshot.active && JSON.stringify(next.urls) === JSON.stringify(snapshot.urls) && next.name === snapshot.name) return
  replaceObjectUrl()
  const initialAsset = next.source === 'upload' ? (next.entry ? galleryUrl(next.entry) : '') : next.source === 'url' ? (directMediaUrl(activeBackgroundUrl(next)) || lastGoodAssetUrl) : ''
  publishSelection({...next, assetUrl: initialAsset, directUrl: '', resolving: next.source === 'url', resolveError: '', urlGeneration: snapshot.urlGeneration + 1, loading: next.source === 'upload'})
  if (next.source === 'upload') void loadUploadedBackground()
})

async function loadUploadedBackground() {
  if (snapshot.source !== 'upload' || !snapshot.legacy || snapshot.assetUrl || uploadLoad) return uploadLoad
  const isCurrent = captureBackgroundSelection()
  uploadLoad = (async () => {
    try {
      const file = await storedFile('readonly')
      if (!isCurrent()) return
      if (!file) { if (snapshot.loading) publish({loading: false}); return }
      const url = URL.createObjectURL(file)
      replaceObjectUrl(url)
      publish({assetUrl: url, loading: false})
    } catch {
      if (isCurrent() && snapshot.loading) publish({loading: false})
    } finally {
      uploadLoad = undefined
    }
  })()
  return uploadLoad
}

export function publishResolvedBackground(generation: number, media: {assetUrl: string; directUrl: string} | undefined, error: string) {
  if (snapshot.source !== 'url' || snapshot.urlGeneration !== generation) return
  if (error) {
    const fallback = lastGoodAssetUrl || activeBackgroundUrl(snapshot)
    publish({assetUrl: fallback, resolving: false, resolveError: error})
  } else if (media) {
    lastGoodAssetUrl = media.assetUrl
    publish({...media, resolving: false, resolveError: ''})
  }
}

export function retryBackgroundUrl() {
  if (snapshot.source !== 'url') return
  publish({urlGeneration: snapshot.urlGeneration + 1, resolving: true, resolveError: ''})
}

/** 设置 URL 模式的多行 API：一行一条，本次随机生效一条；全清空自动回填内置随机图 API。 */
export function setBackgroundUrls(values: string[], kind: BackgroundKind) {
  const cleaned = normalizeBackgroundUrls(values)
  const urls = cleaned.length ? cleaned : [...DEFAULT_BACKGROUND_URLS]
  const preference: BackgroundPreference = {source: 'url', kind, urls, active: pickActive(urls.length), name: ''}
  const activeUrl = urls[preference.active] ?? urls[0] ?? DEFAULT_BACKGROUND_URLS[0] ?? ''
  replaceObjectUrl()
  savePreference(preference)
  publishSelection({...preference, assetUrl: directMediaUrl(activeUrl), directUrl: '', resolving: true, resolveError: '', urlGeneration: snapshot.urlGeneration + 1, loading: false})
}


let migration: Promise<void> | undefined
/** Import the shared IndexedDB file once, preserving every preference that references it. */
export function migrateStoredUpload(): Promise<void> {
  if (migration) return migration
  const syncActive = (material: Material, current: BackgroundPreference) => {
    const active = getThemePreference()
    if (active.theme === 'minimal' || active.material !== material || !snapshot.legacy
      || current.legacy || current.source !== snapshot.source || current.kind !== snapshot.kind || current.name !== snapshot.name) return
    replaceObjectUrl()
    publishSelection({...current, assetUrl: current.source === 'upload' && current.entry ? galleryUrl(current.entry) : '', loading: false})
  }
  migration = (async () => {
    const saved = localStorage.getItem(MIGRATED_KEY)
    if (saved === '1') {
      const {material} = getThemePreference()
      syncActive(material, readBackgroundPreference(material))
      return
    }
    const savedEntry = saved ? JSON.parse(saved) as BackgroundGalleryEntry : undefined
    const materials = ['glass', 'plain'] as const
    const legacyPreference = materials.map(readBackgroundPreference).find(preference => preference.legacy)
    const file = await storedFile('readonly')
    if (savedEntry || file) {
      const originalName = legacyPreference?.name || 'legacy-upload'
      const extensions: Record<string, string> = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif', 'image/bmp': '.bmp', 'image/avif': '.avif', 'video/mp4': '.mp4', 'video/webm': '.webm', 'video/quicktime': '.mov'}
      const fallback = legacyPreference?.kind === 'video' ? '.mp4' : '.jpg'
      const name = /\.(jpe?g|png|webp|gif|bmp|avif|mp4|webm|mov)$/i.test(originalName) ? originalName : originalName + (extensions[file?.type ?? ''] || fallback)
      const entry = savedEntry ?? await uploadBackgroundFile(new File([file!], name, {type: file!.type || (fallback === '.mp4' ? 'video/mp4' : 'image/jpeg')}), true)
      if (!savedEntry) localStorage.setItem(MIGRATED_KEY, JSON.stringify(entry))
      for (const material of materials) {
        const current = readBackgroundPreference(material)
        const updated = current.legacy ? {...current, entry: entry.id, legacy: false} : current
        if (current.legacy) localStorage.setItem(backgroundStorageKey(material), JSON.stringify(updated))
        syncActive(material, updated)
      }
      logger('已把旧的浏览器上传背景迁移进图库')
    }
    if (file) await deleteStoredFile()
    localStorage.setItem(MIGRATED_KEY, '1')
    const {material} = getThemePreference()
    syncActive(material, readBackgroundPreference(material))
  })().catch(() => { /* Keep the old file and retry on a later gallery read. */ }).finally(() => { migration = undefined })
  return migration
}

export async function openGalleryFolder() {
  const result = await api.request('background.gallery.open', {})
  return result.path
}

/** Select an entry supplied by the gallery owner. */
export function applyGalleryEntry(entry: BackgroundGalleryEntry) {
  const preference: BackgroundPreference = {source: 'upload', kind: entry.kind, urls: [], active: 0, name: entry.name, entry: entry.id}
  replaceObjectUrl()
  savePreference(preference)
  publishSelection({...preference, assetUrl: galleryUrl(entry.id), directUrl: '', resolving: false, resolveError: '', loading: false})
}

/** Enter an empty gallery so later reads can restore an upload selection. */
export function enterGallery(identifier?: string) {
  const preference: BackgroundPreference = {
    source: 'upload', kind: snapshot.kind, urls: [], active: 0,
    name: identifier && identifier === snapshot.entry ? snapshot.name : '', entry: identifier,
  }
  replaceObjectUrl()
  savePreference(preference)
  publishSelection({...preference, assetUrl: identifier ? galleryUrl(identifier) : '', loading: false, directUrl: '', resolving: false, resolveError: ''})
}

/** Reconcile the active upload with a complete, successfully loaded gallery. */
export function reconcileGallery(entries: BackgroundGalleryEntry[]) {
  if (snapshot.source !== 'upload') return
  if (snapshot.legacy) { void loadUploadedBackground(); return }
  const entry = entries.find(item => item.id === snapshot.entry) ?? entries[pickActive(entries.length)]
  if (entry) {
    if (snapshot.entry !== entry.id || snapshot.assetUrl !== galleryUrl(entry.id) || snapshot.loading) applyGalleryEntry(entry)
  } else if (snapshot.assetUrl || snapshot.entry || snapshot.loading) {
    enterGallery()
  }
}

export async function uploadBackgroundFile(file: File, legacy = false) {
  const form = new FormData()
  form.append('file', file)
  if (legacy) form.append('legacy', '1')
  const {token} = await api.request('background.access', {})
  const response = await fetch('/api/v1/background/gallery', {method: 'POST', body: form, headers: {'x-azurpilot-background-token': token}})
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload?.error || '上传失败。')
  if (!payload.entry?.id) throw new Error('上传响应缺少图库条目。')
  return payload.entry as BackgroundGalleryEntry
}

export async function saveDirectUrlToGallery() {
  const url = snapshot.directUrl
  if (!url) throw new Error('还没有解析出直链。')
  const result = await api.request('background.gallery.add', {url, name: snapshot.name || ''})
  return result.entry
}

export async function removeGalleryEntry(identifier: string) {
  await api.request('background.gallery.remove', {id: identifier})
}

/** 关闭背景：普通材质的默认档；玻璃材质下也可显式关掉（上传文件保留，便于切回）。 */
export function disableBackground() {
  /* 保留地址列表与图库条目：只关铺图，下次切回各自档位时接着用。 */
  const preference: BackgroundPreference = {source: 'off', kind: snapshot.kind, urls: snapshot.urls, active: snapshot.active, name: snapshot.name, entry: snapshot.entry, legacy: snapshot.legacy}
  replaceObjectUrl()
  savePreference(preference)
  publishSelection({...preference, assetUrl: '', loading: false})
}


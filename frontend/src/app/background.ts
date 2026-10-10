/**
 * @fileoverview 应用背景图与视频偏好管理、IndexedDB 持久化存储及数据流。
 */

import { api } from '../api/client'
import type { BackgroundGalleryEntry } from '../api/types'
import { getThemePreference, subscribeTheme, type Material } from './theme'

/** 'default' 只是旧记录里的档位：读入时折算成 URL 模式的内置 API，不再写回。 */
export type BackgroundSource = 'off' | 'url' | 'upload'
export type BackgroundKind = 'image' | 'video'

export interface BackgroundPreference {
  source: BackgroundSource
  kind: BackgroundKind
  /** URL 模式：一行一个随机图 API，本次生效其中一条。 */
  urls: string[]
  /** 本次生效的是第几条（0 起）。 */
  active: number
  name: string
  /** 图库模式的生效条目 id（本地上传/直链存入的图都进同一个图库）。 */
  entry?: string
}

export interface BackgroundSnapshot extends BackgroundPreference {
  /** 真正交给 <img>/<video> 的地址：URL 模式是解析出的直链，图库模式是服务器上的文件。 */
  assetUrl: string
  /** URL 模式解析出的直链（解析失败时为空）。 */
  directUrl: string
  resolving: boolean
  resolveError: string
  loading: boolean
  revision: number
}

/** 内置默认随机图列表：**全部实测可用**的二次元图库。
    只收"每次请求都出新图"的二次元随机图接口，风景/3D/必应日图之类不收。
    R18 接口**不放进仓库**；需要时由用户自己加进地址列表。 */
export const DEFAULT_BACKGROUND_URLS = [
  'https://api.yppp.net/api.php',
]

/** 单独一条内置地址。 */

/** 历史上唯一的那条内置 API：只用来识别"老用户的列表还是旧默认"，从而升级成整份列表。 */
const LEGACY_DEFAULT_URL = 'https://api.yppp.net/api.php'
const STORAGE_KEY = 'azurpilot.background'

/** 背景记录按材质各存一档：玻璃用原键（老用户设置不变），普通用新键。 */
export const backgroundStorageKey = (material: Material) => material === 'plain' ? `${STORAGE_KEY}.plain` : STORAGE_KEY

/** 各材质的默认档：玻璃默认铺内置随机图，普通默认关闭，用户手动改了才铺。 */
export const defaultBackgroundFor = (material: Material): BackgroundSource => material === 'plain' ? 'off' : 'url'

/** 多行 API 里挑一条生效。用 crypto 取随机数，避免 Math.random 的分布争议。 */
function pickActive(count: number): number {
  if (count <= 1) return 0
  const buffer = new Uint32Array(1)
  crypto.getRandomValues(buffer)
  return buffer[0] % count
}
const DATABASE_NAME = 'azurpilot-preferences'
const DATABASE_VERSION = 1
const STORE_NAME = 'media'
const UPLOAD_KEY = 'background'
const listeners = new Set<() => void>()
/** 图库文件由服务器直接提供（与模板图同一套做法），同源、无跨域。 */
export const galleryUrl = (identifier: string) => `/background-library/${encodeURIComponent(identifier)}`

/** 网图的同源代理地址：服务端先抓下来再回传，浏览器加载它与直链是同一张图。 */
export const proxyUrl = (url: string, token: string) => `/api/v1/background/media?url=${encodeURIComponent(url)}&token=${encodeURIComponent(token)}`

const MIGRATED_KEY = 'azurpilot.background.migrated'
/** initBackgroundGallery 只跑一次的守卫（它是幂等的引导流程，重复调用会引发重解析循环）。 */
let bootstrapped = false

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
    /* 关闭档保留已存的地址与图库条目，重新打开时回到关闭前的那一档。 */
    if (raw?.source === 'off') {
      return {...fallback, source: 'off', kind, urls: Array.isArray(raw.urls) ? normalizeBackgroundUrls(raw.urls.filter((item): item is string => typeof item === 'string')) : [], active: typeof raw.active === 'number' && raw.active >= 0 ? raw.active : 0, name: typeof raw.name === 'string' ? raw.name : '', entry: typeof raw.entry === 'string' ? raw.entry : undefined}
    }
    /* 旧记录：'default' 就是「用内置 API」，折成 URL 模式的一条。 */
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
        entry: typeof raw.entry === 'string' ? raw.entry : undefined,
      }
    }
  } catch { /* 存储不可用或旧数据损坏时使用默认背景。 */ }
  return fallback
}

/** 某条记录当前实际铺的地址（URL 模式取生效那条，其余为空）。 */
export const activeBackgroundUrl = (preference: BackgroundPreference) => preference.source === 'url' ? preference.urls[preference.active] ?? '' : ''

/** 这一条地址本身就是图片/视频文件时才可直接铺；随机图 API 端点每次请求都换图，必须先解析。 */
const directMediaUrl = (url: string) => /\.(?:jpe?g|png|webp|gif|bmp|avif|mp4|webm)(?:[?#]|$)/i.test(url) ? url : ''
/** 记着上一张真正铺出来的图：解析失败时保留它，避免回退到随机端点换出新图。 */
let lastGoodAssetUrl = ''

const initial = readBackgroundPreference(getThemePreference().material)
let snapshot: BackgroundSnapshot = {
  ...initial,
  assetUrl: initial.source === 'upload' && initial.entry ? galleryUrl(initial.entry) : directMediaUrl(activeBackgroundUrl(initial)),
  directUrl: '',
  resolving: false,
  resolveError: '',
  loading: initial.source === 'upload',
  revision: 0,
}
/** 图库条目缓存：列表接口回来一次就存这里，界面与随机取图都读它。 */
let gallery: BackgroundGalleryEntry[] = []
let objectUrl = ''
let uploadLoad: Promise<void> | undefined

export const getBackground = () => snapshot
export const subscribeBackground = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function publish(patch: Partial<BackgroundSnapshot>) {
  snapshot = {...snapshot, ...patch, revision: snapshot.revision + 1}
  listeners.forEach(listener => listener())
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
  let database: IDBDatabase | undefined
  try {
    const opened = await openDatabase()
    database = opened
    await new Promise<void>((resolve, reject) => {
      const transaction = opened.transaction(STORE_NAME, 'readwrite')
      const request = transaction.objectStore(STORE_NAME).delete(UPLOAD_KEY)
      request.onerror = () => reject(request.error)
      transaction.oncomplete = () => resolve()
    })
  } catch { /* 清理失败不应阻止切换到其他背景。 */ }
  finally { database?.close() }
}

/** 一行一个地址：去空行、去重、逐条校验。全空时返回空数组，交给调用方回填内置默认。 */
export function normalizeBackgroundUrls(values: string[]): string[] {
  const seen = new Set<string>()
  for (const value of values) {
    const trimmed = value.trim()
    if (!trimmed) continue
    seen.add(normalizeBackgroundUrl(trimmed))
  }
  return [...seen]
}

export function normalizeBackgroundUrl(value: string): string {
  const input = value.trim()
  if (!input || input.length > 2048) throw new Error('请输入不超过 2048 个字符的背景地址。')
  let parsed: URL
  try { parsed = new URL(input) } catch { throw new Error('请输入有效的背景地址。') }
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('背景地址仅支持 HTTP 或 HTTPS。')
  return parsed.href
}

/* 切换材质时换成那一档自己的记录：普通默认关闭、玻璃默认随机图，各档独立保存。 */
subscribeTheme(() => {
  const next = readBackgroundPreference(getThemePreference().material)
  if (next.source === snapshot.source && activeBackgroundUrl(next) === activeBackgroundUrl(snapshot) && next.name === snapshot.name) return
  replaceObjectUrl()
  const initialAsset = next.source === 'upload' ? (next.entry ? galleryUrl(next.entry) : '') : next.source === 'url' ? (directMediaUrl(activeBackgroundUrl(next)) || lastGoodAssetUrl) : ''
  publish({...next, assetUrl: initialAsset, loading: next.source === 'upload'})
  if (next.source === 'upload') void loadUploadedBackground()
  if (next.source === 'url') void resolveActiveBackground()
})

export async function loadUploadedBackground() {
  if (snapshot.source !== 'upload' || snapshot.assetUrl || uploadLoad) return uploadLoad
  uploadLoad = (async () => {
    try {
      const file = await storedFile('readonly')
      if (!file || snapshot.source !== 'upload') {
        const {revision: _, ...current} = snapshot
        return publish({...current, loading: false})
      }
      const url = URL.createObjectURL(file)
      replaceObjectUrl(url)
      if (snapshot.source === 'upload') {
        const {revision: _, ...current} = snapshot
        publish({...current, assetUrl: url, loading: false})
      }
    } catch {
      if (snapshot.source === 'upload') {
        const {revision: _, ...current} = snapshot
        publish({...current, loading: false})
      }
    } finally {
      uploadLoad = undefined
    }
  })()
  return uploadLoad
}

/** 把当前生效的那条 API 交给服务端解析成真实直链（跨域时浏览器读不到最终地址）。 */
export async function resolveActiveBackground() {
  if (snapshot.source !== 'url') return
  const url = activeBackgroundUrl(snapshot)
  if (!url) return
  publish({resolving: true, resolveError: ''})
  try {
    const {token} = await api.request('background.access', {})
    const result = await api.request('background.resolve', {url})
    if (activeBackgroundUrl(snapshot) !== url) return
    /* 解析成功：壁纸改用直链 —— 同一个地址同时用于预览与"存入图库"，不会出现两次随机。 */
    lastGoodAssetUrl = proxyUrl(result.final_url, token)
    publish({assetUrl: lastGoodAssetUrl, directUrl: result.final_url, resolving: false, resolveError: ''})
  } catch (error) {
    /* 解析失败就退回原地址直接当图片用（很多 API 本身就是图片），并把原因留给界面显示。 */
    const fallback = lastGoodAssetUrl || url
    publish({assetUrl: fallback, resolving: false, resolveError: (error as Error).message})
  }
}

/** 设置 URL 模式的多行 API：一行一条，本次随机生效一条；全清空自动回填内置随机图 API。 */
export function setBackgroundUrls(values: string[], kind: BackgroundKind) {
  const cleaned = normalizeBackgroundUrls(values)
  const urls = cleaned.length ? cleaned : [...DEFAULT_BACKGROUND_URLS]
  const preference: BackgroundPreference = {source: 'url', kind, urls, active: pickActive(urls.length), name: ''}
  replaceObjectUrl()
  savePreference(preference)
  publish({...preference, assetUrl: directMediaUrl(urls[preference.active]), directUrl: '', resolveError: '', loading: false})
  void deleteStoredFile()
  void resolveActiveBackground()
}


/** 启动时把图库拉回来：图库模式随机铺一张，并把旧的浏览器上传图迁移进图库（只做一次）。 */
export async function initBackgroundGallery() {
  /* 只做一次：壁纸的加载 effect 依赖 revision，而这里会 publish；
     没有这个守卫就会「解析→revision 变→effect 重跑→再解析」无限重解析（随机图 API 每次都是新图，表现就是背景狂闪）。 */
  if (bootstrapped) return
  bootstrapped = true
  await refreshGallery()
  /* 迁移必须排在"随机铺一张"之前：随机铺一张会把快照里的名字换成库里的条目名，
     迁移再拿这个名字去登记，旧图的文件名就丢了。 */
  await migrateStoredUpload()
  if (snapshot.source === 'upload') {
    if (snapshot.entry && gallery.some(item => item.id === snapshot.entry)) publish({assetUrl: galleryUrl(snapshot.entry), loading: false})
    else applyGalleryEntry()
  }
  /* 刷新页面后也要把当前 URL 档解析成直链。 */
  if (snapshot.source === 'url') void resolveActiveBackground()
}

/** 旧的单图存在浏览器 IndexedDB 里：取出来上传进图库，再清掉旧记录，避免丢图。 */
async function migrateStoredUpload() {
  if (localStorage.getItem(MIGRATED_KEY)) return
  try {
    const file = await storedFile('readonly')
    if (file && file.size) {
      const name = snapshot.name || 'legacy-upload'
      await uploadBackgroundFile(new File([file], name, {type: file.type || 'image/jpeg'}))
      logger('已把旧的浏览器上传背景迁移进图库')
    }
    await deleteStoredFile()
    localStorage.setItem(MIGRATED_KEY, '1')
  } catch { /* 迁移失败不影响使用：图库照常工作，下次启动再试。 */ }
}

/** 在系统文件管理器里打开图库文件夹。 */
export async function openGalleryFolder() {
  const result = await api.request('background.gallery.open', {})
  return result.path
}

/** 拉取图库列表；界面与随机取图都依赖它。 */
export async function refreshGallery() {
  try {
    gallery = await api.request('background.gallery.list', {})
  } catch { /* 拉取失败按空图库处理，界面显示为空。 */ gallery = [] }
  listeners.forEach(listener => listener())
  return gallery
}

export const getGallery = () => gallery

/** 让图库里的某一条生效；不传 id 则随机抽一条（多图随机播放）。 */
export function applyGalleryEntry(identifier?: string) {
  if (!gallery.length) return
  const entry = (identifier ? gallery.find(item => item.id === identifier) : undefined)
    ?? gallery[Math.floor(pickActive(gallery.length))]
  if (!entry) return
  const preference: BackgroundPreference = {source: 'upload', kind: entry.kind, urls: [], active: 0, name: entry.name, entry: entry.id}
  replaceObjectUrl()
  savePreference(preference)
  publish({...preference, assetUrl: galleryUrl(entry.id), directUrl: '', resolveError: '', loading: false})
}


/** 上传本地图片到图库（服务端落盘）。 */
export async function uploadBackgroundFile(file: File) {
  const form = new FormData()
  form.append('file', file)
  const {token} = await api.request('background.access', {})
  const response = await fetch('/api/v1/background/gallery', {method: 'POST', body: form, headers: {'x-azurpilot-background-token': token}})
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload?.error || '上传失败。')
  await refreshGallery()
  applyGalleryEntry(payload.entry?.id)
  return payload.entry as BackgroundGalleryEntry
}

/** 把当前解析出的直链存进图库（服务端代抓，跨域也能存）。 */
export async function saveDirectUrlToGallery() {
  const url = snapshot.directUrl
  if (!url) throw new Error('还没有解析出直链。')
  const result = await api.request('background.gallery.add', {url, name: snapshot.name || ''})
  await refreshGallery()
  return result.entry
}

export async function removeGalleryEntry(identifier: string) {
  await api.request('background.gallery.remove', {id: identifier})
  await refreshGallery()
  if (snapshot.entry === identifier) applyGalleryEntry()
}

/** 关闭背景：普通材质的默认档；玻璃材质下也可显式关掉（上传文件保留，便于切回）。 */
export function disableBackground() {
  /* 保留地址列表与图库条目：只关铺图，下次切回各自档位时接着用。 */
  const preference: BackgroundPreference = {source: 'off', kind: snapshot.kind, urls: snapshot.urls, active: snapshot.active, name: snapshot.name, entry: snapshot.entry}
  replaceObjectUrl()
  savePreference(preference)
  publish({...preference, assetUrl: '', loading: false})
}


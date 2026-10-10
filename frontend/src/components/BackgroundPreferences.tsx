/**
 * @fileoverview 背景偏好设置组件（支持 URL 与本地文件上传）。
 */

import { useEffect, useState, useSyncExternalStore, type FormEvent } from 'react'
import { BookmarkPlus, ExternalLink, FolderOpen, ListPlus, Shuffle, Upload, X } from 'lucide-react'
import { DEFAULT_BACKGROUND_URLS, applyGalleryEntry, disableBackground, galleryUrl, getBackground, getGallery, initBackgroundGallery, openGalleryFolder, refreshGallery, removeGalleryEntry, saveDirectUrlToGallery, setBackgroundUrls, subscribeBackground, uploadBackgroundFile, type BackgroundKind, type BackgroundSource } from '../app/background'
import { useApp } from '../app/context'
import { Select } from './FormControls'

/** 地址行的稳定 id：用数组下标当 key，删一行后 React 会复用错误的输入节点。 */
type Row = {id: string, value: string}
let rowSeed = 0
const newRow = (value = ''): Row => ({id: `row-${++rowSeed}`, value})
const toRows = (urls: string[]): Row[] => [...urls.map(url => newRow(url)), newRow()]

/** 图片与视频背景属于当前浏览器偏好；上传文件保存在 IndexedDB，避免进入部署配置。
    背景记录按材质各存一档，所以切换材质后表单要跟着换成那一档的值。 */
export function BackgroundPreferences() {
  const {ui, notify, material} = useApp()
  const background = useSyncExternalStore(subscribeBackground, getBackground, getBackground)
  const [source, setSource] = useState<BackgroundSource>(background.source)
  const [kind, setKind] = useState<BackgroundKind>(background.kind)
  const [rows, setRows] = useState<Row[]>(() => toRows(background.urls))
  const [busy, setBusy] = useState(false)
  const gallery = useSyncExternalStore(subscribeBackground, getGallery, getGallery)
  const [error, setError] = useState('')

  useEffect(() => { void initBackgroundGallery() }, [])
  useEffect(() => {
    setSource(background.source)
    setKind(background.kind)
    setRows(toRows(background.urls))
  }, [background.source, background.kind, background.urls])

  function changeSource(next: BackgroundSource) {
    setSource(next)
    setError('')
    if (next === 'off') disableBackground()
    /* 切回 URL 档就铺上已填的地址，不必再点一次应用。 */
    if (next === 'url') {
      try { applyRows() } catch (error) { setError((error as Error).message) }
    }
    /* 切回图库档就铺上原来那张；它已被删除时随机抽一张。 */
    if (next === 'upload') applyGalleryEntry(background.entry)
  }

  /** 改某一行；改的是最后一行且非空时，自动补一个空行（填一行就长一行）。 */
  function changeRow(index: number, value: string) {
    setRows(current => {
      const next = [...current]
      next[index] = {...next[index], value}
      if (index === next.length - 1 && value.trim()) next.push(newRow())
      return next
    })
  }
  /** 删掉某一行；删光了留一个空行，交回给「全清空自动回填内置 API」那条规则。 */
  function removeRow(index: number) {
    setRows(current => {
      const next = current.filter((_, position) => position !== index)
      return next.length ? next : [newRow()]
    })
  }

  /** 一行一条 API；全清空时会回填内置随机图 API，所以应用后要把回填结果同步回输入框。 */
  function applyRows() {
    setBackgroundUrls(rows.map(row => row.value), kind)
    setSource('url')
    setError('')
  }

  function applyUrls(event: FormEvent) {
    event.preventDefault()
    try {
      applyRows()
      notify(ui('settings.backgroundApplied'))
    } catch (error) { setError((error as Error).message) }
  }

  /** 一次可传多张：逐张存进图库，最后随机铺一张 —— 这就是"一个文件夹里随机播放"。 */
  async function upload(files: FileList | null) {
    if (!files?.length) return
    setBusy(true); setError('')
    try {
      for (const file of Array.from(files)) await uploadBackgroundFile(file)
      setSource('upload')
      notify(ui('settings.backgroundApplied'))
    } catch (error) { setError((error as Error).message) } finally { setBusy(false) }
  }
  async function saveDirect() {
    setBusy(true); setError('')
    try {
      await saveDirectUrlToGallery()
      notify(ui('settings.backgroundSaved'))
    } catch (error) { setError((error as Error).message) } finally { setBusy(false) }
  }
  async function openFolder() {
    setError('')
    try { await openGalleryFolder() }
    catch (error) { setError((error as Error).message) }
  }
  async function dropEntry(identifier: string) {
    setBusy(true); setError('')
    try { await removeGalleryEntry(identifier); await refreshGallery() }
    catch (error) { setError((error as Error).message) } finally { setBusy(false) }
  }

  return <div className="field-row background-field">
    <div className="field-label">
      <label htmlFor="ui-background-source">{ui('settings.background')}</label>
      <p>{ui('settings.backgroundHelp')}</p>
    </div>
    <div className="field-control background-control">
      <Select id="ui-background-source" value={source} onChange={event => changeSource(event.target.value as BackgroundSource)}>
        {/* 普通材质默认关背景，所以「关闭」只在这一档出现（玻璃材质默认就带背景）。 */}
        {material === 'plain' && <option value="off">{ui('settings.backgroundOff')}</option>}
        <option value="url">{ui('settings.backgroundUrl')}</option>
        <option value="upload">{ui('settings.backgroundUpload')}</option>
      </Select>
      {source === 'url' && <form className="background-url-form" onSubmit={applyUrls}>
        <div className="background-url-rows">
          {rows.map((row, index) => <div className="background-url-row" key={row.id}>
            <input
              type="url"
              aria-label={ui('settings.backgroundUrl')}
              maxLength={2048}
              value={row.value}
              placeholder={index === 0 ? DEFAULT_BACKGROUND_URLS[0] : ''}
              onChange={event => changeRow(index, event.target.value)}
            />
            <button type="button" className="background-url-remove" aria-label={ui('settings.backgroundRemove')} title={ui('settings.backgroundRemove')} onClick={() => removeRow(index)}><X size={14} aria-hidden="true"/></button>
          </div>)}
        </div>
        <div className="background-url-actions">
          <Select aria-label={ui('settings.backgroundType')} value={kind} onChange={event => setKind(event.target.value as BackgroundKind)}>
            <option value="image">{ui('settings.backgroundImage')}</option>
            <option value="video">{ui('settings.backgroundVideo')}</option>
          </Select>
          <button type="button" className="button subtle" onClick={() => { setRows(toRows(DEFAULT_BACKGROUND_URLS)); setError('') }}>
            <ListPlus size={14} aria-hidden="true"/>{ui('settings.backgroundUseBuiltIn')}
          </button>
        </div>
        <button className="button primary background-apply" type="submit">{ui('settings.backgroundApply')}</button>
      </form>}
      {/* 直链行：显示解析到的真实地址，可打开、可存进图库 —— 存的与看到的是同一张图。 */}
      {source === 'url' && <div className="background-direct">
        <label htmlFor="ui-background-direct">{ui('settings.backgroundDirect')}</label>
        <input
          id="ui-background-direct"
          readOnly
          value={background.directUrl || (background.resolving ? ui('settings.backgroundResolving') : ui('settings.backgroundUnresolved'))}
        />
        <div className="background-direct-actions">
          <a className="button subtle" href={background.directUrl || undefined} target="_blank" rel="noreferrer" aria-disabled={!background.directUrl} onClick={event => { if (!background.directUrl) event.preventDefault() }}>
            <ExternalLink size={14} aria-hidden="true"/>{ui('settings.backgroundOpen')}
          </a>
          <button type="button" className="button subtle" disabled={!background.directUrl || busy} onClick={() => void saveDirect()}>
            <BookmarkPlus size={14} aria-hidden="true"/>{ui('settings.backgroundSaveToGallery')}
          </button>
        </div>
        {background.resolveError && <p className="background-error" role="status">{ui('settings.backgroundResolveFailed')}：{background.resolveError}</p>}
      </div>}
      {source === 'upload' && <div className="background-gallery">
        <label className="background-upload">
          <input className="background-upload-input" type="file" accept="image/*,video/*" multiple disabled={busy} onChange={event => {
            void upload(event.target.files)
            event.target.value = ''
          }}/>
          <span className="background-upload-icon" aria-hidden="true"><Upload size={19}/></span>
          <span className="background-upload-copy">
            <strong>{busy ? ui('settings.backgroundSaving') : ui('settings.backgroundUploadMany')}</strong>
            <small>{ui('settings.backgroundLimit')}</small>
          </span>
        </label>
        <div className="background-gallery-head">
          <button type="button" className="button subtle" disabled={busy} onClick={() => void openFolder()}>
            <FolderOpen size={14} aria-hidden="true"/>{ui('settings.backgroundGallery')}（{gallery.length}）
          </button>
          <button type="button" className="button subtle" disabled={gallery.length < 2} onClick={() => applyGalleryEntry()}>
            <Shuffle size={14} aria-hidden="true"/>{ui('settings.backgroundShuffle')}
          </button>
        </div>
        {gallery.length ? <ul className="background-gallery-list">
          {gallery.map(entry => <li key={entry.id} className={entry.id === background.entry ? 'active' : undefined}>
            {entry.kind === 'video' ? <span className="background-gallery-icon">{ui('settings.backgroundVideo')}</span> : <img src={galleryUrl(entry.id)} alt=""/>}
            <span className="background-gallery-name" title={entry.name}>{entry.name}</span>
            <button type="button" className="background-url-remove" aria-label={ui('settings.backgroundDelete')} title={ui('settings.backgroundDelete')} disabled={busy} onClick={() => void dropEntry(entry.id)}><X size={14} aria-hidden="true"/></button>
          </li>)}
        </ul> : <p className="background-url-hint">{ui('settings.backgroundGalleryEmpty')}</p>}
      </div>}
      {error && <p className="background-error" role="alert">{error}</p>}
    </div>
  </div>
}

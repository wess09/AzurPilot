import {createContext, useContext, useEffect, useSyncExternalStore, type ReactNode} from 'react'
import {api} from '../api/client'
import type {BackgroundGalleryEntry} from '../api/types'
import {applyGalleryEntry, captureBackgroundSelection, enterGallery, getBackground, subscribeBackground, migrateStoredUpload, reconcileGallery, removeGalleryEntry, saveDirectUrlToGallery, uploadBackgroundFile} from './background'
import {useConnection} from './context'
import {usePageRead} from './usePageRead'

const readGallery = async () => {
  await migrateStoredUpload()
  return api.request('background.gallery.list', {})
}

type GalleryContextValue = {
  entries: BackgroundGalleryEntry[] | undefined
  ready: boolean
  error: string
  reload: () => void
  select: (id?: string) => void
  upload: (files: File[]) => Promise<void>
  saveDirect: () => Promise<void>
  remove: (id: string) => Promise<void>
}
const GalleryContext = createContext<GalleryContextValue | null>(null)

export function BackgroundGalleryProvider({children}: {children: ReactNode}) {
  const connection = useConnection()
  const read = usePageRead('background.gallery', connection === 'ready', readGallery)
  const background = useSyncExternalStore(subscribeBackground, getBackground, getBackground)
  useEffect(() => {
    if (connection === 'ready' && read.data && !read.busy && !read.error) reconcileGallery(read.data)
  }, [connection, read.data, read.busy, read.error, background.source, background.entry, background.legacy])

  const select = (id?: string) => {
    const entries = read.data
    if (!entries) { enterGallery(id); return }
    const entry = (id ? entries.find(item => item.id === id) : undefined) ?? entries[Math.floor(Math.random() * entries.length)]
    if (entry) applyGalleryEntry(entry)
    else enterGallery()
  }
  const upsert = (entry: BackgroundGalleryEntry) => read.setData(previous => previous && [...previous.filter(item => item.id !== entry.id), entry])
  const upload = async (files: File[]) => {
    const isCurrent = captureBackgroundSelection()
    let last: BackgroundGalleryEntry | undefined
    try {
      for (const file of files) {
        last = await uploadBackgroundFile(file)
        upsert(last)
      }
    } finally {
      if (last) {
        if (isCurrent()) applyGalleryEntry(last)
        read.reload()
      }
    }
  }
  const saveDirect = async () => {
    const entry = await saveDirectUrlToGallery()
    upsert(entry)
    read.reload()
  }
  const remove = async (id: string) => {
    await removeGalleryEntry(id)
    read.setData(previous => previous?.filter(item => item.id !== id))
    if (getBackground().source === 'upload' && getBackground().entry === id) enterGallery()
    read.reload()
  }
  return <GalleryContext.Provider value={{entries: read.data, ready: read.ready, error: read.error, reload: read.reload, select, upload, saveDirect, remove}}>{children}</GalleryContext.Provider>
}

export function useBackgroundGallery() {
  const value = useContext(GalleryContext)
  if (!value) throw new Error('BackgroundGalleryProvider is missing')
  return value
}

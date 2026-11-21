import { useCallback, useEffect, useSyncExternalStore } from 'react'
import { api } from '../api/client'
import { getBackground, publishResolvedBackground, subscribeBackground } from './background'
import { useConnection } from './context'
import { usePageRead } from './usePageRead'

/** Resolve a wallpaper URL with credentials from the active WebUI session. */
export async function loadBackgroundUrl(url: string) {
  const {token} = await api.request('background.access', {})
  const {final_url} = await api.request('background.resolve', {url})
  const media = new URLSearchParams({url: final_url, token})
  return {directUrl: final_url, assetUrl: '/api/v1/background/media?' + media}
}

/** Keep the resolved media and the settings preview on the same root-owned read. */
export function BackgroundUrlResolver() {
  const background = useSyncExternalStore(subscribeBackground, getBackground, getBackground)
  const connection = useConnection()
  const url = background.source === 'url' ? background.urls[background.active] ?? '' : ''
  const generation = background.urlGeneration
  const load = useCallback(() => loadBackgroundUrl(url), [url])
  const {data, error} = usePageRead(String(generation), connection === 'ready' && !!url, load)

  useEffect(() => {
    if (url && (data || error)) publishResolvedBackground(generation, data, error)
  }, [generation, url, data, error])

  return null
}

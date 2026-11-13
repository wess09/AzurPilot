import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import { useApp, useConnection } from '../app/context'
import { pluginAsset, type InstalledPlugin } from './types'

interface FrameProps {
  plugin: InstalledPlugin
  entry: string
  title: string
  instance?: string
  scheduler?: {state: object; toggle: () => void; disabled: boolean}
  navigation?: {items: {title: string; to: string}[]; go: (to: string) => void}
  fallback?: ReactNode
}

export function PluginFrame({plugin, entry, title, instance, scheduler, navigation, fallback}: FrameProps) {
  const {ui, language, resolvedMode, schema} = useApp()
  const connection = useConnection()
  const frame = useRef<HTMLIFrameElement>(null)
  const channel = useRef<MessagePort | null>(null)
  const controls = useRef(scheduler)
  controls.current = scheduler
  const navigationRef = useRef(navigation)
  navigationRef.current = navigation
  const online = useRef(connection === 'ready')
  online.current = connection === 'ready'
  const [connected, setConnected] = useState(false)
  const [failed, setFailed] = useState(false)
  const [nonce] = useState(() => Array.from(crypto.getRandomValues(new Uint32Array(4)), n => n.toString(16).padStart(8, '0')).join(''))
  const source = pluginAsset(plugin, entry) + '#apu=' + nonce

  useEffect(() => {
    if (connected) return
    const timer = window.setTimeout(() => setFailed(true), 8000)
    return () => window.clearTimeout(timer)
  }, [connected])
  useEffect(() => {
    function handshake(event: MessageEvent) {
      if (failed || channel.current || event.source !== frame.current?.contentWindow || event.origin !== 'null'
          || event.data?.type !== 'apu.hello' || event.data.nonce !== nonce) return
      connect(event.source as Window)
    }
    window.addEventListener('message', handshake)
    return () => window.removeEventListener('message', handshake)
  })
  useEffect(() => () => {channel.current?.close(); channel.current = null}, [])
  useEffect(() => {
    if (!failed) return
    channel.current?.close()
    channel.current = null
  }, [failed])
  useEffect(() => {
    if (connected && scheduler) channel.current?.postMessage({type: 'scheduler.state', data: scheduler.state})
  }, [connected, scheduler])
  useEffect(() => {
    if (connected) channel.current?.postMessage({type: 'appearance', data: {language, mode: resolvedMode}})
  }, [connected, language, resolvedMode])
  useEffect(() => {
    if (connected && navigation) channel.current?.postMessage({type: 'navigation.items', data: navigation.items})
  }, [connected, navigation])

  function connect(target: Window) {
    const {port1, port2} = new MessageChannel()
    channel.current = port1
    const permissions = plugin.manifest.permissions ?? []
    let ready = false
    port1.onmessage = async ({data}) => {
      if (channel.current !== port1 || !data || typeof data !== 'object') return
      if (data.type === 'apu.ready') {
        ready = true
        setConnected(true)
        return
      }
      if (!ready || typeof data.id !== 'string' || data.id.length > 100) return
      const reply = (value: unknown, error?: string) => {
        if (channel.current === port1) port1.postMessage({id: data.id, value, error})
      }
      try {
        switch (data.method) {
          case 'instance.current':
            reply(permissions.includes('instance.read') ? instance ?? null : null)
            return
          case 'instance.overview': {
            if (!instance || !permissions.includes('instance.read')) break
            const overview = await api.request('overview.get', {instance})
            const names = new Set(Object.values(schema?.menu ?? {}).flatMap(group => group.tasks))
            reply({instance: overview.instance, status: overview.status, resources: overview.resources,
              tasks: overview.tasks.map(({name, state, nextRun}) => ({name, state, nextRun})),
              taskNames: [...names]})
            return
          }
          case 'storage.get':
          case 'storage.set':
          case 'storage.delete': {
            if (!permissions.includes('storage') || typeof data.key !== 'string' || !data.key || data.key.length > 120) break
            const action = data.method === 'storage.get' ? 'get' : data.method === 'storage.set' ? 'set' : 'delete'
            if (action === 'set' && (JSON.stringify(data.value)?.length ?? 0) > 65536) throw new Error(ui('plugins.storageLimit'))
            const {value} = await api.request(action === 'get' ? 'plugins.storage.get' : 'plugins.storage.write',
              {id: plugin.manifest.id, instance: instance ?? null, key: data.key, action, value: data.value})
            reply(value)
            return
          }
          case 'scheduler.toggle':
            if (!online.current || !permissions.includes('scheduler.control') || !controls.current || controls.current.disabled) break
            controls.current.toggle()
            reply(null)
            return
          case 'navigation.open': {
            const target = navigationRef.current
            if (!target || !target.items.some(item => item.to === data.to)) break
            target.go(data.to)
            reply(null)
            return
          }
        }
        reply(null, ui('plugins.operationUnavailable'))
      } catch (error) { reply(null, (error as Error).message) }
    }
    target.postMessage({type: 'apu.connect', apiVersion: 1}, '*', [port2])
  }

  if (failed) return fallback ?? <p role="alert">{ui('plugins.viewFailed')}</p>
  return <div className="apu-frame">
    {!connected && <p role="status" className="apu-frame-loading">{ui('plugins.loadingView')}</p>}
    <iframe ref={frame} src={source} title={title} sandbox="allow-scripts" referrerPolicy="no-referrer"
      className={connected ? '' : 'apu-frame-pending'}/>
  </div>
}

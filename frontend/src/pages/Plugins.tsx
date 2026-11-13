import { useRef, useState } from 'react'
import { Upload } from 'lucide-react'
import { useApp, useConnection } from '../app/context'
import { ErrorBox, Loading, Modal } from '../components/ui'
import { Button } from '../components/ui/button'
import { usePlugins } from '../plugins/context'
import type { InstalledPlugin } from '../plugins/types'

// 导入是主操作。已安装插件按名称、状态和操作排列，沿用设置面板的颜色与间距。
export function Plugins() {
  const {ui} = useApp()
  const connection = useConnection()
  const {plugins, ready, error, refresh, request, theme, setTheme} = usePlugins()
  const fileInput = useRef<HTMLInputElement>(null)
  const busyRef = useRef(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [remove, setRemove] = useState<InstalledPlugin>()
  const disabled = busy || connection !== 'ready'

  async function run(path: string, options: RequestInit, afterSuccess?: () => void) {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setMessage('')
    try {
      await request(path, options)
      afterSuccess?.()
      setRemove(undefined)
    } catch (failure) {
      setMessage((failure as Error).message)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  return <div className="settings-page">
    <h1 className="legacy-sr-title">{ui('nav.plugins')}</h1>
    <section className="panel config-group">
      <div className="panel-heading flex flex-wrap items-center justify-between gap-3">
        <h2 className="m-0">{ui('plugins.installed')}</h2>
        <input ref={fileInput} type="file" accept=".apu" hidden aria-label={ui('plugins.import')} onChange={event => {
          const file = event.currentTarget.files?.[0]
          event.currentTarget.value = ''
          if (!file) return
          if (!file.name.toLowerCase().endsWith('.apu')) {setMessage(ui('plugins.fileType')); return}
          void run('', {method: 'POST', body: file})
        }}/>
        <Button type="button" disabled={disabled} onClick={() => fileInput.current?.click()}><Upload aria-hidden="true"/>{ui('plugins.import')}</Button>
      </div>
      {message && <div className="px-4 pb-4"><ErrorBox message={message}/></div>}
      {error && <div className="px-4 pb-4"><ErrorBox message={error} retry={refresh}/></div>}
      {!ready && !error && <Loading/>}
      {ready && plugins.length === 0 && <p className="m-0 border-t border-[var(--border)] px-4 py-4 text-sm text-[var(--muted)]">{ui('plugins.empty')}</p>}
      {plugins.map(plugin => {
        const {manifest, enabled} = plugin
        const path = '/' + encodeURIComponent(manifest.id)
        const selected = theme?.manifest.id === manifest.id
        return <article key={manifest.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] px-4 py-4">
          <div className="min-w-0 break-words">
            <h3 className="m-0 text-sm font-semibold">{manifest.name}</h3>
            <p className="m-0 text-sm text-[var(--muted)]">{manifest.version} · {ui(enabled ? 'plugins.enabled' : 'plugins.disabled')}</p>
            {!!manifest.permissions?.length && <p className="m-0 text-xs text-[var(--muted)]">
              {manifest.permissions.map(permission => ui(`plugins.permission.${permission}`)).join(' · ')}
            </p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => void run(path, {
              method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled: !enabled}),
            }, !enabled && manifest.theme ? () => setTheme(manifest.id) : undefined)}>{ui(enabled ? 'plugins.disable' : 'plugins.enable')}</Button>
            {enabled && manifest.theme && <Button type="button" variant="outline" size="sm" aria-pressed={selected}
              onClick={() => setTheme(selected ? '' : manifest.id)}>{ui(selected ? 'plugins.restoreTheme' : 'plugins.applyTheme')}</Button>}
            <Button type="button" variant="ghost" size="sm" disabled={disabled} onClick={() => setRemove(plugin)}>{ui('plugins.remove')}</Button>
          </div>
        </article>
      })}
    </section>
    {remove && <Modal title={ui('plugins.remove')} onClose={() => {if (!busy) setRemove(undefined)}}>
      <p>{ui('plugins.removePrompt', {name: remove.manifest.name})}</p>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" disabled={busy} onClick={() => setRemove(undefined)}>{ui('common.cancel')}</Button>
        <Button type="button" variant="destructive" disabled={disabled}
          onClick={() => void run('/' + encodeURIComponent(remove.manifest.id), {method: 'DELETE'})}>{ui('plugins.remove')}</Button>
      </div>
    </Modal>}
  </div>
}

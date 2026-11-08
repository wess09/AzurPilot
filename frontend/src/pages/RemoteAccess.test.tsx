import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import { RemoteAccess } from './RemoteAccess'
import { translateUi } from '../i18n'

// vi.mock 的工厂会被提升到 import 之前，模块级数据必须走 vi.hoisted。
const state = vi.hoisted(() => ({
  groups: [
    {key: 'Git', label: 'Git', fields: []},
    {key: 'RemoteAccess', label: 'RemoteAccess', fields: []},
    {key: 'Webui', label: 'Webui', fields: []},
  ],
  queue: {change: () => {}, retry: () => {}},
  remote: {enabled: true, state: 'waiting_peer', address: '', error: ''},
}))

vi.mock('../app/useDeploySettings', () => ({
  useDeploySettings: () => ({
    data: {groups: state.groups, notice: '', demo: false, remote: state.remote},
    error: '',
    edits: {edits: {}, storageError: ''},
    queue: state.queue,
  }),
}))

function createMockContext(): AppContextValue {
  return {
    instancesLoaded: true,
    instances: [],
    refresh: async () => {},
    t: (key: string) => key,
    ui: (key, params) => translateUi('zh-CN', key, params),
    notify: () => {},
    previewEnabled: false,
    setPreviewEnabled: () => {},
    devMode: false,
    setDevMode: () => {},
    theme: 'legacy-light',
    setTheme: () => {},
    material: 'glass',
    setMaterial: () => {},
    resolvedMode: 'light',
    customPalettes: [],
    saveCustomPalette: () => {},
    deleteCustomPalette: () => {},
    language: 'zh-CN',
    setLanguage: () => {},
  }
}

function render() {
  return renderToStaticMarkup(
    <AppContext.Provider value={createMockContext()}>
      <RemoteAccess />
    </AppContext.Provider>
  )
}

describe('远程访问页', () => {
  beforeEach(() => {
    state.remote = {enabled: true, state: 'waiting_peer', address: '', error: ''}
  })

  it('就绪时展示地址与复制按钮', () => {
    state.remote = {enabled: true, state: 'waiting_peer', address: 'https://tunnel.example.com/p2p/example-peer-id', error: ''}
    const html = render()
    expect(html).toContain('https://tunnel.example.com/p2p/example-peer-id')
    expect(html).toContain('复制')
    expect(html).toContain('已连接')
  })

  it('未启用时给出引导，不展示地址', () => {
    state.remote = {enabled: false, state: 'stopped', address: '', error: ''}
    const html = render()
    expect(html).toContain('未启用')
    expect(html).toContain('打开下面的「启用远程访问」')
    expect(html).not.toContain('复制')
  })

  it('连接失败时展示状态与错误信息', () => {
    state.remote = {enabled: true, state: 'failed', address: '', error: 'ssh_not_found'}
    const html = render()
    expect(html).toContain('连接失败')
    expect(html).toContain('ssh_not_found')
  })

  it('认领远程访问与 WebUI 两组设置，不含系统级分组', () => {
    const html = render()
    expect(html).toContain('Gui.DeploySetting.GroupRemoteAccess')
    expect(html).toContain('Gui.DeploySetting.GroupWebui')
    expect(html).not.toContain('Gui.DeploySetting.GroupGit')
  })
})

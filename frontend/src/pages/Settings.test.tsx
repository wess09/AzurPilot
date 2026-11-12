import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import { Settings } from './Settings'
import { translateUi } from '../i18n'

// vi.mock 的工厂会被提升到 import 之前，模块级数据必须走 vi.hoisted。
const {groups, queue} = vi.hoisted(() => ({
  groups: [
    {key: 'Git', label: 'Git', fields: [{key: 'Branch', type: 'string', label: 'Branch', help: 'help', value: 'dev', options: []}]},
    {key: 'RemoteAccess', label: 'RemoteAccess', fields: []},
    {key: 'Webui', label: 'Webui', fields: []},
  ],
  queue: {change: () => {}, retry: () => {}},
}))

vi.mock('../app/useDeploySettings', () => ({
  useDeploySettings: () => ({
    data: {groups, notice: '', demo: false},
    error: '',
    edits: {edits: {}, storageError: ''},
    queue,
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
      <Settings />
    </AppContext.Provider>
  )
}

describe('系统设置页分组归属', () => {
  it('渲染系统级分组', () => {
    expect(render()).toContain('Gui.DeploySetting.GroupGit')
  })

  it('远程访问与 WebUI 分组在远程访问页，这里不再出现', () => {
    const html = render()
    expect(html).not.toContain('Gui.DeploySetting.GroupRemoteAccess')
    expect(html).not.toContain('Gui.DeploySetting.GroupWebui')
  })

  it('外观偏好已移到界面设置页', () => {
    const html = render()
    expect(html).not.toContain('自定义背景')
    expect(html).not.toContain('配色方案')
  })

  it('启动器卡片排在第一张', () => {
    const html = render()
    const launcher = html.indexOf('Gui.Launcher.StartupTitle')
    expect(launcher).toBeGreaterThanOrEqual(0)
    expect(launcher).toBeLessThan(html.indexOf('Gui.DeploySetting.GroupGit'))
  })
})

/**
 * @fileoverview SidebarTransition 的渲染回归：常规包裹渲染与减弱动效模式下的降级。
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { SidebarTransition } from './SidebarTransition'
import { setMotionReduced } from '../app/motionPrefs'

describe('SidebarTransition', () => {
  beforeEach(() => {
    // motionPrefs 是模块级单例，后面的用例会打开减弱动效；这里复位防止用例间泄漏。
    setMotionReduced(false)
  })

  it('renders children under the animated wrapper', () => {
    const html = renderToStaticMarkup(
      <SidebarTransition viewKey="global">
        <div data-testid="global-nav">Global Navigation</div>
      </SidebarTransition>
    )

    expect(html).toContain('sidebar-transition-wrap')
    expect(html).toContain('sidebar-transition-pane')
    expect(html).toContain('Global Navigation')
  })

  it('renders correctly with instance view key', () => {
    const html = renderToStaticMarkup(
      <SidebarTransition viewKey="instance:demo-main">
        <div>Instance Content</div>
      </SidebarTransition>
    )
    expect(html).toContain('Instance Content')
  })

  it('renders cleanly in reduced motion mode', () => {
    setMotionReduced(true)
    const html = renderToStaticMarkup(
      <SidebarTransition viewKey="global">
        <div>Reduced Global</div>
      </SidebarTransition>
    )
    expect(html).toContain('Reduced Global')
  })
})

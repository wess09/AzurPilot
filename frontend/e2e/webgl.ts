import type { Page } from '@playwright/test'

/** 固定玻璃材质探测使用的渲染器，保留页面上的其他 Canvas API。 */
export function mockWebGLRenderer(page: Page, renderer: string) {
  return page.addInitScript(name => {
    const getContext = HTMLCanvasElement.prototype.getContext
    Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
      value(this: HTMLCanvasElement, type: string, options?: WebGLContextAttributes) {
        if (type === 'webgl' && options?.failIfMajorPerformanceCaveat) {
          return {RENDERER: 0x1f01, getExtension: () => null, getParameter: () => name}
        }
        return Reflect.apply(getContext, this, [type, options])
      },
    })
  }, renderer)
}

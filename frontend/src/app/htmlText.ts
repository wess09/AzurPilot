/**
 * @fileoverview React 帮助文本展示前的 HTML 纯文本化。
 */
/**
 * 将仅用于 React 文本节点展示的 HTML 帮助文本转换为纯文本。
 *
 * 浏览器环境使用 DOMParser 读取 textContent；SSR / Node 环境没有 DOMParser 时
 * 直接返回原字符串，由 React 文本节点负责转义。该函数不承担 HTML 清洗职责。
 */
export function htmlToPlainText(value: string): string {
  if (!value || typeof DOMParser === 'undefined') return value
  const document = new DOMParser().parseFromString(value, 'text/html')
  return document.body.textContent ?? ''
}

/**
 * @fileoverview 画布编辑器的键盘命令识别：把快捷键事件翻译成编辑命令，并判断焦点是否在文本控件内。
 */

/** 画布快捷键；文本控件由浏览器处理自己的复制、粘贴和删除。 */
type EditorCommand = 'copy' | 'cut' | 'paste' | 'undo' | 'redo' | 'delete' | 'all' | 'clear'
/** 把键盘事件翻译成画布编辑命令；带 Alt 时不拦截（留给系统/浏览器快捷键），非编辑键返回 undefined。 */
export function editorCommand(event: {key:string; ctrlKey:boolean; metaKey:boolean; shiftKey:boolean; altKey:boolean}): EditorCommand | undefined {
  if (event.altKey) return
  const key = event.key.toLowerCase(), modifier = event.ctrlKey || event.metaKey
  if (modifier) return ({c:'copy', x:'cut', v:'paste', a:'all', y:'redo', z:event.shiftKey ? 'redo' : 'undo'} as Record<string,EditorCommand>)[key]
  if (key === 'backspace' || key === 'delete') return 'delete'
  if (key === 'escape') return 'clear'
}
/** 判断事件目标是否落在可输入文本的控件里，调用方据此跳过画布快捷键。 */
export function editingText(target: EventTarget | null) {
  return target instanceof Element && !!target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], [role="textbox"]')
}

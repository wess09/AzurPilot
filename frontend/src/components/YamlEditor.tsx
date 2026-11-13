/**
 * @fileoverview YAML 配置文本代码编辑器组件。
 */

import { useEffect, useRef } from 'react'
import { Annotation, Compartment, EditorState } from '@codemirror/state'
import { EditorView, keymap, lineNumbers, highlightActiveLine } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
import { HighlightStyle, syntaxHighlighting, bracketMatching } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import { yaml } from '@codemirror/lang-yaml'
import { useApp } from '../app/context'

const colors = HighlightStyle.define([
  {tag: [tags.propertyName, tags.definition(tags.propertyName)], color: 'var(--syntax-key)'},
  {tag: tags.string, color: 'var(--syntax-string)'},
  {tag: [tags.content, tags.number, tags.bool, tags.null, tags.labelName, tags.typeName, tags.keyword], color: 'var(--syntax-value)'},
  {tag: tags.comment, color: 'var(--syntax-comment)', fontStyle: 'italic'},
  {tag: [tags.punctuation, tags.meta], color: 'var(--syntax-punctuation)'},
])
const externalChange = Annotation.define<boolean>()

/**
 * CodeMirror 6 的 YAML 受控编辑器。
 *
 * 编辑器实例只在 id/label 变化时重建；value 变化经外部回填写进文档，回填事务带
 * 外部变更注解，不会触发 onChange——只有用户的输入才进入表单草稿。disabled 与
 * invalid 用 Compartment 动态重配，避免重建编辑器丢掉历史与光标。
 */
export function YamlEditor({id, value, onChange, disabled = false, label, invalid}: {
  id: string; value: string; onChange: (value: string) => void; disabled?: boolean; label: string; invalid?: boolean
}) {
  const {ui} = useApp()
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView>(undefined)
  const change = useRef(onChange)
  const initial = useRef(value)
  const editable = useRef(new Compartment())
  change.current = onChange
  useEffect(() => {
    const editor = new EditorView({
      parent: host.current!,
      state: EditorState.create({doc: initial.current, extensions: [
        yaml(), lineNumbers(), history(), bracketMatching(), highlightActiveLine(),
        syntaxHighlighting(colors), EditorView.lineWrapping,
        // 保留 Tab 的浏览器焦点导航；YAML 输入使用语言扩展自动缩进。
        keymap.of([...defaultKeymap, ...historyKeymap]),
        editable.current.of([]),
        EditorView.contentAttributes.of({id, 'aria-label': label, 'aria-multiline': 'true', role: 'textbox'}),
        EditorView.updateListener.of(update => {
          if (update.docChanged && update.transactions.some(transaction => !transaction.annotation(externalChange))) change.current(update.state.doc.toString())
        }),
      ]}),
    })
    view.current = editor
    return () => {editor.destroy(); view.current = undefined}
  }, [id, label])
  useEffect(() => {
    const editor = view.current
    // 外部回填不能再次触发表单变更，其余编辑命令均应进入草稿。
    if (editor && editor.state.doc.toString() !== value) editor.dispatch({changes: {from: 0, to: editor.state.doc.length, insert: value}, annotations: externalChange.of(true)})
  }, [value, id, label])
  useEffect(() => {
    view.current?.dispatch({effects: editable.current.reconfigure([
      EditorState.readOnly.of(disabled), EditorView.editable.of(!disabled),
      EditorView.contentAttributes.of({'aria-disabled': String(disabled), 'aria-invalid': String(!!invalid), ...(invalid ? {'aria-describedby': `${id}-status`} : {})}),
    ])})
  }, [disabled, invalid, id, label])
  return <div
    aria-invalid={invalid || undefined}
    className={`yaml-editor flex flex-col overflow-hidden rounded-md border border-input bg-transparent shadow-xs transition-[color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-[3px] aria-invalid:ring-destructive/20 ${disabled ? 'opacity-60' : ''}`}
  >
    <div className="border-b border-input px-3 py-1.5 text-xs text-muted-foreground">{ui('field.yaml')}</div>
    <div ref={host}/>
  </div>
}

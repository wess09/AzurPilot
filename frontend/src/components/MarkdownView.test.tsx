import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MarkdownView } from './MarkdownView'

describe('MarkdownView 组件（基于 marked + katex + dompurify）', () => {
  it('正确渲染基础 Markdown、链接与任务清单', () => {
    const md = `
# 标题一
**粗体**与*斜体*，还有[GitHub链接](https://github.com/wess09/AzurPilot)。

- [x] 已完成项
- [ ] 待完成项
`
    const html = renderToStaticMarkup(<MarkdownView content={md} />)
    expect(html).toContain('<h1>标题一</h1>')
    expect(html).toContain('<strong>粗体</strong>')
    expect(html).toContain('<em>斜体</em>')
    expect(html).toContain('href="https://github.com/wess09/AzurPilot"')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('type="checkbox"')
  })

  it('正确渲染 LaTeX 公式（行内与块级公式通过 KaTeX 编译）', () => {
    const md = '行内公式：$E = mc^2$，以及块级公式：\n\n$$\\frac{a}{b}$$'
    const html = renderToStaticMarkup(<MarkdownView content={md} />)

    // KaTeX 会生成 katex 类或 katex-html 容器，断言只盯关键词，不锁具体标记。
    expect(html).toContain('katex')
    expect(html).toContain('md-math-inline')
    expect(html).toContain('md-math-block')
  })

  it('正确渲染安全的 HTML 标签与折叠 details', () => {
    const md = `
使用快捷键 <kbd>Ctrl</kbd> + <kbd>C</kbd>，这是<mark>高亮文本</mark>，化学式 H<sub>2</sub>O，上标 x<sup>2</sup>。
<font color="#34d399">彩色文本</font>

<details>
<summary>点击展开折叠内容</summary>
详细内部信息
</details>
`
    const html = renderToStaticMarkup(<MarkdownView content={md} />)
    expect(html).toContain('<kbd>Ctrl</kbd>')
    expect(html).toContain('<mark>高亮文本</mark>')
    expect(html).toContain('<sub>2</sub>')
    expect(html).toContain('<sup>2</sup>')
    expect(html).toContain('color="#34d399"')
    expect(html).toContain('<details>')
    expect(html).toContain('<summary>点击展开折叠内容</summary>')
    expect(html).toContain('详细内部信息')
  })

  it('严格净化恶意 HTML 注入（DOMPurify 拦截 script 和事件属性）', () => {
    const dangerous = '<script>window.pwned=true</script><img src="x" onerror="alert(1)" />安全内容'
    const html = renderToStaticMarkup(<MarkdownView content={dangerous} />)

    expect(html).not.toContain('<script>')
    expect(html).not.toContain('window.pwned')
    expect(html).not.toContain('onerror')
    expect(html).toContain('安全内容')
  })

  it('正确渲染 GitHub 风格提示块 (> [!NOTE] / > [!TIP])', () => {
    const alertMd = `
> [!NOTE]
> 这是一个说明信息

> [!TIP]
> 保持分辨率为 1280x720
`
    const html = renderToStaticMarkup(<MarkdownView content={alertMd} />)
    expect(html).toContain('md-alert-note')
    expect(html).toContain('md-alert-tip')
    expect(html).toContain('说明')
    expect(html).toContain('提示')
  })

  it('正确渲染代码块语法高亮与复制属性', () => {
    const codeMd = `
\`\`\`python
def start_bot(name: str):
    print(f"Bot {name} started")
\`\`\`
`
    const html = renderToStaticMarkup(<MarkdownView content={codeMd} />)
    expect(html).toContain('md-code-wrap')
    expect(html).toContain('md-code-lang')
    expect(html).toContain('python')
    expect(html).toContain('md-code-copy')
    expect(html).toContain('hljs')
  })
})

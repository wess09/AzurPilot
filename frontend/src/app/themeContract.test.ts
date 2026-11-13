import { describe, expect, it } from 'vitest'
import legacyPalette from '../styles/legacy-palette.css?raw'
import materialAxis from '../styles/theme-material.css?raw'
import legacySkin from '../styles/legacy.css?raw'

const palettes = [legacyPalette]

// 有材质轴的家族必须真的声明玻璃取值：漏了就只有普通一种观感，
// 「玻璃 / 普通」两个选项会长得一模一样，而不会报任何错。
describe('材质轴取值', () => {
  // 磨砂参数只在一级面声明一次，旧的 --theme-glass-* 键改为委托，避免两套同值 token 以后漂移。
  it('现代主题声明磨砂参数，并将旧键委托给一级面', () => {
    expect(legacyPalette).toMatch(/--theme-surface-blur:\s*(?!0px)\d/)
    expect(legacyPalette).toMatch(/--theme-surface-saturation:\s*\d/)
    expect(legacyPalette).toMatch(/--theme-glass-blur:\s*var\(--theme-surface-blur\)/)
    expect(legacyPalette).toMatch(/--theme-material-filter:\s*var\(--theme-surface-filter\)/)
    expect(legacyPalette).toMatch(/--theme-glass:\s*var\(--theme-surface-bg\)/)
  })

  it('普通材质分支把玻璃压回不透明与无滤镜', () => {
    expect(materialAxis).toMatch(/:root\[data-material='plain'\]/)
    expect(materialAxis).toMatch(/--theme-material-filter:\s*none/)
    expect(materialAxis).toMatch(/--theme-glass:\s*var\(--surface\)/)
  })

  it('现代主题引入材质轴样式表', () => {
    expect(legacySkin).toContain('theme-material.css')
  })
})

// 拥有层参数键的区域：四个层级（一级面、二级贴片、三级嵌面、控件）与四个按位置命名的区域
// （侧栏、顶栏、弹窗、菜单）。每区各 8 键——参数键（alpha/blur/saturation/radius）由旋钮写入，
// 合成键（bg/filter/edge/shadow）由皮肤消费。侧栏与顶栏不在旋钮目录里（见 `themeKnobs` 的 `REGIONS`），
// 但它们的键在，供皮肤直接消费。
const REGIONS = ['surface', 'plate', 'inset', 'control', 'sidebar', 'topbar', 'modal', 'menu'] as const
const REGION_PROPS = ['alpha', 'blur', 'saturation', 'radius', 'bg', 'filter', 'edge', 'shadow'] as const
// 已溶解的语义区：按叠加层重新指派后不再有自己的层参数键——`--theme-segment-border` 这类部件级绘制细节不算。
// `chrome` 已不在此列：顶栏与侧栏的磨砂各自有了区域键，外壳滤镜改为引用侧栏区域键。
const DISSOLVED = ['tab', 'segment'] as const

const declaration = (css: string, key: string) => {

  const needle = `${key}:`
  const start = css.indexOf(needle)
  if (start < 0) return ''
  const valueStart = start + needle.length
  const semicolon = css.indexOf(';', valueStart)
  if (semicolon < 0) return ''
  return css.slice(valueStart, semicolon).trim()
}

describe('三层画布契约', () => {
  it('三个区各八键齐备', () => {
    for (const css of palettes) {
      for (const region of REGIONS) {
        for (const prop of REGION_PROPS) {
          expect(declaration(css, `--theme-${region}-${prop}`), `${region}-${prop}`).not.toBe('')
        }
      }
      for (const region of DISSOLVED) {
        for (const prop of REGION_PROPS) {
          expect(css.includes(`--theme-${region}-${prop}`), `${region}-${prop}`).toBe(false)
        }
      }
    }
  })


  // 各层只声明自己的默认值，不引用别的层。
  it('三层之间不互相继承', () => {
    for (const css of palettes) {
      for (const prop of ['alpha', 'blur', 'saturation'] as const) {
        expect(declaration(css, `--theme-control-${prop}`), `control-${prop}`).not.toContain('var(--theme-surface-')
      }
      expect(declaration(css, '--theme-plate-blur'), 'plate-blur').not.toContain('var(--theme-surface-')
      expect(declaration(css, '--theme-plate-radius'), 'plate-radius').not.toContain('var(--theme-surface-')
    }
  })

  it('合成键由参数键与 surface 合成', () => {
    for (const css of palettes) {
      for (const region of REGIONS) {
        expect(declaration(css, `--theme-${region}-bg`), `${region}-bg`).toContain(`var(--theme-${region}-alpha)`)
        // 扁平族有意把滤镜写成 none：0 半径的模糊仍会单独成合成层，它们连这一层都不建。
        const filter = declaration(css, `--theme-${region}-filter`)
        expect(filter === 'none' || filter.includes(`var(--theme-${region}-blur)`), `${region}-filter`).toBe(true)
      }
    }
  })
})

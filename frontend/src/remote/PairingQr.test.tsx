import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { PairingQr, generateQrSvgData, pairingQrPayload } from './PairingQr'

describe('PairingQr 二维码组件与协议生成', () => {
  const VALID_SECRET = '00112233445566778899aabbccddeeff'

  it('有效 32 位 hex secret 正确生成 azurpilot:// 协议 URI', () => {
    expect(pairingQrPayload(VALID_SECRET)).toBe(
      'azurpilot://pair?secret=00112233445566778899aabbccddeeff',
    )
  })

  it('非法字符或长度不满足 32 位的 secret 抛出校验异常', () => {
    expect(() => pairingQrPayload('')).toThrow('Invalid pairing secret')
    expect(() => pairingQrPayload('not-a-secret')).toThrow('Invalid pairing secret')
    expect(() => pairingQrPayload('00112233445566778899aabbccddeef')).toThrow(
      'Invalid pairing secret',
    )
    expect(() => pairingQrPayload('00112233445566778899aabbccddeeff00')).toThrow(
      'Invalid pairing secret',
    )
    expect(() => pairingQrPayload('00112233445566778899aabbccddeefg')).toThrow(
      'Invalid pairing secret',
    )
  })

  it('矢量数据计算严格满足 4 模块空白安全区（Quiet Zone）', () => {
    const payload = pairingQrPayload(VALID_SECRET)
    const data = generateQrSvgData(payload, 'M', 4)
    // 33 模块 + 4*2 边距 = 41 尺寸。
    expect(data.moduleCount).toBe(33)
    expect(data.margin).toBe(4)
    expect(data.viewBoxSize).toBe(41)
    // 起始绘制点应在 margin 处（x=4）。
    expect(data.pathD).toContain('M 4 4 h 1 v 1 h -1 Z')
  })

  it('正常渲染包含 SVG 二维码与安全底色的结构', () => {
    const html = renderToStaticMarkup(
      <PairingQr secret={VALID_SECRET} label="AzurPilot for Android 配对二维码" />,
    )
    expect(html).toContain('class="pairing-qr"')
    expect(html).toContain('<svg')
    expect(html).toContain('role="img"')
    expect(html).toContain('viewBox="0 0 41 41"')
    expect(html).toContain('fill="#ffffff"')
    expect(html).toContain('aria-label="AzurPilot for Android 配对二维码"')
  })

  it('传入非法 secret 时优雅降级渲染 alert 提示而不崩溃', () => {
    const html = renderToStaticMarkup(
      <PairingQr secret="bad-secret" label="AzurPilot for Android 配对二维码" />,
    )
    expect(html).toContain('pairing-qr-error')
    expect(html).toContain('role="alert"')
    expect(html).toContain('Invalid pairing secret')
    expect(html).not.toContain('<svg')
  })
})

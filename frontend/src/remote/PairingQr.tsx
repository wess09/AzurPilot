/**
 * @fileoverview 配对二维码组件：满足 ISO/IEC 18004 与 GB/T 18284，内置四周各 4 模块的空白安全区（Quiet Zone），
 * 并由外层 .pairing-qr 容器保障 32px 纯白物理留白，阻断背景或边缘对扫码对焦的干扰。
 */
import { useMemo } from 'react'
import qrcode from 'qrcode-generator'
import './pairing-qr.css'

/** 把配对密钥拼成 azurpilot://pair 深链；secret 不是 32 位十六进制时抛错。 */
export function pairingQrPayload(secret: string): string {
  if (!/^[a-f0-9]{32}$/.test(secret)) throw new Error('Invalid pairing secret')
  return `azurpilot://pair?secret=${secret}`
}

/** 生成符合 4 模块安全间距要求的矢量 QR 数据；返回方角与圆角两套路径、三个定位框坐标与 viewBox 尺寸。 */
export function generateQrSvgData(
  value: string,
  level: 'L' | 'M' | 'Q' | 'H' = 'M',
  margin: number = 4,
) {
  const qr = qrcode(0, level)
  qr.addData(value)
  qr.make()
  const moduleCount = qr.getModuleCount()
  const viewBoxSize = moduleCount + margin * 2

  let pathD = ''
  let roundedPathD = ''
  const finders = [
    { x: margin, y: margin },
    { x: margin + moduleCount - 7, y: margin },
    { x: margin, y: margin + moduleCount - 7 },
  ]
  const isDark = (row: number, col: number) =>
    row >= 0 && col >= 0 && row < moduleCount && col < moduleCount && qr.isDark(row, col)
  const point = (value: number) => Number(value.toFixed(2))

  for (let row = 0; row < moduleCount; row++) {
    for (let col = 0; col < moduleCount; col++) {
      if (qr.isDark(row, col)) {
        pathD += `M ${col + margin} ${row + margin} h 1 v 1 h -1 Z `
        // 三个定位框单独绘制；数据块只圆润外露拐角，保留相邻模块的连接。
        if ((row < 7 && (col < 7 || col >= moduleCount - 7)) || (col < 7 && row >= moduleCount - 7)) continue
        const x = col + margin
        const y = row + margin
        const tl = !isDark(row - 1, col) && !isDark(row, col - 1) ? .22 : 0
        const tr = !isDark(row - 1, col) && !isDark(row, col + 1) ? .22 : 0
        const br = !isDark(row + 1, col) && !isDark(row, col + 1) ? .22 : 0
        const bl = !isDark(row + 1, col) && !isDark(row, col - 1) ? .22 : 0
        roundedPathD += `M ${point(x + tl)} ${y} H ${point(x + 1 - tr)} Q ${x + 1} ${y} ${x + 1} ${point(y + tr)} `
          + `V ${point(y + 1 - br)} Q ${x + 1} ${y + 1} ${point(x + 1 - br)} ${y + 1} `
          + `H ${point(x + bl)} Q ${x} ${y + 1} ${x} ${point(y + 1 - bl)} `
          + `V ${point(y + tl)} Q ${x} ${y} ${point(x + tl)} ${y} Z `
      }
    }
  }

  return {
    viewBoxSize,
    moduleCount,
    margin,
    pathD,
    roundedPathD,
    finders,
  }
}

/** 配对二维码展示组件：secret 非法或生成失败时渲染错误占位，label 同时作无障碍名称。 */
export function PairingQr({
  secret,
  label,
}: {
  secret: string
  label: string
}) {
  const { qrData, error } = useMemo(() => {
    try {
      return { qrData: generateQrSvgData(pairingQrPayload(secret), 'M', 4), error: '' }
    } catch (err) {
      return { qrData: null, error: (err as Error).message }
    }
  }, [secret])

  if (error || !qrData) {
    return (
      <div className="pairing-qr pairing-qr-error" role="alert">
        <span>{error || '生成二维码失败'}</span>
      </div>
    )
  }

  const { viewBoxSize, roundedPathD, finders } = qrData

  return (
    <div className="pairing-qr">
      <svg
        role="img"
        className="pairing-qr-symbol"
        aria-label={label}
        viewBox={`0 0 ${viewBoxSize} ${viewBoxSize}`}
        width="100%"
        height="100%"
        style={{ display: 'block' }}
      >
        <title>{label}</title>
        {/* 底层纯白填充，与外层纯白卡片融为一体 */}
        <rect width={viewBoxSize} height={viewBoxSize} fill="#ffffff" />
        <path d={roundedPathD} fill="currentColor" />
        {finders.map(({ x, y }) => (
          <g key={`${x}-${y}`}>
            <rect x={x} y={y} width="7" height="7" rx="1.1" fill="currentColor" />
            <rect x={x + 1} y={y + 1} width="5" height="5" rx=".6" fill="#ffffff" />
            <rect x={x + 2} y={y + 2} width="3" height="3" rx=".65" fill="currentColor" />
          </g>
        ))}
      </svg>
    </div>
  )
}

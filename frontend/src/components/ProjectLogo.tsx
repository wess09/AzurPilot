import type { ComponentProps } from 'react'

/** 项目 logo 图源：部署基址下的内置 azurpilot.webp。 */
export const PROJECT_LOGO_URL = `${import.meta.env.BASE_URL}azurpilot.webp`

/** 禁改 src/width/height：图源固定、宽高统一由 size 控制。 */
type LogoProps = Omit<ComponentProps<'img'>, 'src' | 'width' | 'height'> & {size?: number}

/** 项目 logo 图标：默认 28px 等宽高；默认空 alt 表示纯装饰，需要读屏描述时由调用方传入。 */
export function ProjectLogo({size = 28, alt = '', ...props}: LogoProps) {
  return <img {...props} src={PROJECT_LOGO_URL} alt={alt} width={size} height={size}/>
}

import type { ComponentProps } from 'react'

export const PROJECT_LOGO_URL = `${import.meta.env.BASE_URL}azurpilot.webp`

type LogoProps = Omit<ComponentProps<'img'>, 'src' | 'width' | 'height'> & {size?: number}

export function ProjectLogo({size = 28, alt = '', ...props}: LogoProps) {
  return <img {...props} src={PROJECT_LOGO_URL} alt={alt} width={size} height={size}/>
}

import type { ComponentProps, ReactNode } from 'react'

/** Shared surface for page sections. Compact sections retain the settings form layout. */
export function Panel({className = '', compact = false, ...props}: ComponentProps<'section'> & {compact?: boolean}) {
  return <section className={`panel${compact ? ' config-group' : ''} ${className}`.trim()} {...props}/>
}

export function PanelHeading({title, icon, actions, className = ''}: {title: ReactNode; icon?: ReactNode; actions?: ReactNode; className?: string}) {
  return <div className={`panel-heading ${className}`.trim()}><div>{icon}<h2>{title}</h2></div>{actions}</div>
}

export function PanelBody({className = '', ...props}: ComponentProps<'div'>) {
  return <div className={`panel-body ${className}`.trim()} {...props}/>
}

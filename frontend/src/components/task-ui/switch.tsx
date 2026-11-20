import * as React from 'react'
import { Switch as BaseSwitch } from '../official-ui/switch'
import { cn } from '../../lib/utils'

function Switch({className, ...props}: React.ComponentProps<typeof BaseSwitch>) {
  return <BaseSwitch className={cn('[contain:paint]', className)} {...props}/>
}

export { Switch }

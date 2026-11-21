import * as React from 'react'
import { Switch as BaseSwitch } from '../ui/switch'

function Switch({size = 'default', ...props}: React.ComponentProps<typeof BaseSwitch>) {
  return <BaseSwitch size={size} {...props}/>
}

export { Switch }

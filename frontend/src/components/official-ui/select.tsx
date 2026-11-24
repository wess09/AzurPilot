import * as React from 'react'
import { SelectTrigger as BaseSelectTrigger } from '../ui/select'

// Official forms use a content-sized trigger; the shared control defaults to full width.
function SelectTrigger(props: React.ComponentProps<typeof BaseSelectTrigger>) {
  return <BaseSelectTrigger width="fit" {...props}/>
}

export { Select, SelectContent, SelectItem, SelectValue } from '../ui/select'
export { SelectTrigger }

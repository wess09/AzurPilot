/** Radix switch shared by the application. */
import * as React from 'react'
import * as SwitchPrimitive from '@radix-ui/react-switch'
import { cn } from '../../lib/utils'

function Switch({className, size = 'large', ...props}: React.ComponentProps<typeof SwitchPrimitive.Root> & {size?: 'sm' | 'default' | 'large'}) {
  return <SwitchPrimitive.Root
    data-slot="switch"
    data-size={size}
    className={cn(
      'peer group/switch inline-flex shrink-0 cursor-pointer items-center rounded-full border border-transparent shadow-xs transition-all outline-none',
      'data-[size=large]:h-5 data-[size=large]:w-9 data-[size=default]:h-[1.15rem] data-[size=default]:w-8 data-[size=sm]:h-3.5 data-[size=sm]:w-6',
      'data-[state=checked]:bg-primary data-[state=unchecked]:bg-input dark:data-[state=unchecked]:bg-input/80',
      'focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50',
      className,
    )}
    {...props}
  >
    <SwitchPrimitive.Thumb data-slot="switch-thumb" className={cn(
      'pointer-events-none block rounded-full bg-background shadow-sm ring-0 transition-transform',
      'group-data-[size=large]/switch:size-4 group-data-[size=default]/switch:size-4 group-data-[size=sm]/switch:size-3',
      'data-[state=unchecked]:translate-x-0 data-[state=checked]:translate-x-[calc(100%-2px)] group-data-[size=large]/switch:data-[state=checked]:translate-x-4',
      'dark:data-[state=checked]:bg-primary-foreground dark:data-[state=unchecked]:bg-foreground',
    )}/>
  </SwitchPrimitive.Root>
}

export { Switch }

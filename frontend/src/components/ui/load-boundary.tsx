import type {ReactNode} from 'react'
import {ErrorBox, Loading} from '../ui'

export function LoadBoundary({ready, error, retry, children}: {ready: boolean; error?: string; retry?: () => void; children?: ReactNode}) {
  if (!ready) return error ? <ErrorBox message={error} retry={retry}/> : <Loading/>
  return <>{error && <ErrorBox message={error} retry={retry}/>} {children}</>
}

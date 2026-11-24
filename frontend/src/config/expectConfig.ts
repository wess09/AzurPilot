import type {Config, Value} from '../api/types'

/** Attach the exact values from the last accepted snapshot to edited fields. */
export function expectConfig(snapshot: Config | undefined, changes: {path: string; value: Value}[]) {
  if (!snapshot) throw new Error('Configuration is not loaded')
  return changes.map(change => {
    const [task, group, field] = change.path.split('.')
    if (!task || !group || !field) throw new Error('Invalid configuration path')
    const fields = snapshot.values[task]?.[group]
    // Older or sparse snapshots may lack a field; the API has no missing-value sentinel.
    return fields && Object.hasOwn(fields, field) ? {...change, expected: fields[field]} : change
  })
}

export function isConfigConflict(error: unknown) {
  return typeof error === 'object' && error !== null && 'code' in error && error.code === 'CONFLICT'
}

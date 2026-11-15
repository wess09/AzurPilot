/** APU API v1 client. Import from an installed plugin document. */
const listeners = new Map()
const latest = new Map()
const pending = new Map()
let sequence = 0

const port = await new Promise((resolve, reject) => {
  const nonce = new URLSearchParams(location.hash.slice(1)).get('apu')
  const timer = setTimeout(() => {
    window.removeEventListener('message', connected)
    reject(new Error('AzurPilot did not connect'))
  }, 7000)
  function connected(event) {
    if (event.source !== parent || event.data?.type !== 'apu.connect' || event.data.apiVersion !== 1 || !event.ports[0]) return
    clearTimeout(timer)
    window.removeEventListener('message', connected)
    resolve(event.ports[0])
  }
  window.addEventListener('message', connected)
  parent.postMessage({type: 'apu.hello', nonce}, '*')
})

port.onmessage = ({data}) => {
  if (data.id) {
    const task = pending.get(data.id)
    if (!task) return
    pending.delete(data.id)
    clearTimeout(task.timer)
    if (data.error) task.reject(new Error(data.error))
    else task.resolve(data.value)
  } else {
    latest.set(data.type, data.data)
    for (const listener of listeners.get(data.type) ?? []) listener(data.data)
  }
}
port.postMessage({type: 'apu.ready'})

export function request(method, args = {}) {
  const id = String(++sequence)
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id)
      reject(new Error('AzurPilot did not respond'))
    }, 15000)
    pending.set(id, {resolve, reject, timer})
    port.postMessage({...args, id, method})
  })
}

export function subscribe(type, listener) {
  const group = listeners.get(type) ?? new Set()
  group.add(listener)
  listeners.set(type, group)
  if (latest.has(type)) listener(latest.get(type))
  return () => group.delete(listener)
}

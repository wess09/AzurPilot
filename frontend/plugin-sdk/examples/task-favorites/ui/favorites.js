import { request, subscribe } from '../apu.js'

const form = document.querySelector('form')
const select = document.querySelector('select')
const list = document.querySelector('ul')
const status = document.querySelector('[role="status"]')
const key = 'favorites'
let names = []

subscribe('appearance', ({mode}) => { document.documentElement.style.colorScheme = mode })

function show() {
  const items = names.map(name => {
    const item = document.createElement('li')
    item.append(name + ' ')
    const remove = document.createElement('button')
    remove.textContent = '取消收藏'
    remove.addEventListener('click', () => void save(names.filter(value => value !== name)))
    item.append(remove)
    return item
  })
  list.replaceChildren(...items)
}

async function save(next) {
  try {
    names = await request('storage.set', {key, value: next})
    show()
    status.textContent = ''
  } catch (error) { status.textContent = error.message }
}

try {
  const [overview, saved] = await Promise.all([request('instance.overview'), request('storage.get', {key})])
  names = saved ?? []
  for (const name of new Set([...overview.tasks.map(task => task.name), ...overview.taskNames])) {
    select.add(new Option(name, name))
  }
  if (!select.options.length) {
    form.hidden = true
    status.textContent = '当前实例暂无已调度任务。'
  }
  show()
} catch (error) { status.textContent = error.message }

form.querySelector('button').addEventListener('click', () => {
  if (select.value && !names.includes(select.value)) void save([...names, select.value])
})

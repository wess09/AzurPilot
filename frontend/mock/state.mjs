import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import Ajv from 'ajv'

// 只读取公开的模板、元数据和翻译，绝不读取用户实例或部署文件。
const read = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'))
const args = read('../../module/config/argument/args.json')
const menu = read('../../module/config/argument/menu.json')
const template = read('../../config/template.json')
const contract = read('../src/api/contract.json')
const locales = Object.fromEntries(['zh-CN', 'zh-TW', 'en-US', 'ja-JP', 'zh-MIAO'].map(lang => [lang, read(`../../module/config/i18n/${lang}.json`)]))
const ajv = new Ajv({ strict: false, useDefaults: true })
const validators = Object.fromEntries(Object.entries(contract.methods).map(([method, entry]) => [method, ajv.compile(entry.params)]))
const revision = values => createHash('sha256').update(JSON.stringify(values)).digest('hex')
const timestamp = date => date.toISOString().slice(0, 19).replace('T', ' ')
const translate = key => key.split('.').reduce((value, part) => value?.[part], locales['zh-CN']) ?? key
export const fail = (code, message, details = null) => { throw Object.assign(new Error(message), { code, details }) }

function strategyLocation(source, index) {
  const prefix = source.slice(0, Math.max(0, index))
  return { line: prefix.split(/\r?\n/).length, column: prefix.length - Math.max(prefix.lastIndexOf('\n'), prefix.lastIndexOf('\r')) }
}

function invalidStrategy(source, code, message, index = 0) {
  return { valid: false, diagnostics: [{ code, message, ...strategyLocation(source, index) }] }
}

function maskLuaStringsAndComments(source) {
  let output = ''
  for (let index = 0; index < source.length;) {
    if (source.startsWith('--[[', index)) {
      const end = source.indexOf(']]', index + 4)
      if (end < 0) return { masked: output, error: invalidStrategy(source, 'syntax_error', '多行注释没有结束', index) }
      const comment = source.slice(index, end + 2)
      output += comment.replace(/[^\r\n]/g, ' ')
      index = end + 2
      continue
    }
    if (source.startsWith('--', index)) {
      const end = source.indexOf('\n', index)
      const comment = source.slice(index, end < 0 ? source.length : end)
      output += comment.replace(/[^\r\n]/g, ' ')
      index = end < 0 ? source.length : end
      continue
    }
    const quote = source[index]
    if (quote === '"' || quote === "'") {
      const start = index++
      output += ' '
      let closed = false
      while (index < source.length) {
        const char = source[index++]
        if (char === '\\') {
          output += ' '
          if (index < source.length) output += source[index++] === '\n' ? '\n' : ' '
          continue
        }
        output += char === '\n' || char === '\r' ? char : ' '
        if (char === quote) { closed = true; break }
      }
      if (!closed) return { masked: output, error: invalidStrategy(source, 'syntax_error', '字符串没有结束', start) }
      continue
    }
    output += source[index++]
  }
  return { masked: output, error: null }
}

function validateMockStrategy(script) {
  // Mock 不执行 Lua；这里只复现不会误伤有效分支策略的明显语法和白名单错误。
  if (!script.trim()) return { valid: true, diagnostics: [] }
  const { masked, error } = maskLuaStringsAndComments(script)
  if (error) return error

  const pairs = { '(': ')', '[': ']', '{': '}' }
  const opening = []
  for (let index = 0; index < masked.length; index++) {
    const character = masked[index]
    if (character in pairs) opening.push({ character, index })
    else if (Object.values(pairs).includes(character)) {
      const previous = opening.pop()
      if (!previous || pairs[previous.character] !== character) return invalidStrategy(script, 'syntax_error', '括号或花括号不匹配', index)
    }
  }
  if (opening.length) return invalidStrategy(script, 'syntax_error', '括号或花括号没有结束', opening.at(-1).index)

  const forbiddenStatement = /\b(?:while|repeat|for|goto|break)\b/.exec(masked)
  if (forbiddenStatement) return invalidStrategy(script, 'forbidden_statement', `不支持 ${forbiddenStatement[0]} 语句`, forbiddenStatement.index)
  const namedFunction = /\bfunction\s+(?!\()/.exec(masked)
  if (namedFunction) return invalidStrategy(script, 'forbidden_statement', '不支持具名 function 语句', namedFunction.index)
  const forbiddenCall = /\b((?:os|io|debug|package|math|string|table|coroutine)\s*[.:]\s*[A-Za-z_]\w*|require|load|dofile|loadfile|collectgarbage|setmetatable|getmetatable|pairs|ipairs|next|type|tonumber|tostring|error|assert|pcall|xpcall)\s*\(/.exec(masked)
  if (forbiddenCall) {
    return invalidStrategy(script, 'forbidden_call', `不允许调用 ${forbiddenCall[1].replace(/\s/g, '')}`, forbiddenCall.index)
  }
  const plan = /\breturn\s+shop\s*\.\s*plan\s*(?:\(\s*)?\{/.exec(masked)
  if (!plan) return invalidStrategy(script, 'missing_return', '必须返回 shop.plan {...}', 0)

  const unknownShopField = /\bshop\s*\.\s*(?!plan\b)([A-Za-z_]\w*)/.exec(masked)
  if (unknownShopField) return invalidStrategy(script, 'forbidden_field', `不支持 shop.${unknownShopField[1]}`, unknownShopField.index)
  const allowedContextFields = new Set(['domain', 'currency', 'spent', 'purchased'])
  for (const match of masked.matchAll(/\bcontext\s*\.\s*([A-Za-z_]\w*)/g)) {
    if (!allowedContextFields.has(match[1])) return invalidStrategy(script, 'unknown_context_field', `不支持 context.${match[1]}`, match.index)
  }
  const allowedCandidateFields = new Set(['id', 'key', 'name', 'group', 'sub_genre', 'tier', 'price', 'cost', 'stock', 'max_quantity', 'available'])
  for (const match of masked.matchAll(/\bitem\s*\.\s*([A-Za-z_]\w*)/g)) {
    if (!allowedCandidateFields.has(match[1])) return invalidStrategy(script, 'unknown_candidate_field', `不支持商品字段 ${match[1]}`, match.index)
  }
  const allowedPipelineMethods = new Set(['where', 'score', 'order_by', 'cap', 'take'])
  for (const match of masked.matchAll(/:\s*([A-Za-z_]\w*)\s*\(/g)) {
    const method = match[1]
    if (!allowedPipelineMethods.has(method)) return invalidStrategy(script, 'forbidden_call', '候选管道只允许 where、score、order_by、cap、take', match.index)
  }
  for (const match of masked.matchAll(/:\s*take\s*\(([^)]*)\)/g)) {
    const rawAmount = match[1].trim()
    if (!/^\d+$/.test(rawAmount)) return invalidStrategy(script, 'invalid_take', 'take 必须是 0 到 100 之间的整数', match.index)
    const amount = Number(rawAmount)
    if (amount > 100) return invalidStrategy(script, 'invalid_take', 'take 必须在 0 到 100 之间', match.index)
  }
  for (const match of masked.matchAll(/\b([A-Za-z_]\w*)\s*\(/g)) {
    const before = masked.slice(0, match.index).trimEnd().at(-1)
    if (before === ':' || before === '.' || ['function', 'if', 'elseif'].includes(match[1])) continue
    return invalidStrategy(script, 'forbidden_call', `不允许调用 ${match[1]}`, match.index)
  }
  return { valid: true, diagnostics: [] }
}

function requireValidMockStrategy(script) {
  const result = validateMockStrategy(script)
  if (!result.valid) fail('INVALID_PARAMS', `高级商店策略脚本无效：${result.diagnostics[0].message}`, result.diagnostics)
}

function validateMockAdvancedGroups(values, tasks) {
  for (const task of tasks) {
    const group = values[task]?.ShopAdvanced
    if (group?.Mode !== 'advanced') continue
    const script = group.Script
    if (typeof script !== 'string' || !script.trim()) fail('INVALID_PARAMS', `${task} 的高级模式需要先保存非空且有效的策略脚本`)
    requireValidMockStrategy(script)
  }
}

function validateField(path, value) {
  const parts = path.split('.')
  const field = parts.length === 3 && parts.reduce((node, key) => Object.hasOwn(node ?? {}, key) ? node[key] : undefined, args)
  if (!field) fail('INVALID_PARAMS', '配置项不存在')
  if (field.type === 'storage' && field.display !== 'hide' && value !== null && typeof value === 'object' && !Array.isArray(value) && !Object.keys(value).length) return parts
  if (['hide', 'disabled', 'readonly'].includes(field.display) || ['storage', 'stored', 'state', 'lock'].includes(field.type)) fail('READ_ONLY', '此配置项不可修改')
  if (field.type === 'multiselect') {
    if (!Array.isArray(value) || value.some(item => !field.option?.includes(item)) || new Set(value).size !== value.length) fail('INVALID_PARAMS', '多选项无效')
    return parts
  }
  if (field.option?.length && !field.option.includes(value)) fail('INVALID_PARAMS', '请选择有效选项')
  const kind = typeof field.value
  const valid = field.type === 'checkbox' || kind === 'boolean' ? typeof value === 'boolean'
    : kind === 'number' ? typeof value === 'number' && Number.isFinite(value) && (!Number.isInteger(field.value) || Number.isInteger(value))
      : typeof value === 'string' || (field.value === null && value === null)
  if (!valid || (typeof value === 'string' && value.length > 20000)) fail('INVALID_PARAMS', '参数类型或长度不正确')
  if (Array.isArray(field.validate) && (typeof value !== 'number' || value < field.validate[0] || value > field.validate[1])) fail('INVALID_PARAMS', '数值超出允许范围')
  if (field.validate === 'datetime' && (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value) || Number.isNaN(Date.parse(value.replace(' ', 'T'))))) fail('INVALID_PARAMS', '日期格式不正确')
  return parts
}

export function createMockState({ empty = false } = {}) {
  const instances = new Map()
  const startup = new Set()
  const remember = new Set()
  const commits = Array.from({ length: 123 }, (_, index) => ({ sha: createHash('sha1').update(`mock-commit-${123 - index}`).digest('hex'), author: 'AzurPilot', date: new Date(Date.UTC(2026, 8, 14, 0, -index)).toISOString(), message: index === 0 ? 'feat(webui): 新增主页与实例状态\n\n统一全局设置和更新入口。' : `fix(runtime): 改善任务运行稳定性 ${123 - index}` }))
  let localHead = commits[3].sha
  let upstreamHead = commits[0].sha
  // 端到端场景开关：模拟本地与更新源历史分叉（镜像重写历史导致 SHA 不匹配）。
  let divergedUpdater = false
  const divergedLocalHead = createHash('sha1').update('mock-diverged-local').digest('hex')
  const setUpdateScenario = mode => {
    divergedUpdater = mode === 'diverged'
    localHead = divergedUpdater ? divergedLocalHead : commits[3].sha
  }
  const updateStatus = () => ({ state: localHead === upstreamHead ? 'idle' : 'available', localHead, upstreamHead, branch: 'dev', ahead: divergedUpdater ? 1 : 0, behind: divergedUpdater ? 3 : commits.findIndex(item => item.sha === localHead), available: localHead !== upstreamHead, busy: false, canApply: localHead !== upstreamHead, canCancel: false, error: '', shaMismatch: divergedUpdater })
  const settings = {
    groups: [
      {
        key: 'Webui', label: 'WebUI 设置', fields: [
          { key: 'WebuiHost', type: 'string', label: '监听地址', help: '模拟部署设置，仅在当前 mock 会话中保留。', value: '0.0.0.0', options: [] },
          { key: 'WebuiPort', type: 'int', label: '监听端口', help: '用于验证数值输入与保存。', value: 22267, options: [] },
          { key: 'Password', type: 'password', label: '访问密码', help: '留空保留原密码。', value: '', options: [] },
        ]
      },
      {
        key: 'RemoteAccess', label: '远程访问', fields: [
          { key: 'EnableRemoteAccess', type: 'bool', label: '启用远程访问', help: '模拟部署设置，仅在当前 mock 会话中保留。', value: true, options: [] },
          { key: 'RemoteAccessMode', type: 'select', label: '远程访问模式', help: '自动模式优先 P2P，失败后回退 SSH 转发。', value: 'auto', options: ['auto', 'webrtc', 'ssh'] },
        ]
      },
      {
        key: 'Git', label: 'Git', fields: [
          { key: 'Branch', type: 'string', label: '分支', help: '模拟系统级分组，用于验证系统设置页。', value: 'dev', options: [] },
        ]
      },
    ], notice: '前端测试数据', demo: false, remote: {
      enabled: true, state: 'waiting_peer', address: 'https://tunnel.example.com/p2p/example-peer-id', error: '',
    }
  }
  const get = name => instances.get(name) ?? fail('NOT_FOUND', '实例不存在')
  const snapshot = name => ({ instance: name, revision: revision(get(name).values), values: structuredClone(get(name).values) })
  function log(name, text, level = 'INFO') {
    const instance = get(name)
    instance.logs.push({ id: ++instance.cursor, level, text: `${timestamp(new Date())} [${name}] ${text}` })
    instance.logs = instance.logs.slice(-400)
  }
  function add(name, values) {
    instances.set(name, { values: structuredClone(values), status: 'stopped', logs: [], cursor: 0 })
    log(name, '测试实例已就绪，所有操作均为模拟。')
  }
  if (!empty) {
    for (const [index, name] of ['demo-main', 'demo-alt', 'demo-error', 'demo-dog'].entries()) {
      const values = structuredClone(template)
      values.Main.Emotion.Fleet1Record = '2026-09-12 23:45:12.123456'
      values.Main.Scheduler.NextRun = '2099-01-01 12:00:00'
      values.Alas.Emulator.Serial = `127.0.0.1:${5555 + index * 2}`
      /* 四个演示实例各占一档：小狗 / 中狗 / 大狗 / 狗王，用来一次看全行动力图标的四档。 */
      const apTotal = {'demo-main': 6001, 'demo-alt': 8001, 'demo-error': 10001, 'demo-dog': 12001}[name] ?? 6001
      const dashboardDefaults = {
        Oil: { Value: 14200 - index * 100, Limit: 25000 },
        Coin: { Value: 186420 - index * 1000, Limit: 600000 },
        Gem: { Value: 2468 - index * 10 },
        Cube: { Value: 384 - index * 5 },
        Pt: { Value: 42500 - index * 200 },
        ActionPoint: { Value: 101 - index * 2, Total: apTotal },
        YellowCoin: { Value: 1520 - index * 20 },
        PurpleCoin: { Value: 340 - index * 10 },
        Core: { Value: 1280 - index * 15 },
        Medal: { Value: 650 - index * 5 },
        Merit: { Value: 18400 - index * 100 },
        GuildCoin: { Value: 7600 - index * 50 },
      }
      const nowTs = timestamp(new Date())
      for (const [key, item] of Object.entries(dashboardDefaults)) {
        if (values.Dashboard[key]) Object.assign(values.Dashboard[key], item, { Record: nowTs })
      }
      for (const [order, task] of ['Commission', 'Research', 'Dorm', 'Main'].entries()) {
        values[task].Scheduler.Enable = true
        values[task].Scheduler.NextRun = timestamp(new Date(Date.now() + (order - 1) * 1800000))
      }
      add(name, values)
    }
    get('demo-error').status = 'error'
    get('demo-error').values.Alas.Storage.Storage = { failureCount: 3, lastError: '模拟器连接失败', retry: { enabled: false, remaining: 0 }, tasks: ['Commission', 'Research'] }
    log('demo-error', '模拟器连接失败，请检查连接设置。', 'ERROR')
  }
  function overview(name) {
    const data = snapshot(name)
    return {
      instance: name, revision: data.revision, status: get(name).status, emulator: data.values.Alas.Emulator,
      tasks: Object.entries(data.values).filter(([, groups]) => groups.Scheduler?.Enable).map(([task, groups]) => ({
        name: task, nextRun: groups.Scheduler.NextRun,
        state: get(name).status === 'running' && task === 'Commission' ? 'running' : groups.Scheduler.NextRun <= timestamp(new Date()) ? 'pending' : 'waiting',
        pending: groups.Scheduler.NextRun <= timestamp(new Date()),
      })),
      resources: Object.entries(data.values.Dashboard).filter(([, resource]) => 'Value' in resource).map(([key, resource]) => ({
        name: key, label: translate(`${key}._info.name`), value: resource.Value, limit: resource.Limit, total: resource.Total, record: resource.Record,
      })),
    }
  }
  function dispatch(method, input = {}) {
    const params = structuredClone(input)
    if (!Object.hasOwn(validators, method)) fail('METHOD_NOT_FOUND', '未知 API 方法')
    if (!validators[method](params)) fail('INVALID_PARAMS', '请求参数不符合 API 契约')
    const name = params.instance
    if (name != null) get(name)
    switch (method) {
      case 'updater.status': return updateStatus()
      case 'updater.commits': return { entries: commits.slice(params.offset, params.offset + params.limit), total: commits.length, hasMore: params.offset + params.limit < commits.length, localHead, upstreamHead }
      case 'updater.fetch': return { accepted: true }
      case 'updater.apply': localHead = upstreamHead; divergedUpdater = false; return { accepted: true }
      case 'updater.cancel': return { accepted: true }
      case 'system.ping': return { pong: true }
      case 'schema.get': return { args, menu, translations: locales[params.language] }
      case 'instances.list': return [...instances].map(([name, item]) => ({ name, status: item.status, currentTask: item.status === 'running' ? 'Commission' : null, serial: item.values.Alas.Emulator.Serial, server: item.values.Alas.Emulator.ServerName }))
      case 'instances.create': {
        if (!/^[A-Za-z0-9\u3041-\u3096\u30a1-\u30fa\u30fc\u31f0-\u31ff\uff66-\uff9f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff][A-Za-z0-9_. \u3041-\u3096\u30a1-\u30fa\u30fc\u31f0-\u31ff\uff66-\uff9f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\-]{0,63}$/.test(params.name) || /^(template|deploy|backup|con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i.test(params.name)) fail('INVALID_PARAMS', '实例名称无效')
        if ([...instances.keys()].some(name => name.toLowerCase() === params.name.toLowerCase())) fail('ALREADY_EXISTS', '同名实例已存在')
        add(params.name, params.source ? get(params.source).values : template)
        return snapshot(params.name)
      }
      case 'instances.delete':
        if (get(name).status === 'running') fail('INSTANCE_RUNNING', '请先停止实例再删除')
        if (params.revision !== snapshot(name).revision) fail('CONFLICT', '配置已变化，请重新加载后删除')
        instances.delete(name); startup.delete(name)
        return { deleted: name }
      case 'config.get': return snapshot(name)
      case 'shop_strategy.validate': return validateMockStrategy(params.script)
      case 'config.patch': {
        const data = snapshot(name)
        const seen = new Set()
        const affectedShopTasks = new Set()
        for (const { path, value } of params.changes) {
          const [task, group, arg] = validateField(path, value)
          if (seen.has(path)) fail('INVALID_PARAMS', '同一次保存不能重复修改同一个参数')
          seen.add(path)
          const field = args[task][group][arg]
          if (field.mode === 'restricted_lua') requireValidMockStrategy(value)
          data.values[task] ??= {}; data.values[task][group] ??= {}
          data.values[task][group][arg] = value
          if (group === 'ShopAdvanced') affectedShopTasks.add(task)
        }
        validateMockAdvancedGroups(data.values, affectedShopTasks)
        get(name).values = data.values
        log(name, `已保存 ${params.changes.length} 项配置。`)
        return snapshot(name)
      }
      case 'overview.get': return overview(name)
      case 'scheduler.start': case 'tasks.run':
        if (get(name).status === 'running') fail('INSTANCE_RUNNING', '实例已在运行')
        if (method === 'tasks.run' && params.task !== 'FleetScan' && !Object.values(menu).some(group => group.page === 'tool' && group.tasks.includes(params.task))) fail('INVALID_PARAMS', '该任务不支持单独运行')
        get(name).status = 'running'; log(name, '模拟调度器已启动。')
        return overview(name)
      case 'scheduler.stop':
        get(name).status = 'stopped'; log(name, '模拟调度器已停止。')
        return overview(name)
      case 'logs.get': {
        const item = get(name)
        const reset = params.after > item.cursor || params.after < (item.logs[0]?.id ?? 1) - 1
        return { instance: name, cursor: item.cursor, reset, entries: item.logs.filter(entry => reset || entry.id > params.after) }
      }
      case 'preview.capture': {
        if (!get(name).previewAt) return { instance: name, image: null, capturedAt: null }
        const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#142d3a"/><circle cx="640" cy="300" r="145" fill="none" stroke="#78dac4" stroke-width="3"/><path d="M640 190 720 370 640 330 560 370Z" fill="#78dac4"/><text x="640" y="530" text-anchor="middle" fill="#d5ede9" font-size="32">AzurPilot · 模拟器测试画面</text></svg>'
        return { instance: name, image: `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`, capturedAt: get(name).previewAt ?? null }
      }
      case 'statistics.refreshLoot': return { refreshed: true }
      case 'meowfficer.scoreReport': {
        // demo-alt 用来验证「还没跑过评分任务」的空状态，其余实例都给一份示例报告。
        if (name === 'demo-alt') fail('NOT_FOUND', '评分报告尚未生成，请先在「工具Plus → 指挥喵评分」运行一次任务')
        const cats = [{
          source: 'shot_0.png', cat: '克雷喵', tags: ['SSR', '铁血', '潜艇', '司令'], fixed: false,
          note: '指定潜艇司令，狩猎范围+1；初始池小、最好毕业', maxed: true, pointsSpent: 6, primary: 'submarine',
          talents: [
            { name: '狼群之首', level: 1, kind: 'special', inferred: false },
            { name: '雷击长·潜艇', level: 3, kind: 'normal', inferred: false },
            { name: '装填新手·潜艇', level: 3, kind: 'normal', inferred: true },
          ],
          rubrics: [
            {
              key: 'submarine', label: '潜艇猫', tier: '准毕业', score: 100, x: 1, y: 6.0,
              xHits: ['狼群之首 Lv1'], yHits: ['新人雷击士·潜艇 Lv3', '装填新手·潜艇 Lv3'],
              notes: ['缺 侵略如火：两者是潜艇口径里唯一的两个一档输出彩'],
              source: '28法则执行篇·潜艇猫；详细上手攻略·潜艇喵', primary: true
            },
            {
              key: 'low_cost', label: '低耗猫', tier: '不适合低耗', score: 35, x: 0, y: 2.0,
              xHits: [], yHits: ['装填新手·潜艇 Lv3'], notes: [], source: '28法则执行篇·低耗猫', primary: false
            },
          ],
        }, {
          source: 'shot_1.png', cat: '海伦娜喵', tags: ['SSR', '白鹰', '轻巡'], fixed: true,
          note: '辅助输出向，主口径取雷暴', maxed: false, pointsSpent: 3, primary: 'torpedo',
          talents: [{ name: '一骑当千', level: 3, kind: 'special', inferred: false }],
          rubrics: [
            // 雷暴口径是加权点制：与真实后端一致地给出 null 的 x/y 与语义标签
            {
              key: 'torpedo', label: '雷暴猫', tier: '雷暴优秀', score: 88, x: null, y: null,
              xHits: [], yHits: ['一骑当千 Lv3', '雷击长·轻巡 Lv3'], yLabel: '加权命中',
              notes: ['适合雷暴队当输出小猫'], source: '28法则执行篇·雷暴猫', primary: true
            },
          ],
        }]
        return { instance: name, generatedAt: timestamp(new Date()), count: cats.length, cats: cats.slice(-(params.limit ?? 100)) }
      }
      case 'statistics.report': {
        const makePoints = (res, days = 7) => {
          if (name === 'demo-alt') return []
          const baseMap = {
            oil: 14200, coin: 186420, gem: 2468, cube: 384, pt: 42500, core: 1280, medal: 650, merit: 18400, guild_coin: 7600,
            ap: 101, asset: 5301, distance: 4520, yellow_coins: 1520, purple_coins: 340,
            Chip: 240, total_exp_gained: 152000, battle_count: 36, total_run_time: 2490,
          }
          const resKeyMap = {
            oil: 'Oil', coin: 'Coin', gem: 'Gem', cube: 'Cube', pt: 'Pt', core: 'Core', medal: 'Medal', merit: 'Merit', guild_coin: 'GuildCoin',
            ap: 'ActionPoint', yellow_coins: 'YellowCoin', purple_coins: 'PurpleCoin',
          }
          const dbKey = resKeyMap[res] ?? res
          const base = get(name).values.Dashboard[dbKey]?.Value ?? baseMap[res] ?? 500
          const safeDays = Math.max(1, Number(days) || 7)
          return Array.from({ length: 24 }, (_, index) => ({
            time: timestamp(new Date(Date.now() - (23 - index) * safeDays * 3600000)),
            value: Math.max(0, Math.round(base * (.8 + index / 120 + Math.sin(index) * .03))),
          }))
        }
        const reportSeries = entries => entries.map(([key, label, res = key]) => ({
          key, label, points: makePoints(res, params.days)
        }))
        const result = { instance: name, category: params.category, month: params.month, metrics: [], series: [], tables: [], notes: [] }
        if (params.category === 'resources') {
          result.series = reportSeries([
            ['oil', '石油', 'Oil'], ['coin', '物资', 'Coin'], ['gem', '钻石', 'Gem'], ['cube', '心智魔方', 'Cube'],
            ['pt', '活动 PT', 'Pt'], ['core', '核心数据', 'Core'], ['medal', '荣誉勋章', 'Medal'],
            ['merit', '功勋', 'Merit'], ['guild_coin', '舰队币', 'GuildCoin']
          ])
        } else if (params.category === 'action') {
          result.series = reportSeries([
            ['ap', '行动力', 'ActionPoint'], ['asset', '行动力资产', 'asset'], ['distance', '海里数', 'distance'],
            ['yellow_coins', '作战补给凭证', 'YellowCoin'], ['purple_coins', '特别兑换凭证', 'PurpleCoin']
          ])
        } else if (params.category === 'commission') {
          result.metrics = [
            { label: '完成委托', value: 48, unit: '项' }, { label: '钻石', value: 80, unit: '' },
            { label: '心智魔方', value: 32, unit: '' }, { label: '心智单元', value: 240, unit: '' },
            { label: '石油', value: 3600, unit: '' }, { label: '物资', value: 28400, unit: '' }
          ]
          result.series = reportSeries([
            ['Gem', '钻石', 'Gem'], ['Cube', '心智魔方', 'Cube'], ['Chip', '心智单元', 'Chip'],
            ['Oil', '石油', 'Oil'], ['Coin', '物资', 'Coin']
          ])
          result.tables = [
            {
              title: '委托收益明细', columns: ['资源', '总收益', '掉落记录数', '平均每次掉落'], rows: name === 'demo-alt' ? [] : [
                ['钻石', 80, 4, 20], ['心智魔方', 32, 16, 2], ['心智单元', 240, 12, 20], ['石油', 3600, 18, 200], ['物资', 28400, 24, 1183.33]
              ]
            },
            {
              title: '委托结算记录', columns: ['时间', '委托数量', '钻石', '魔方', '心智单元', '石油', '物资'], defaultSort: { index: 0, descending: true }, rows: name === 'demo-alt' ? [] : [
                [timestamp(new Date(Date.now() - 3600000)), 2, 20, 2, 0, 400, 1500],
                [timestamp(new Date(Date.now() - 7200000)), 1, 0, 4, 20, 0, 2200],
                [timestamp(new Date(Date.now() - 14400000)), 3, 40, 0, 40, 800, 3100],
                [timestamp(new Date(Date.now() - 28800000)), 2, 0, 2, 0, 600, 1800]
              ]
            }
          ]
        } else if (params.category === 'ships') {
          result.metrics = [
            { label: '目标等级', value: 125, unit: '' }, { label: '预估经验效率', value: 48200, unit: '/小时' },
            { label: '平均战斗时长', value: 42, unit: '秒' }, { label: '平均每轮时长', value: 68, unit: '秒' },
            { label: '短猫平均战斗时长', value: 25, unit: '秒' }, { label: '今日战斗', value: 36, unit: '场' },
            { label: '今日经验', value: 152000, unit: '' }, { label: '今日运行', value: 41.5, unit: '分钟' }
          ]
          result.series = reportSeries([
            ['total_exp_gained', '每日经验', 'total_exp_gained'],
            ['battle_count', '每日战斗', 'battle_count'],
            ['total_run_time', '每日运行秒数', 'total_run_time']
          ])
          result.tables = [{
            title: '舰船升级进度',
            columns: ['位置', '等级', '当前经验', '累计经验', '目标经验', '检测后战斗数', '还需经验', '还需战斗', '预估用时'],
            note: '上次检测：2026-09-20 18:30:00；舰队：1队。',
            rows: name === 'demo-alt' ? [] : [
              ['旗舰', 124, 284000, 3284000, 3600000, 36, 316000, 75, '01:15:00'],
              ['先锋1', 123, 192000, 2792000, 3600000, 36, 808000, 192, '03:12:00'],
              ['先锋2', 121, 84000, 2184000, 3600000, 36, 1416000, 337, '05:37:00']
            ]
          }]
        } else if (params.category === 'opsi') {
          result.metrics = [
            { label: '战斗次数', value: 1420, unit: '场' }, { label: '出击轮数', value: 710, unit: '轮' },
            { label: '出击消耗', value: 3550, unit: '行动力' }, { label: '明石遭遇', value: 85, unit: '次' },
            { label: '明石遭遇率', value: 11.97, unit: '%' }, { label: '塞壬研究装置', value: 28, unit: '个' },
            { label: '装置获取率', value: 3.94, unit: '%' }, { label: '购买行动力', value: 3950, unit: '' },
            { label: '平均每次购买', value: 46.47, unit: '' }, { label: '净行动力', value: 400, unit: '' },
            { label: '循环效率', value: 11.27, unit: '%' }
          ]
          result.tables = [{
            title: '短猫运行统计',
            columns: ['侵蚀等级', '战斗次数', '有效轮数', '平均战斗秒数', '平均每轮秒数', '研究装置', '获取率（%）', '统计来源'],
            rows: name === 'demo-alt' ? [] : [
              [3, 420, 210, 38.5, 62.1, 8, 3.81, '实测'],
              [5, 1000, 500, 44.2, 71.8, 20, 4.0, '实测']
            ]
          }]
        } else if (params.category === 'loot') {
          // 素材与服务端 module/api/statistics_service.py 的 loot 分支对齐：
          // 上面收益卡片（金菜/彩图纸 + 今日/本月/选定月份总计）、中间收获明细、
          // 下面掉落记录，最后是原有的短猫按侵蚀等级的收益汇总。
          const items = [
            ['PlateGeneralT4', '通用部件T4', '金', 8, 5],
            ['PlateGunT4', '主炮部件T4', '金', 8, 8],
            ['PlateTorpedoT4', '鱼雷部件T4', '金', 6, 6],
            ['PlateAntiAirT4', '防空炮部件T4', '金', 4, 4],
            ['PlatePlaneT4', '舰载机部件T4', '金', 5, 5],
            ['GearDesignPlanGunT5', '舰炮研发图纸UR型', '彩', 0, 0],
            ['GearDesignPlanTorpedoT5', '鱼雷研发图纸UR型', '彩', 0, 0],
            ['GearDesignPlanAntiAirT5', '防空炮研发图纸UR型', '彩', 0, 0],
            ['GearDesignPlanPlaneT5', '舰载机研发图纸UR型', '彩', 1, 1]
          ]
          const empty = name === 'demo-alt'
          result.taskOptions = [
            { key: 'opsi_daily', label: '大世界每日Plus', count: 0 },
            { key: 'opsi_obscure', label: '隐秘海域', count: 0 },
            { key: 'opsi_abyssal', label: '深渊坐标', count: 0 },
            { key: 'opsi_stronghold', label: '塞壬要塞', count: empty ? 0 : 1 },
            { key: 'opsi_meowfficer_farming', label: '耄耋相接', count: empty ? 0 : 19 }
          ]
          const detail = {
            title: '大世界掉落明细',
            columns: ['图标', '物品', '稀有度', '总收益', '掉落记录数', '平均每次掉落'],
            note: '暂时只统计金菜（通用/主炮/鱼雷/防空炮/舰载机 部件T4）与彩图纸（舰炮/鱼雷/防空炮/舰载机 研发图纸UR型）；其他物品照常入库，只是不在这里展示。',
            defaultSort: { index: 3, descending: true },
            rows: empty ? [] : items.map(([key, zh, rarity, amount, count]) => [
              `opsi:${key}`, zh, rarity, amount || null, count || null, count ? 1.6 : null
            ])
          }
          result.metrics = empty ? [] : [
            { label: '掉落记录', value: 20, unit: '次' },
            ...items.map(([key, zh, , amount]) => ({ label: zh, value: amount || null, unit: '', icon: `opsi:${key}` })),
            { label: '今日总计', value: 7, unit: '' },
            { label: '本月总计', value: 32, unit: '' },
            { label: '选定月份总计', value: 32, unit: '' }
          ]
          result.tables = empty ? [detail] : [
            detail,
            {
              title: '掉落记录',
              columns: ['时间', '任务', '海域', '掉落物'],
              note: '按时间倒序；只列掉了金菜或彩图纸的记录，其余掉落不入这张表。',
              defaultSort: { index: 0, descending: true },
              rows: [
                ['2026-09-25 07:58:28', '耄耋相接', '危险海域 Mediterranee A（侵蚀5）', '鱼雷部件T4 x1'],
                ['2026-09-25 07:30:33', '耄耋相接', '危险海域 Mediterranee A（侵蚀5）', '舰载机研发图纸UR型 x1、通用部件T4 x1、主炮部件T4 x1'],
                ['2026-09-23 12:04:51', '塞壬要塞', '要塞海域 East Continental Shelf E（侵蚀3）', '通用部件T4 x4、主炮部件T4 x1、鱼雷部件T4 x1、防空炮部件T4 x1、舰载机部件T4 x1']
              ]
            }
          ]
          result.tables.push({
            title: '短猫掉落收益',
            columns: ['侵蚀等级', '上次记录时间', '有效战斗轮数', '平均黄币/轮', '平均金菜/轮', '平均深渊/轮', '平均隐秘/轮'],
            rows: empty ? [] : [
              [3, timestamp(new Date(Date.now() - 3600000)), 210, 4.125, 0.35, 0.08, 0.12],
              [5, timestamp(new Date(Date.now() - 1800000)), 500, 5.82, 0.58, 0.15, 0.22]
            ]
          })
        } else if (params.category === 'research') {
          // 两个视图共用同一套形状：上面收益卡片、中间收获明细、下面原始掉落记录，
          // 区别只在期数视图按期过滤、心智/物资视图不分期。素材与服务端
          // module/api/statistics_service.py 对齐。
          const scope = params.scope ?? 'series'
          if (scope !== 'series') {
            const items = name === 'demo-alt' ? [] : [
              ['CognitiveChips', '心智单元', '金', 480, 12],
              ['Coins', '物资', '—', 3116, 78]
            ]
            const recordRows = name === 'demo-alt' ? [] : [
              ['2026-09-24 21:04:10', 'D-737-MI', 9, '物资 x96'],
              ['2026-09-24 12:30:05', 'Q-051-UL', 7, '物资 x120'],
              ['2026-09-23 08:12:44', 'G-531-MI', 9, '心智单元 x40、物资 x88']
            ]
            result.metrics = [
              { label: '掉落记录', value: 79, unit: '次' },
              ...items.map(([key, zh, , amount]) => ({ label: zh, value: amount || null, unit: '', icon: `research:${key}` })),
              { label: '今日总计', value: name === 'demo-alt' ? null : 96, unit: '' },
              { label: '本月总计', value: name === 'demo-alt' ? null : 2840, unit: '' },
              { label: '选定月份总计', value: name === 'demo-alt' ? null : 3596, unit: '' }
            ]
            result.tables = [
              {
                title: '心智/物资收获明细',
                columns: ['图标', '物品', '稀有度', '总收益', '掉落记录数', '平均每次掉落'],
                note: '心智单元与物资不绑期数、各期混着出，所以这里不分期统计（时间范围跟着「汇总周期」走）；清单里没掉过的也留一行，便于对照。图标暂用当前物品模板。',
                defaultSort: { index: 3, descending: true },
                rows: items.map(([key, zh, rarity, amount, count]) => [
                  `research:${key}`, zh, rarity, amount || null, count || null, count ? 1.5 : null
                ])
              },
              {
                title: '掉落记录',
                columns: ['时间', '项目', '期数', '掉落物'],
                note: '按时间倒序；只列掉了心智单元或物资的记录。',
                defaultSort: { index: 0, descending: true },
                rows: recordRows
              }
            ]
          } else {
            const items = [
              ['BlueprintValparaiso', '蓝图：瓦尔帕莱索', '彩', 12],
              ['BlueprintMaxImmelmann', '蓝图：马克斯·殷麦曼', '彩', 0],
              ['BlueprintTakahashi', '蓝图：高梁', '金', 29],
              ['BlueprintDuncan', '蓝图：邓肯', '金', 14],
              ['BlueprintOrage', '蓝图：暴风雨', '金', 17],
              ['Prototype_Carrier_Based_Ta_152_C_1_R14_T0', '试作舰载型Ta 152C-1/R14T0设计图', '彩', 4]
            ]
            const rows = name === 'demo-alt' ? [] : items.map(([key, zh, rarity, amount]) => [
              `research:${key}`, zh, rarity, amount || null,
              amount ? Math.max(1, Math.round(amount / 1.5)) : null, amount ? 1.5 : null
            ])
            result.metrics = [
              { label: '掉落记录', value: 79, unit: '次' },
              ...items.map(([key, zh, , amount]) => ({ label: zh, value: amount || null, unit: '', icon: `research:${key}` }))
            ]
            result.tables = [
              {
                title: `第 ${params.series || 9} 期收获明细`,
                columns: ['图标', '物品', '稀有度', '总收益', '掉落记录数', '平均每次掉落'],
                note: '每期只统计该期各艘船的图纸与该期的彩装图纸；心智与物资在「心智/物资」里看。图标暂用当前物品模板。',
                defaultSort: { index: 3, descending: true },
                rows
              },
              {
                title: '掉落记录',
                columns: ['时间', '项目', '期数', '掉落物'],
                note: '按时间倒序；只列掉了本期图纸或彩装的记录，那一次只掉心智或物资的不算。',
                defaultSort: { index: 0, descending: true },
                rows: name === 'demo-alt' ? [] : [
                  [timestamp(new Date(Date.now() - 3600000)), 'Q-268-MI', 9, '试作舰载型Ta 152C-1/R14T0设计图 x1、蓝图：邓肯 x1、蓝图：暴风雨 x1'],
                  [timestamp(new Date(Date.now() - 7200000)), 'G-531-MI', 9, '蓝图：高梁 x2'],
                  [timestamp(new Date(Date.now() - 14400000)), 'Q-051-MI', 9, '试作型三联装550mm鱼雷改（弹药调整）T0设计图 x1']
                ]
              }
            ]
          }
        }
        return result
      }
      case 'statistics.resources': {
        const base = get(name).values.Dashboard[params.resource]?.Value ?? 500
        return {
          instance: name, resource: params.resource, truncated: false, points: name === 'demo-alt' ? [] : Array.from({ length: 24 }, (_, index) => ({
            time: timestamp(new Date(Date.now() - (23 - index) * params.days * 3600000)), value: Math.max(0, Math.round(base * (.8 + index / 120 + Math.sin(index) * .03))),
          }))
        }
      }
      case 'settings.get': return structuredClone(settings)
      case 'settings.patch': {
        const fields = settings.groups.flatMap(group => group.fields)
        for (const [key, value] of Object.entries(params.values)) {
          const field = fields.find(field => field.key === key)
          if (!field || typeof value !== typeof field.value || (key === 'WebuiPort' && (!Number.isInteger(value) || value < 1 || value > 65535))) fail('INVALID_PARAMS', '部署设置无效')
        }
        for (const field of fields) if (field.key in params.values && field.key !== 'Password') field.value = params.values[field.key]
        return { updated: Object.keys(params.values) }
      }
      case 'startup.get': return { enabled: startup.has(name), remember: remember.has(name) }
      case 'startup.set':
        if (params.enabled !== undefined) { if (params.enabled) startup.add(name); else startup.delete(name) }
        if (params.remember !== undefined) { if (params.remember) remember.add(name); else remember.delete(name) }
        return { enabled: startup.has(name), remember: remember.has(name) }
      case 'announcement.get':
        return {
          announcementId: 'mock-announcement-v2',
          title: 'AzurPilot 核心控制中心 v2.4 升级公告',
          content: [
            'AzurPilot 现代化全自动化控制中心现已全面升级！支持全服 7×24 小时高稳定性调度。',
            '',
            '> [!NOTE]',
            '> 本次更新已全面集成 **KaTeX 数学公式引擎** 与 **原生安全 HTML 渲染器**，支持更丰富的动态公告展示。',
            '',
            '### 📐 算法公式与调度评估',
            '自动化调度基于强化图像匹配模型，匹配阈值满足 $\\theta \\ge 0.85$，在 $1280 \\times 720$ 画面下的综合评估目标函数如下：',
            '',
            '$$T_{\\text{schedule}} = \\sum_{i=1}^{n} \\frac{\\alpha_i \\cdot \\text{Cost}_i}{\\sqrt{\\Delta t_i + 1}} + \\mathcal{O}(\\log n)$$',
            '',
            '其中贝叶斯先验概率满足公式：$P(A|B) = \\frac{P(B|A)P(A)}{P(B)}$。',
            '',
            '### 🎨 HTML 与富文本排版能力',
            '- 快捷键操作：按下 <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>R</kbd> 可快速重载配置',
            '- 状态高亮：系统当前处于 <mark>自动化调度优化</mark> 阶段，网络链路 <font color="#10b981">● 正常连通</font>',
            '- 样式标签：支持下标 H<sub>2</sub>O、上标 x<sup>2</sup> 与 <span style="color: #60a5fa; font-weight: bold">带颜色样式的自定义文本</span>',
            '',
            '<details>',
            '<summary><b>点击展开查看详细功能清单与发布日志</b></summary>',
            '',
            '#### 📋 任务推进清单',
            '- [x] 引入 Marked + KaTeX + DOMPurify 成熟渲染生态',
            '- [x] 支持 GitHub 风格 Callout 提示块与折叠详情',
            '- [x] 优化公告卡片在深浅色主题下的视觉适配',
            '- [ ] 接入跨设备 WebSocket 实时公告推送通知',
            '',
            '#### 📊 各服务器支持状态对照',
            '| 服务器 | 状态 | 推荐延迟 | 自动重连 |',
            '| :--- | :---: | :---: | :---: |',
            '| 国服 (CN) | <font color="#10b981">极佳</font> | &lt; 35ms | 支持 |',
            '| 日服 (JP) | <font color="#10b981">良好</font> | &lt; 80ms | 支持 |',
            '| 国际服 (EN) | <font color="#60a5fa">正常</font> | &lt; 150ms | 支持 |',
            '| 台服 (TW) | <font color="#60a5fa">正常</font> | &lt; 90ms | 支持 |',
            '',
            '```python',
            '# 自动化快速启动示例',
            'from module.config.config import AzurLaneConfig',
            'config = AzurLaneConfig("alas")',
            'print(f"Server: {config.server.server}, Resolution: 1280x720")',
            '```',
            '</details>',
            '',
            '> [!TIP]',
            '> 保持模拟器分辨率为 `1280×720`（DPI 240），可获得最高的截图识别率与运行效率。',
            '',
            '更多项目详情、Issue 反馈及更新指引，欢迎参阅 [GitHub 官方仓库](https://github.com/wess09/AzurPilot)。',
          ].join('\n'),
          url: 'https://github.com/wess09/AzurPilot'
        }
      case 'events.subscribe':
        if (params.topics.some(topic => topic !== 'instances') && !name) fail('INVALID_PARAMS', '订阅此主题需要指定实例')
        return { topics: params.topics, instance: name ?? null }
      default: fail('METHOD_NOT_FOUND', '此方法由连接层处理')
    }
  }
  function tick() {
    for (const [name, item] of instances) if (item.status === 'running') {
      item.previewAt = new Date().toISOString()
      log(name, '模拟任务正在运行，等待下一轮调度。')
    }
  }
  return { dispatch, tick, setUpdateScenario }
}

import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import Ajv from 'ajv'
import {spawnSync} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import {createStockProxy} from './stock.mjs'
import {resourceFlows} from './resource-flows.mjs'

// 只读取公开的模板、元数据和翻译，绝不读取用户实例或部署文件。
const read = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'))
const args = read('../../module/config/argument/args.json')
const menu = read('../../module/config/argument/menu.json')
const template = read('../../config/template.json')
const storageCatalog = read('../../assets/stats/storage_items/catalog.json')
const contract = read('../src/api/contract.json')
const locales = Object.fromEntries(['zh-CN', 'zh-TW', 'en-US', 'ja-JP', 'zh-MIAO'].map(lang => [lang, read(`../../module/config/i18n/${lang}.json`)]))
const ajv = new Ajv({ strict: false, useDefaults: true })
const validators = Object.fromEntries(Object.entries(contract.methods).map(([method, entry]) => [method, ajv.compile(entry.params)]))
const revision = values => createHash('sha256').update(JSON.stringify(values)).digest('hex')
// 与后端按游戏包名确定地区的规则一致，开服检测配置不参与判断。
const region = packageName => !packageName || packageName === 'auto' ? null : ({
  en: 'en', jp: 'jp', tw: 'tw',
  'com.YoStarEN.AzurLane': 'en', 'com.YoStarJP.AzurLane': 'jp', 'com.hkmanjuu.azurlane.gp': 'tw',
  'com.hkmanjuu.azurlane.gp.mc': 'tw',
})[packageName] ?? 'cn'
const timestamp = date => date.toISOString().slice(0, 19).replace('T', ' ')
const translate = key => key.split('.').reduce((value, part) => value?.[part], locales['zh-CN']) ?? key
export const fail = (code, message, details = null) => { throw Object.assign(new Error(message), { code, details }) }

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
  const mindShips = new Map()
  function mindPython(action, params) {
    const run = spawnSync('uv', ['run', '--no-sync', 'python', '-X', 'utf8', '-m', 'dev_tools.mind_calculator_mock'], {
      cwd: fileURLToPath(new URL('../../', import.meta.url)), input: JSON.stringify({action, ...params}),
      encoding: 'utf8', timeout: 30000, windowsHide: true,
    })
    if (run.error || run.status) fail('INTERNAL_ERROR', '计算器模拟服务运行失败')
    const result = JSON.parse(run.stdout)
    if (result.error) fail('INVALID_PARAMS', result.error)
    return result
  }
  const stock = createStockProxy(name=>{const r=get(name).values.Dashboard.ActionPoint;return r?.Total!=null&&r.Record?{instance:name,actionPoints:r.Total,observedAt:Math.floor(new Date(r.Record.replace(' ','T')+'Z').getTime()/1000)}:null})
  const programs = new Map()
  const simulations = new Map()
  function simulation(name) {
    if (!simulations.has(name)) simulations.set(name, {
      state: 'idle', running: false, runId: 0, completedSamples: 0, totalSamples: 0,
      error: '', result: null, figure: null, image: null, entries: [], cursor: 0, floor: 0,
    })
    return simulations.get(name)
  }
  function simulationLog(item, text) {
    item.entries.push({id: ++item.cursor, level: 'INFO', text: `INFO ${timestamp(new Date())} │ [大世界模拟器] ${text}`})
  }
  function simulationStatus(name, after = 0) {
    const {image, entries, cursor, floor, ...status} = simulation(name)
    const reset = after <= floor || after > cursor
    return structuredClone({...status, instance: name,
      logs: {instance: name, cursor, reset, entries: entries.filter(entry => reset || entry.id > after)}})
  }
  let cardCatalog
  function programPython(action, config, params = {}) {
    const run = spawnSync('uv', ['run', '--no-sync', 'python', '-X', 'utf8', '-m', 'dev_tools.scheduler_mock'], {
      cwd: fileURLToPath(new URL('../../', import.meta.url)), input: JSON.stringify({action, config, ...params}),
      encoding: 'utf8', timeout: 15000, windowsHide: true,
    })
    if (run.error || run.status) fail('INTERNAL_ERROR', '模拟解释器运行失败')
    const result = JSON.parse(run.stdout)
    if (result.error) fail('INVALID_PARAMS', result.error)
    return result
  }
  function program(name) {
    if (!cardCatalog) cardCatalog = programPython('catalog', get(name).values)
    if (!programs.has(name)) {
      const isShowcase = name === 'demo-main' && cardCatalog.templates.all
      const draft = isShowcase ? structuredClone(cardCatalog.templates.all) : structuredClone(cardCatalog.templates.takeover)
      programs.set(name, {mode: 'native', draft, active:null, generation:0})
    }
    const current = programs.get(name)
    return {...structuredClone(current), revision:revision(current)}
  }
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
  // 日志时间与真实后端一致使用本地时区（timestamp() 供调度比较，保持 UTC）。
  const logTime = date => [date.getHours(), date.getMinutes(), date.getSeconds()].map(n => String(n).padStart(2, '0')).join(':')
    + '.' + String(date.getMilliseconds()).padStart(3, '0')
  function log(name, text, level = 'INFO') {
    const instance = get(name)
    const now = new Date()
    instance.logs.push({
      id: ++instance.cursor, level,
      // 与真实后端 web_formatter 一致：级别列宽 8、时分秒加毫秒、竖线分隔；多行文本只挂首行前缀。
      text: `${level.padEnd(8)} ${logTime(now)} │ ${text}`,
    })
    instance.logs = instance.logs.slice(-400)
  }
  // 独立渲染对象（分割线、居中标题等）不带级别与时间前缀，与真实后端一致。
  function logRaw(name, text, level = 'INFO') {
    const instance = get(name)
    instance.logs.push({ id: ++instance.cursor, level, text })
    instance.logs = instance.logs.slice(-400)
  }
  function add(name, values) {
    instances.set(name, { values: structuredClone(values), status: 'stopped', logs: [], cursor: 0 })
    log(name, '测试实例已就绪，所有操作均为模拟。')
  }
  // 中文与全角字符按两列计宽，保证演示日志里的 Rich 框线在等宽字体下右缘对齐。
  const displayWidth = text => [...text].reduce((sum, ch) => sum + (/[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/.test(ch) ? 2 : 1), 0)
  const padDisplay = (text, size) => text + ' '.repeat(Math.max(0, size - displayWidth(text)))
  // 按真实 Rich 排版生成异常堆栈：外层框含源码行与 locals 子框，框内嵌套框。
  function stackTraceText() {
    const W = 149
    const box = (title, rows, w = W) => [
      title
        ? `╭${'─'.repeat(Math.floor((w - 2 - displayWidth(title) - 2) / 2))} ${title} ${'─'.repeat(Math.ceil((w - 2 - displayWidth(title) - 2) / 2))}╮`
        : `╭${'─'.repeat(w - 2)}╮`,
      ...rows.map(row => `│ ${padDisplay(row, w - 4)} │`),
      `╰${'─'.repeat(w - 2)}╯`,
    ]
    const locals = box('locals', [
      `command = 'opsi_ash_beacon'`,
      `set_task = <function set_task at 0x0000015959B907D0>`,
      `skip_first_screenshot = False`,
    ], W - 10)
    const metaLocals = box('locals', [`self = <module.os_ash.meta.OpsiAshBeacon object at 0x0000015941D4AFD0>`], W - 10)
    const rows = [
      ...box('Traceback (most recent call last)', [
        ``,
        `E:\\AzurPilot\\alas.py:1019 in run`,
        ``,
        `  1017 │   │   │   elif not self._channel_float_done:`,
        `  1018 │   │   │   │   self.handle_channel_float()`,
        `❱ 1019 │   │   │   self.__getattribute__(command)()`,
        `  1020 │   │   │   return True`,
        `  1021 │   │   except TaskEnd:`,
        ``,
        ...locals,
        ``,
        `E:\\AzurPilot\\module\\os_ash\\meta.py:616 in run`,
        ``,
        `  614 │   │   """执行信标攻击任务主流程：进入 META 页面、攻击、领取奖励、延迟到下次服务器更新。"""`,
        `  615 │   │   self.ui_ensure(page_reward)`,
        `❱ 616 │   │   self._begin_beacon()`,
        `  617 │   │   self.ui_goto_main()`,
        ``,
        ...metaLocals,
        ``,
      ]),
      `ScriptEnd: [心情-保底] 计算模式红脸弹窗，心情清零并延时`,
    ]
    return rows.join('\n')
  }
  // 注入覆盖各种真实日志形态的演示数据：各级别、分割线、居中标题、属性对齐、多行消息、海图识别、透视边缘、表格与异常堆栈。
  function seedLogShowcase(name) {
    const seed = (text, level = 'INFO') => log(name, text, level)
    const bare = (text, level = 'INFO') => logRaw(name, text, level)
    const W = 160
    const rule = (char, title) => {
      if (!title) return char.repeat(W)
      const span = W - displayWidth(title) - 2
      return char.repeat(Math.floor(span / 2)) + ' ' + title + ' ' + char.repeat(Math.ceil(span / 2))
    }
    const indent = ' '.repeat(9)

    bare(rule('═'))
    bare(padDisplay('调度器', Math.floor((W - displayWidth('调度器')) / 2) * 2 + displayWidth('调度器')))
    bare(rule('═'))
    seed('调度器已就绪，开始按任务队列执行')
    bare(rule('═', 'COMMISSION'))
    seed('COMMISSION')
    bare(rule('─', 'SUB_STAGE'))
    seed('SUB_STAGE')
    seed('<<< 查找所有舰队 >>>')
    seed('[META作战] 战斗结束并回到正确页面')

    // 1. 海域透视与边缘线识别（完整闭合 vs 边缘缺失对比）
    // 样例 A: 四边完整闭合 (全绿高亮)
    seed('[地图-透视] 0.045s  _   水平: 7 (7 内部, 0 边缘)')
    seed('[地图-透视] 边缘: /_\\    垂直: 8 (8 内部, 0 边缘)')

    // 样例 B: 右边缘与下边缘缺失 (视角滑至海域右下角，右/下红虚线警示)
    seed('[地图-透视] 0.041s      水平: 5 (5 内部, 0 边缘)')
    seed('[地图-透视] 边缘: /_     垂直: 6 (6 内部, 0 边缘)')

    // 样例 C: 单应性左边缘缺失 (单应性位置偏左，左红虚线警示)
    seed('[地图-单应性] 0.038s  _   边缘线: 1 水平, 2 垂直')
    seed('[地图-单应性] 边缘:  _\\   单应位置: (  4,   2)')

    // 2. 连续右对齐属性块 (attr_align)
    seed(`${padDisplay('摄像机', 22)}: (4, 3)`)
    seed(`${padDisplay('摄像机修正', 22)}: (4, 3) -> (5, 3)`)
    seed(`${padDisplay('之前中心偏移', 22)}: (12, -4)`)
    seed(`${padDisplay('敌舰覆盖', 22)}: [C3, D4, E2]`)

    // 3. 局部海图视野 (view.show)
    seed('.. .. ++ ++ -- -- -- --')
    seed('.. ++ ++ -- 1M -- -- --')
    seed('++ ++ -- -- -- -- 2C --')
    seed('-- -- FL -- -- -- ++ ++')
    seed('-- -- -- MY -- ++ ++ ++')

    // 4. 全局海图主网格 (map.show)
    seed('[地图-显示]   A  B  C  D  E  F  G  H')
    seed(' 1 ++ ++ ++ -- -- -- -- --')
    seed(' 2 ++ ++ ++ -- 1M -- -- --')
    seed(' 3 -- -- -- -- -- -- 2C --')
    seed(' 4 -- -- FL -- -- -- -- --')
    seed(' 5 -- -- -- -- MY ++ ++ ++')
    seed(' 6 -- -- -- -- -- ++ ++ ++')
    seed(' 7 ++ ++ ++ -- -- -- -- --')

    // 5. 寻路代价网格 (map.show_cost)
    seed('      A    B    C    D    E    F    G    H')
    seed(' 1 9999 9999 9999    4    5    6    7    8')
    seed(' 2 9999 9999 9999    3    4    5    6    7')
    seed(' 3    3    2    1    2    3    4    5    6')
    seed(' 4    2    1    0    1    2    3    4    5')
    seed(' 5    3    2    1    2    3 9999 9999 9999')
    seed(' 6    4    3    2    3    4 9999 9999 9999')
    seed(' 7 9999 9999 9999    4    5    6    7    8')

    // 6. 大世界雷达扫描 (radar.show)
    seed('-- -- -- -- -- -- -- -- -- --')
    seed('-- AK -- PO -- RE -- -- 1E --')
    seed('-- -- -- -- -- == == -- -- --')
    seed('-- -- FL -- -- == == -- EX --')
    seed('-- AR -- -- ME -- -- -- -- SD')
    seed('-- QU -- -- -- -- EN -- -- --')

    // 7.1 Rich Table: 设备基准测试 (Device Benchmark)
    bare([
      '                                                                        Benchmark Result                                                                        ',
      '                                                          ┌──────────────┬──────────┬──────┬─────────┐                                                          ',
      '                                                          │ Device       │  Method  │  FPS │ Latency │                                                          ',
      '                                                          ├──────────────┼──────────┼──────┼─────────┤                                                          ',
      '                                                          │ MuMuPlayer12 │ nemu_ipc │ 58.4 │  0.005s │                                                          ',
      '                                                          │ MuMuPlayer12 │    u2    │ 18.2 │  0.052s │                                                          ',
      '                                                          │ MuMuPlayer12 │  adb_nc  │ 24.1 │  0.038s │                                                          ',
      '                                                          └──────────────┴──────────┴──────┴─────────┘                                                          '
    ].join('\n'))

    // 7.2 Rich Table: 截图方式性能测试 (Screenshot Benchmark)
    bare([
      '                                                                      Screenshot Benchmark                                                                      ',
      '                                                          ┌──────────────┬────────┬─────────┐                                                           ',
      '                                                          │ Screenshot   │  Time  │  Speed  │                                                           ',
      '                                                          ├──────────────┼────────┼─────────┤                                                           ',
      '                                                          │ nemu_ipc     │ 0.005s │ Fastest │                                                           ',
      '                                                          │ DroidCast    │ 0.018s │  Fast   │                                                           ',
      '                                                          │ uiautomator2 │ 0.052s │ Medium  │                                                           ',
      '                                                          │ ADB          │ 0.319s │  Slow   │                                                           ',
      '                                                          │ aScreenCap   │ Failed │ Failed  │                                                           ',
      '                                                          └──────────────┴────────┴─────────┘                                                           '
    ].join('\n'))

    // 7.3 Rich Table: 控制点击方式测试 (Click Benchmark)
    bare([
      '                                                                         Click Benchmark                                                                        ',
      '                                                          ┌──────────────┬────────┬─────────┐                                                           ',
      '                                                          │ Control      │  Time  │  Speed  │                                                           ',
      '                                                          ├──────────────┼────────┼─────────┤                                                           ',
      '                                                          │ minitouch    │ 0.012s │ Fastest │                                                           ',
      '                                                          │ ADB_NC       │ 0.038s │  Fast   │                                                           ',
      '                                                          │ uiautomator2 │ 0.052s │  Fast   │                                                           ',
      '                                                          │ ADB          │ 0.120s │ Medium  │                                                           ',
      '                                                          └──────────────┴────────┴─────────┘                                                           '
    ].join('\n'))

    // 7.4 Rich Table: OCR 识别基准摘要 (OCR Benchmark Summary)
    bare([
      '                                                                        OCR基准测试摘要                                                                         ',
      '                                        ┌──────────┬──────────┬──────────────────┬──────────┬────────┬────────┐                                         ',
      '                                        │ Model    │ Dataset  │ Accuracy         │ Avg Time │ Rating │ Status │                                         ',
      '                                        ├──────────┼──────────┼──────────────────┼──────────┼────────┼────────┤                                         ',
      '                                        │ CRNN     │ general  │ 100.00% (50/50)  │ 12.345 ms│ Fast   │  PASS  │                                         ',
      '                                        │ Paddle   │ button   │  96.00% (48/50)  │ 28.120 ms│ Good   │  PASS  │                                         ',
      '                                        │ CNS      │ number   │  85.00% (42/50)  │  8.500 ms│ Fast   │ Warning│                                         ',
      '                                        └──────────┴──────────┴──────────────────┴──────────┴────────┴────────┘                                         '
    ].join('\n'))

    // 7.5 Rich Table: 指挥喵评分汇总 (Meowfficer Score Summary)
    bare([
      '                                                                           评分汇总                                                                             ',
      '                                                            ┌────────┬────────┬──────────┬──────┬────────┐                                                      ',
      '                                                            │ 来源   │ 指挥喵 │ 口径     │ 档位 │ 参考分 │                                                      ',
      '                                                            ├────────┼────────┼──────────┼──────┼────────┤                                                      ',
      '                                                            │ 喵窝-1 │ 莫桑   │ 战列旗舰 │  T0  │ 96/100 │                                                      ',
      '                                                            │ 喵窝-2 │ 小吉丸 │ 驱逐雷击 │  T1  │ 85/100 │                                                      ',
      '                                                            │ 喵窝-3 │ 伯克   │ 巡洋雷击 │  T2  │ 72/100 │                                                      ',
      '                                                            └────────┴────────┴──────────┴──────┴────────┘                                                      '
    ].join('\n'))

    // 7.6 ASCII Table: 经典 ASCII 字符画表格 (Legacy ASCII Table)
    bare([
      '                                                                    Legacy ASCII Benchmark                                                                      ',
      '                                                          +--------------+--------+--------+                                                            ',
      '                                                          |  Screenshot  |  Time  | Speed  |                                                            ',
      '                                                          +--------------+--------+--------+                                                            ',
      '                                                          |     ADB      | 0.319s |  Fast  |                                                            ',
      '                                                          | uiautomator2 | 0.476s | Medium |                                                            ',
      '                                                          |  aScreenCap  | Failed | Failed |                                                            ',
      '                                                          +--------------+--------+--------+                                                            '
    ].join('\n'))

    seed('带有路径 E:\\AzurPilot\\module\\os_ash\\meta.py 和 True/False/None', 'WARNING')
    seed('大括号 { [ ( ) ] }，相对路径 ./relative/path/log.txt')
    seed(`多行消息：当前任务队列\n${indent}Commission（进行中）\n${indent}Research（等待下一轮）`)

    // 9. 统一错误上下文 (error_context) 与完整堆栈
    seed('[错误] 任务执行发生未处理异常（opsi_ash_beacon）\n'
      + `${indent}原因：程序抛出了 ScriptEnd，具体原因需要结合下方堆栈定位。\n`
      + `${indent}影响：当前任务无法确认执行结果，调度器将尝试重启恢复。\n`
      + `${indent}建议：查看错误现场中的 log.txt、截图和完整堆栈，确认是否需要更新资源或提交问题。\n`
      + `${indent}异常：ScriptEnd: [心情-保底] 计算模式红脸弹窗，心情清零并延时\n`
      + stackTraceText().split('\n').map(line => indent + line).join('\n'), 'ERROR')

    // 10. LLM 智能分析报告
    bare(rule('═', '[LLM] LLM 错误分析'))
    seed('[LLM] 正在调用 LLM 分析异常原因...')
    seed('[LLM] 该错误已被 LLM 分析过，直接复用上次的分析结果以节省 API ...')
    seed(`[LLM] \n[LLM 分析报告 (由 gpt-4o-mini 提供, 复用缓存)]\n### 根本原因\n任务在执行 \`opsi_ash_beacon\` 时遇到了心情归零保底机制，触发了 \`ScriptEnd\` 正常流程中断。\n\n### 处置建议\n1. 检查调度设置中的心情恢复时长；\n2. 确认大世界信标是否已进入冷却状态。`)
    bare(rule('═', '[LLM] LLM 分析结束'))

    seed('CRITICAL 级别消息，用于验证最高级别配色', 'CRITICAL')
    seed('DEBUG 级别消息，级别筛选为 ALL 时同样可见', 'DEBUG')
    bare(rule('─'))
  }
  if (!empty) {
    for (const [index, name] of ['demo-main', 'demo-alt', 'demo-error', 'demo-dog'].entries()) {
      const values = structuredClone(template)
      values.Main.Emotion.Fleet1Record = '2026-09-12 23:45:12.123456'
      values.Main.Scheduler.NextRun = '2099-01-01 12:00:00'
      values.Alas.Emulator.Serial = `127.0.0.1:${5555 + index * 2}`
      values.Alas.Emulator.ServerName = 'cn_android-20'
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
      seedLogShowcase(name)
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
      case 'instances.list': return [...instances].map(([name, item]) => ({ name, status: item.status, currentTask: item.status === 'running' ? item.currentTask ?? 'Commission' : null, serial: item.values.Alas.Emulator.Serial, server: item.values.Alas.Emulator.ServerName, region: region(item.values.Alas.Emulator.PackageName) }))
      case 'instances.create': {
        if (!/^[A-Za-z0-9\u3041-\u3096\u30a1-\u30fa\u30fc\u31f0-\u31ff\uff66-\uff9f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff][A-Za-z0-9_. \u3041-\u3096\u30a1-\u30fa\u30fc\u31f0-\u31ff\uff66-\uff9f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\-]{0,63}$/.test(params.name) || /^(template|deploy|backup|con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i.test(params.name)) fail('INVALID_PARAMS', '实例名称无效')
        if ([...instances.keys()].some(name => name.toLowerCase() === params.name.toLowerCase())) fail('ALREADY_EXISTS', '同名实例已存在')
        add(params.name, params.source ? get(params.source).values : template)
        if (params.source && programs.has(params.source)) {const {mode,draft,active} = program(params.source); programs.set(params.name,{mode,draft,active,generation:0})}
        return snapshot(params.name)
      }
      case 'instances.delete':
        if (get(name).status === 'running') fail('INSTANCE_RUNNING', '请先停止实例再删除')
        if (simulations.get(name)?.running) fail('SIMULATOR_RUNNING', '请先中断大世界模拟器再删除实例')
        if (params.revision !== snapshot(name).revision) fail('CONFLICT', '配置已变化，请重新加载后删除')
        instances.delete(name); startup.delete(name); programs.delete(name); simulations.delete(name)
        return { deleted: name }
      case 'config.get': return snapshot(name)
      case 'config.export': {
        if (!programs.has(name)) return snapshot(name).values
        const {mode, draft, active} = program(name)
        return {...snapshot(name).values, ...(programs.has(name) ? {_schedulerProgram: {mode,draft,active}} : {})}
      }
      case 'scheduler.program.catalog': {
        const catalog = programPython('catalog', get(name).values)
        catalog.resources.forEach(r => {r.label = translate(`${r.name}._info.name`)})
        return catalog
      }
      case 'scheduler.program.get': return program(name)
      case 'scheduler.program.save': {
        const current = program(name)
        if (params.revision !== current.revision) fail('CONFLICT', '方案已变化，请重新加载')
        delete current.revision; current.draft = params.document; programs.set(name, current)
        return program(name)
      }
      case 'scheduler.program.validate': return programPython('validate', get(name).values, params)
      case 'scheduler.program.simulate': return programPython('simulate', get(name).values, params)
      case 'scheduler.program.apply': {
        const current = program(name)
        if (params.revision !== current.revision) fail('CONFLICT', '方案已变化，请重新加载')
        const result = programPython('validate', get(name).values, {document:current.draft, mode:params.mode})
        if (params.mode !== 'native' && !result.valid) fail('INVALID_PARAMS', '程序校验失败', result.diagnostics)
        delete current.revision; current.mode = params.mode; current.active = structuredClone(current.draft); current.generation += 1
        programs.set(name, current); return program(name)
      }
      case 'scheduler.program.state': return {mode:program(name).mode, generation:program(name).generation, state:{status:'idle',trace:[]}}
      case 'config.patch': {
        const data = snapshot(name)
        const seen = new Set()
        for (const { path, value } of params.changes) {
          const [task, group, arg] = validateField(path, value)
          if (seen.has(path)) fail('INVALID_PARAMS', '同一次保存不能重复修改同一个参数')
          seen.add(path)
          data.values[task] ??= {}; data.values[task][group] ??= {}
          data.values[task][group][arg] = value
        }
        get(name).values = data.values
        log(name, `已保存 ${params.changes.length} 项配置。`)
        return snapshot(name)
      }
      case 'overview.get': return overview(name)
      case 'mind.catalog': return mindPython('catalog', params)
      case 'mind.calculate': return mindPython('calculate', params)
      case 'mind.report': {
        const range = get(name).values.MindCalculatorScan.MindCalculator
        return {...mindPython('report', {ships: mindShips.get(name) ?? []}), instance: name, updated_at: '', min_level: range.MinLevel, max_level: range.MaxLevel}
      }
      case 'mind.save': {
        const current = mindPython('report', {ships: mindShips.get(name) ?? []})
        if (current.revision !== params.revision) fail('CONFLICT', '舰船数据已变化，请重新载入后再保存')
        mindShips.set(name, params.ships)
        return dispatch('mind.report', {instance: name})
      }
      case 'mind.import': return mindPython('import', params)
      case 'mind.recognize': return mindPython('recognize', params)
      case 'mind.export': return mindPython('export', {...params, ships: mindShips.get(name) ?? []})
      case 'stock.status': return stock.status(name)
      case 'stock.rebuild': return stock.rebuild(name,params)
      case 'stock.request': return stock.request(name,params)
      case 'scheduler.start': case 'tasks.run':
        if (get(name).status === 'running') fail('INSTANCE_RUNNING', '实例已在运行')
        if (method === 'tasks.run' && !['FleetScan', 'StorageStatistics'].includes(params.task) && !Object.values(menu).some(group => group.page === 'tool' && group.tasks.includes(params.task))) fail('INVALID_PARAMS', '该任务不支持单独运行')
        get(name).status = 'running'; get(name).currentTask = params.task ?? 'Commission'; log(name, '模拟调度器已启动。')
        return overview(name)
      case 'scheduler.stop':
        get(name).status = 'stopped'; log(name, '模拟调度器已停止。')
        return overview(name)
      case 'logs.get': {
        const item = get(name)
        const reset = params.after > item.cursor || params.after < (item.logs[0]?.id ?? 1) - 1
        return { instance: name, cursor: item.cursor, reset, entries: item.logs.filter(entry => reset || entry.id > params.after) }
      }
      case 'opsi.simulator.status': return simulationStatus(name, params.after)
      case 'opsi.simulator.start': {
        const item = simulation(name)
        if (item.running) fail('SIMULATOR_RUNNING', '模拟正在进行，请先中断或等待完成')
        const settings = get(name).values.OpsiSimulator.OpsiSimulatorParameters
        Object.assign(item, {state: 'running', running: true, runId: item.runId + 1,
          completedSamples: 0, totalSamples: settings.Deterministic ? 1 : settings.Samples,
          error: '', result: null, figure: null, image: null, entries: [], floor: item.cursor})
        simulationLog(item, '模拟服务示例已启动。')
        return simulationStatus(name)
      }
      case 'opsi.simulator.stop': {
        const item = simulation(name)
        if (item.running) {
          item.state = 'interrupted'; item.running = false
          simulationLog(item, '模拟中断。')
        }
        return simulationStatus(name)
      }
      case 'opsi.simulator.figure': return {instance: name, image: simulation(name).image}
      case 'preview.capture': {
        if (!get(name).previewAt) return { instance: name, image: null, capturedAt: null }
        const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#142d3a"/><circle cx="640" cy="300" r="145" fill="none" stroke="#78dac4" stroke-width="3"/><path d="M640 190 720 370 640 330 560 370Z" fill="#78dac4"/><text x="640" y="530" text-anchor="middle" fill="#d5ede9" font-size="32">AzurPilot · 模拟器测试画面</text></svg>'
        return { instance: name, image: `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`, capturedAt: get(name).previewAt ?? null }
      }
      case 'statistics.refreshLoot': return { refreshed: true }
      case 'meowfficer.scoreReport': {
        // demo-alt 用来验证「还没跑过评分任务」的空状态，其余实例都给一份示例报告。
        if (name === 'demo-alt') fail('NOT_FOUND', '评分报告尚未生成，请先在「工具 → 指挥喵评分」运行一次任务')
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
      case 'statistics.resourceFlows': return resourceFlows(params, snapshot(name), storageCatalog, name === 'demo-alt')
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
        if (params.category === 'storage') {
          result.notes = [name === 'demo-alt' ? '尚未运行仓库统计任务。' : '最近完整扫描：2026-10-03 00:00:00；复核 12 页。', '刷新只读取已有快照，运行仓库统计任务后才更新数量。']
          const quantities = [153, 46, 20, 46, 58, 1, 32791, 1204, 881, 497, 1659, 1266, 1628, 745, 5015, 3584, 3785, 5634, 4230, 5297, 699, 859, 884, 753, 767]
          result.series = storageCatalog.items.map((item, index) => ({
            key: item.id, label: item.name,
            icon: 'storage:' + item.templates[0].replace('assets/stats/', '').replace('.png', ''),
            points: name === 'demo-alt' ? [] : [8, 3, 1, 0]
              .filter(days => days < (params.days ?? 7))
              .map(days => ({t: Math.floor((Date.now() - days * 86400000) / 1000) * 1000000,
                v: Math.max(1, quantities[index] - days * 3), s: '仓库统计（cn）'})),
          }))
          result.tables = [{title: '仓库物品', note: result.notes.join(' '), columns: ['图标', '物品', '分类', '数量', '状态'],
            rows: storageCatalog.items.map((item, index) => [
              'storage:' + item.templates[0].replace('assets/stats/', '').replace('.png', ''),
              item.name, item.group, name === 'demo-alt' ? null : quantities[index], name === 'demo-alt' ? '未扫描' : '已复核',
            ])}]
        } else if (params.category === 'resources') {
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
          // 上面收益卡片（指定掉落物品 + 今日/本月/选定月份总计）、中间收获明细、
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
            ['GearDesignPlanPlaneT5', '舰载机研发图纸UR型', '彩', 1, 1],
            ['GearDesignPlanT5', '装备研发图纸UR型', '彩', 1, 1],
            ['GearDesignPlanGunT4', '舰炮研发图纸SSR型', '金', 7, 4],
            ['GearDesignPlanTorpedoT4', '鱼雷研发图纸SSR型', '金', 5, 3],
            ['GearDesignPlanAntiAirT4', '防空炮研发图纸SSR型', '金', 6, 4],
            ['GearDesignPlanPlaneT4', '舰载机研发图纸SSR型', '金', 4, 2],
            ['Ultra_High_Purity_Metals', '特种钢材', '金', 14, 8],
            ['Military_Grade_Electronic_Components', '军工级电子元件', '金', 12, 7],
            ['HBX_Blend_Gunpowder', 'HBX炸药', '金', 11, 6],
            ['High_Durability_Elastomers', '氟橡胶', '金', 10, 5],
            ['Superconductive_Metals', '超导铜', '金', 13, 7],
            ['Corrosion_Resistant_Alloys', '钛合金', '金', 9, 5],
            ['OrdnanceTestingReportT4', '机密实验计划', '金', 3, 3],
            ['OrdnanceTestingReportT5', '绝密实验计划', '彩', 1, 1],
            ['PrototypeGearPartsT5', '特装型突破部件', '彩', 2, 2]
          ]
          const empty = name === 'demo-alt'
          result.taskOptions = [
            { key: 'opsi_daily', label: '大世界每日', count: 0 },
            { key: 'opsi_obscure', label: '隐秘海域', count: 0 },
            { key: 'opsi_abyssal', label: '深渊坐标', count: 0 },
            { key: 'opsi_stronghold', label: '塞壬要塞', count: empty ? 0 : 1 },
            { key: 'opsi_month_boss', label: '月度Boss', count: empty ? 0 : 1 },
            { key: 'opsi_meowfficer_farming', label: '耄耋相接', count: empty ? 0 : 19 }
          ]
          const detail = {
            title: '大世界掉落明细',
            columns: ['图标', '物品', '稀有度', '总收益', '掉落记录数', '平均每次掉落'],
            note: '统计金菜（部件T4）、装备研发图纸SSR/UR型、六种金色研发材料、机密/绝密实验计划及特装型突破部件；其他物品照常入库，只是不在这里展示。',
            defaultSort: { index: 3, descending: true },
            rows: empty ? [] : items.map(([key, zh, rarity, amount, count]) => [
              `opsi:${key}`, zh, rarity, amount || null, count || null, count ? Math.round(amount / count * 10) / 10 : null
            ])
          }
          result.metrics = empty ? [] : [
            { label: '掉落记录', value: 21, unit: '次' },
            ...items.map(([key, zh, , amount]) => ({ label: zh, value: amount || null, unit: '', icon: `opsi:${key}` })),
            { label: '今日总计', value: 7, unit: '' },
            { label: '本月总计', value: items.reduce((total, item) => total + item[3], 0), unit: '' },
            { label: '选定月份总计', value: items.reduce((total, item) => total + item[3], 0), unit: '' }
          ]
          result.tables = empty ? [detail] : [
            detail,
            {
              title: '掉落记录',
              columns: ['时间', '任务', '海域', '掉落物'],
              note: '按时间倒序；只列含上述统计物品的掉落记录，其余掉落不入这张表。',
              defaultSort: { index: 0, descending: true },
              rows: [
                ['2026-09-25 08:00:00', '月度Boss', '月度Boss海域', '机密实验计划 x1、绝密实验计划 x1、特装型突破部件 x1、特种钢材 x2、装备研发图纸UR型 x1'],
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
      case 'background.access': return {token: 'mock-background-token'}
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
      case 'background.gallery.list': return []
      case 'background.gallery.open': return { path: 'cache/background/library' }
      case 'background.gallery.remove': return { removed: true }
      case 'background.gallery.add': return { entry: { id: 'mock_bg', name: params.name || 'mock', kind: 'image', size: 1024, added: Date.now() } }
      default: fail('METHOD_NOT_FOUND', '此方法由连接层处理')
    }
  }
  function tick() {
    for (const [name, item] of simulations) if (item.running) {
      const settings = get(name).values.OpsiSimulator.OpsiSimulatorParameters
      item.running = false
      if (!(settings.TimeUseRatio > 0 && settings.TimeUseRatio <= 1) || item.totalSamples <= 0) {
        item.state = 'failed'; item.error = '样本数和时间利用率必须为正数，利用率不能超过 1'
        simulationLog(item, item.error)
        continue
      }
      item.state = 'completed'; item.completedSamples = item.totalSamples
      item.result = {cl1Count: 123, meowCount: 45, crashedProbability: .02,
        cl1Time: 7380, meowTime: 9000, ap: 485.3, coin: 100510}
      if (settings.Draw !== 'do_not') {
        item.figure = `mock-${item.runId}.svg`
        const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="300"><rect width="900" height="300" fill="white"/><text x="40" y="35" font-size="18">模拟服务示例轨迹</text><path d="M40 70 250 140 450 90 650 180 860 200" fill="none" stroke="blue"/><path d="M40 230 250 180 450 140 650 100 860 70" fill="none" stroke="orange"/></svg>'
        item.image = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`
      }
      simulationLog(item, '[模拟结果] 最终行动力: 485.3，最终黄币: 100510（模拟服务示例）。')
    }
    for (const [name, item] of instances) if (item.status === 'running') {
      item.previewAt = new Date().toISOString()
      log(name, '模拟任务正在运行，等待下一轮调度。')
    }
  }
  return { dispatch, tick, setUpdateScenario, subscribeStock:stock.subscribe, close:stock.close }
}

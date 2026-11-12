/**
 * @fileoverview 过滤器语法高亮编辑器组件（基于 CodeMirror 6）。
 * 全面支持 Alas 全套过滤器语法体系：
 * 1. 委托过滤器（Commission Filter）：Daily/Urgent/Extra/Major/Night 类别、Gem/Cube/Drill/Oil/Box/Part/Resource/Event/Book/Retrofit/Ship 产出、时间 0:30/1.5/4、tier 价值分层徽章、shortest 兜底徽章
 * 2. 科研过滤器（Research Filter）：S1-S9 系列、DR/PRY/PR 稀有度、B/C/D/E/G/H/Q/T 类型代码、科研船名（monarch/drake/kearsarge...）、项目编号（如 315/031）、时长、reset 警示红徽章、shortest 最短徽章、cheapest 节能徽章
 * 3. 商店/活动兑换/海域物资（Shop & Supply Items）：EquipUR/SSR、GachaTicket、Augment 兵装、Plate 部件、Book 教材、Food 粮食、Cat 喵箱、Logger 记录仪、ActionPoint、PurpleCoins、大世界特种材料与各兑换船名
 * 4. 战术学院过滤器（Tactical Filter）：SameT1~T4 同系加成徽章、Red/Blue/YellowT1~T4 教材颜色与等级组合、first/second/third 预设词
 * 5. 后宅喂食过滤器（Dorm Feed Filter）：20000/10000/5000/3000/2000/1000 专属存粮容量高亮
 * 6. 舰队、关卡与稀有度过滤器：Fleet-1~6、CallSubmarine、关卡代码 (A1~D3/SP/EX/11-4)、稀有度 (ultra/super_rare/elite...)、退役狗粮船名 (bogue/ranger/langley...)
 * 7. 系统调度任务优先级（Yukikaze / OpsiScheduling）：Restart、Commission、Tactical、Research 等所有核心任务名胶囊高亮
 */

import { useEffect, useRef } from 'react'
import { Annotation, Compartment, EditorState } from '@codemirror/state'
import {
  Decoration,
  EditorView,
  keymap,
  MatchDecorator,
  ViewPlugin,
  type DecorationSet,
  type ViewUpdate,
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'

const externalChange = Annotation.define<boolean>()

/** 优先级连接符号 (>) */
const ARROW_PATTERN = /^[>＞﹥›˃ᐳ❯]+$/

/** 策略控制与预设标记 */
const TIER_MARKER_PATTERN = /^tier$/i
const RESET_PATTERN = /^reset$/i
const SHORTEST_PATTERN = /^shortest$/i
const CHEAPEST_PATTERN = /^cheapest$/i
const PRESET_PATTERN = /^(first|second|third|skip|all)$/i

/** 后宅存粮容量规格 */
const DORM_FOOD_PATTERN = /^(20000|10000|5000|3000|2000|1000)$/

/** 纯时间格式 */
const PURE_TIME_PATTERN = /^\d{1,2}:\d{2}$/

/** 舰队与潜艇召唤指令 */
const FLEET_PATTERN = /^(fleet-?[1-6]|callsubmarine|submarine)$/i

/** 稀有度级别指令 */
const RARITY_PATTERN = /^(ultra|super_rare|elite|rare|common|ur|ssr|sr|r|n)$/i

/** 关卡代码与难度级别 */
const STAGE_PATTERN = /^(?:[a-d][1-4]|sp\d*|ex|esp|t[1-4]|\d{1,2}-\d{1,2}|easy|normal|hard)$/i

/** 岛屿打工人标记 */
const WORKER_PATTERN = /^workerjuu$/i

/** 常见退役/强化狗粮舰船名 */
const FODDER_SHIP_PATTERN = /^(bogue|ranger|langley|hermes|z20|z21|aulick|foote|cassin|downes)$/i

/** Alas 核心系统调度任务名称（YukikazeTaskManager / OpsiScheduling） */
const SYSTEM_TASK_PATTERN =
  /^(restart|opsicrossmonth|commission|tactical|research|exercise|dorm|meowfficer|guild|gacha|reward|storagestatistics|shopfrequent|shoponce|shipyard|freebies|privatequarters|opsiexplore|opsiexplorecleanup|opsipreventactionpointoverflow|minigame|awaken|opsiashbeacon|opsidaily|opsishop|opsivoucher|eventshop|opsiabyssal|opsistronghold|opsiobscure|opsiarchive|daily|limitchallenge|hard|opsimonthboss|sos|eventsp|eventa|eventb|eventc|eventd|raiddaily|coalitionsp|wararchives|maritimeescort|islandjuueatery|islandjuucoffee|islandgrill|islandteahouse|islandrestaurant|islandfarm|islandrancher|islandmineforest|islanddailygather|islandmanufacture|islandairdrop|islandbusiness|islanddailyorder|islanddailyinteract|islandpearlsell|islandcargopreparation|event|event2|event3|raid|hospital|hospitalevent|coalition|raidscuttle|main|main2|main3|opsischeduling|opsimeowfficerfarming|gemsfarming|ambush11|opsihazard1leveling|threeoillowcost|operationhandover)$/i

/** 战术学院语法正则捕获组：same(同系加成) -? (red|blue|yellow) -? (T1~T4) */
const TACTICAL_PATTERN = /^(same)?(-)?(red|blue|yellow)?(-)?(t[1-4])?$/i

/** 科研项目正则表达式捕获组：系列 -? 船名 -? 稀有度 类型代码 -? 项目编号/时长 */
const RESEARCH_PATTERN =
  /^(s[1-9])?(-)?(neptune|monarch|ibuki|izumo|roon|saintlouis|seattle|georgia|kitakaze|azuma|friedrich|gascogne|champagne|cheshire|drake|mainz|odin|anchorage|hakuryu|agir|august|marcopolo|plymouth|rupprecht|harbin|chkalov|brest|kearsarge|hindenburg|shimanto|schultz|flandre|napoli|nakhimov|halford|bayard|daisen|goudenleeuw|mecklenburg|dmitri|kansas|vittorio|valparaiso|maximmelmann|duncan|takahashi|orage)?(-)?(dr|pry|pr)?([bcdeghqt])?(-)?(\d{3})?(\d+(?:\.\d+)?)?$/i

/** 委托过滤器正则捕获组：类别 (major|daily|extra|urgent|night) -? 产出 -? 时间 (0:30|4|1.5) */
const COMMISSION_PATTERN =
  /^(major|daily|extra|urgent|night)?(-)?(resource|chip|event|drill|part|cube|oil|book|retrofit|box|gem|ship)?(-)?(\d{1,2}:\d{2}|\d+(?:\.\d+)?)?$/i

/** 商店与海域物资复合正则捕获组：物品大类 -? 属性/颜色/阵营 -? 等级 */
const SHOP_ITEM_PATTERN =
  /^(array|book|box|bulin|cat|chip|coin|cube|drill|food|plate|retrofit|pr|dr|specializedcore|logger|tuning|fragment|equip|gachaticket|meta|skinbox|oil|medal|merit|actionpoint|purplecoins|operationcoins|augment|expbook|oxycola|coolant|ship|geardesignplan|gearpart|developmentmaterial|ordnancetestingreport|metaredbook|crystallizedheatresistantsteel|nanoceramicalloy|neuroplasticprostheticarm|supercavitationgenerator|hiddenzonedatalogger|adventuregalley|albacore|bataan|bearn|bluegill|carabiniere|casablanca|contedicavour|dukeofyork|echo|eldridge|gangut|glorious|grenville|hibiki|hunter|icarus|kawakaze|kinggeorgev|kinu|kuroshio|lagalissonniere|lemalinmuse|letemeraire|littorio|mikuma|minsk|newcastle|oyashio|quincy|ryuujou|sanjuan|sheffieldmuse|trento|u37|vincennes|z24|z26|z28|z36)?(-)?(neptune|monarch|red|blue|yellow|general|gun|torpedo|antiair|plane|wild|random|dd|cl|bb|cv|iris|sardegna|abyssal|archive|obscure|unlock|combat|offence|offense|survival|ironblood|eagle|royal|sakura|enhance|change|core)?(-)?(s[1-5]|t[1-6]|ur|ssr|sr|r|n|\d+)?$/i

/** 语法解析装饰器。分支顺序即匹配优先级，先命中先上色；复合语法（9~12）必须排在通用等级后缀（16）之前，否则 PlateTorpedoT3、SameT4 这类整词会被拆碎。 */
const tokenDecorator = new MatchDecorator({
  regexp: /[>＞﹥›˃ᐳ❯]+|[^\s>＞﹥›˃ᐳ❯]+/g,
  decorate: (add, from, to, match) => {
    const raw = match[0]

    // 1. 优先级连接箭头 (>)
    if (ARROW_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-arrow'}))
      return
    }

    // 2. 策略控制词与特殊徽章
    if (TIER_MARKER_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-tier-marker'}))
      return
    }
    if (RESET_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-reset'}))
      return
    }
    if (SHORTEST_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-shortest'}))
      return
    }
    if (CHEAPEST_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-cheapest'}))
      return
    }
    if (PRESET_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-preset'}))
      return
    }

    // 3. 后宅喂食专属容量 (Dorm Feed Filter)
    if (DORM_FOOD_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-dorm-food'}))
      return
    }

    // 4. 纯时间格式 (如 0:30, 1:45, 5:20)
    if (PURE_TIME_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-time'}))
      return
    }

    // 5. 舰队与战术指令 (Fleet-1~6, CallSubmarine)
    if (FLEET_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-fleet'}))
      return
    }

    // 6. 稀有度指令 (ultra, super_rare, elite, rare, common)
    if (RARITY_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-rarity'}))
      return
    }

    // 7. 关卡代码 (如 A1~D3, SP, EX, 11-4)
    if (STAGE_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-stage'}))
      return
    }

    // 8. 岛屿工人打卡 (WorkerJuu)
    if (WORKER_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-worker'}))
      return
    }

    // 9. 战术学院复合语法 (Tactical: SameT4, RedT3, BlueT2, Same-T1)
    const tac = TACTICAL_PATTERN.exec(raw)
    if (tac && (tac[1] || (tac[3] && tac[5]))) {
      let offset = from
      const segments: {val?: string; cls: string}[] = [
        {val: tac[1], cls: 'cm-filter-tactical-same'},
        {val: tac[2], cls: 'cm-filter-delimiter'},
        {val: tac[3], cls: `cm-filter-tactical-${tac[3]?.toLowerCase()}`},
        {val: tac[4], cls: 'cm-filter-delimiter'},
        {val: tac[5], cls: 'cm-filter-tier'},
      ]
      for (const seg of segments) {
        if (seg.val) {
          const len = seg.val.length
          add(offset, offset + len, Decoration.mark({class: seg.cls}))
          offset += len
        }
      }
      return
    }

    // 10. 科研过滤器复合结构 (Research: S9-DR0.5, S9-E-315, Q0.5, DR2.5, monarch)
    const res = RESEARCH_PATTERN.exec(raw)
    if (res && (res[1] || res[3] || res[5] || res[6])) {
      let offset = from
      const segments: {val?: string; cls: string}[] = [
        {val: res[1], cls: 'cm-filter-series'},
        {val: res[2], cls: 'cm-filter-delimiter'},
        {val: res[3], cls: 'cm-filter-ship'},
        {val: res[4], cls: 'cm-filter-delimiter'},
        {val: res[5], cls: res[5]?.toLowerCase() === 'dr' ? 'cm-filter-dr' : 'cm-filter-pry'},
        {val: res[6], cls: 'cm-filter-genre-code'},
        {val: res[7], cls: 'cm-filter-delimiter'},
        {val: res[8], cls: 'cm-filter-number'},
        {val: res[9], cls: 'cm-filter-time'},
      ]
      for (const seg of segments) {
        if (seg.val) {
          const len = seg.val.length
          add(offset, offset + len, Decoration.mark({class: seg.cls}))
          offset += len
        }
      }
      return
    }

    // 11. 委托过滤器复合模式 (Commission: ExtraCube-0:30, UrgentBox-6, Gem-4, Major)
    const comm = COMMISSION_PATTERN.exec(raw)
    if (comm && (comm[1] || comm[3])) {
      let offset = from
      const segments: {val?: string; cls: string}[] = [
        {val: comm[1], cls: `cm-filter-comm cm-filter-comm-${comm[1]?.toLowerCase()}`},
        {val: comm[2], cls: 'cm-filter-delimiter'},
        {val: comm[3], cls: `cm-filter-genre cm-filter-genre-${comm[3]?.toLowerCase()}`},
        {val: comm[4], cls: 'cm-filter-delimiter'},
        {val: comm[5], cls: 'cm-filter-time'},
      ]
      for (const seg of segments) {
        if (seg.val) {
          const len = seg.val.length
          add(offset, offset + len, Decoration.mark({class: seg.cls}))
          offset += len
        }
      }
      return
    }

    // 12. 商店物资与装备复合模式 (Shop Items: PlateTorpedoT3, BookRedT2, FoodT6, EquipUR)
    const shopItem = SHOP_ITEM_PATTERN.exec(raw)
    if (shopItem && (shopItem[1] || (shopItem[3] && shopItem[5]))) {
      let offset = from
      const segments: {val?: string; cls: string}[] = [
        {val: shopItem[1], cls: 'cm-filter-shop-group'},
        {val: shopItem[2], cls: 'cm-filter-delimiter'},
        {val: shopItem[3], cls: 'cm-filter-shop-sub'},
        {val: shopItem[4], cls: 'cm-filter-delimiter'},
        {val: shopItem[5], cls: 'cm-filter-tier'},
      ]
      for (const seg of segments) {
        if (seg.val) {
          const len = seg.val.length
          add(offset, offset + len, Decoration.mark({class: seg.cls}))
          offset += len
        }
      }
      return
    }

    // 13. 系统调度任务优先级名称 (Yukikaze / OpsiScheduling: Restart, Commission, Research...)
    if (SYSTEM_TASK_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-task'}))
      return
    }

    // 14. 狗粮/常见筛选舰船名 (bogue, ranger, langley...)
    if (FODDER_SHIP_PATTERN.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-ship'}))
      return
    }

    // 15. 纯数字 / 阈值数值 (如 0.5, 4, 30)
    if (/^\d+(?:\.\d+)?$/.test(raw)) {
      add(from, to, Decoration.mark({class: 'cm-filter-number'}))
      return
    }

    // 16. 简单等级后缀 (如 PlateT3 中的 T3)
    const tier = /^(.*)(t[1-6]|s[1-5])$/i.exec(raw)
    if (tier) {
      const prefixLen = tier[1].length
      if (prefixLen > 0) {
        add(from, from + prefixLen, Decoration.mark({class: 'cm-filter-item'}))
      }
      add(from + prefixLen, to, Decoration.mark({class: 'cm-filter-tier'}))
      return
    }

    // 17. 通用项（普通标签、未特殊匹配项）
    add(from, to, Decoration.mark({class: 'cm-filter-item'}))
  },
})

const filterHighlightPlugin = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet
    constructor(view: EditorView) {
      this.decorations = tokenDecorator.createDeco(view)
    }
    update(update: ViewUpdate) {
      this.decorations = tokenDecorator.updateDeco(update, this.decorations)
    }
  },
  {decorations: v => v.decorations}
)

/**
 * Alas 过滤器语法高亮编辑器：CodeMirror 6 文本域，按词法给任务名、舰船、关卡等 token 上色。
 *
 * 提交契约是「失焦即提交」：输入过程不触发 onChange，失焦或卸载时才提交草稿，
 * 避免每个按键都触发外层重渲染；外部 value 变化（重置、切换实例）会整体覆盖编辑内容。
 *
 * @param id 挂到可编辑内容上的 DOM id，invalid 时还用于拼接错误描述的 aria-describedby。
 * @param value 外部受控值，仅在外部变化时同步进编辑器。
 * @param onChange 失焦或卸载时以编辑器当前全文调用。
 * @param label 可编辑内容的 aria-label。
 * @param invalid 校验失败标记，联动 aria-invalid 与错误描述。
 */
export function FilterEditor({
  id,
  value,
  onChange,
  disabled = false,
  label,
  invalid,
}: {
  id: string
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  label: string
  invalid?: boolean
}) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView>(undefined)
  const change = useRef(onChange)
  const initial = useRef(value)
  const latestValue = useRef(value)
  const lastCommitted = useRef(value)
  const editable = useRef(new Compartment())

  // onChange/value 每次渲染都刷新进 ref：输入路径只读 ref，effect 不依赖它们，编辑器实例不会因 props 变化被重建。
  change.current = onChange
  latestValue.current = value

  useEffect(() => {
    const editor = new EditorView({
      parent: host.current!,
      state: EditorState.create({
        doc: initial.current,
        extensions: [
          history(),
          EditorView.lineWrapping,
          filterHighlightPlugin,
          keymap.of([...defaultKeymap, ...historyKeymap]),
          editable.current.of([]),
          EditorView.contentAttributes.of({
            id,
            'aria-label': label,
            'aria-multiline': 'true',
            role: 'textbox',
          }),
          EditorView.updateListener.of(update => {
            if (update.docChanged) {
              latestValue.current = update.state.doc.toString()
            }
          }),
          EditorView.domEventHandlers({
            blur: (_event, v) => {
              const current = v.state.doc.toString()
              if (current !== lastCommitted.current) {
                lastCommitted.current = current
                change.current(current)
              }
              return false
            },
          }),
        ],
      }),
    })
    view.current = editor

    return () => {
      // 卸载时如果有未提交的草稿，触发一次提交
      if (latestValue.current !== lastCommitted.current) {
        lastCommitted.current = latestValue.current
        change.current(latestValue.current)
      }
      editor.destroy()
      view.current = undefined
    }
  }, [id, label])

  // 外部配置更新时同步至编辑器（如重置或切换实例）
  useEffect(() => {
    const editor = view.current
    if (editor && editor.state.doc.toString() !== value) {
      lastCommitted.current = value
      latestValue.current = value
      editor.dispatch({
        changes: {from: 0, to: editor.state.doc.length, insert: value},
        annotations: externalChange.of(true),
      })
    }
  }, [value])

  // 只读与校验状态经 Compartment 热重配置，不必销毁重建整个编辑器。
  useEffect(() => {
    view.current?.dispatch({
      effects: editable.current.reconfigure([
        EditorState.readOnly.of(disabled),
        EditorView.editable.of(!disabled),
        EditorView.contentAttributes.of({
          'aria-disabled': String(disabled),
          'aria-invalid': String(!!invalid),
          ...(invalid ? {'aria-describedby': `${id}-status`} : {}),
        }),
      ]),
    })
  }, [disabled, invalid, id])

  return (
    <div
      aria-invalid={invalid || undefined}
      className={`filter-editor ${disabled ? 'is-disabled' : ''}`}
      ref={host}
    />
  )
}

# styles/ —— 样式分层结构说明

本目录采用「混合分层」三层约定：**L1 全局设计层（契约，禁改）+ L2 全局共享词汇域层（本目录下按域命名的 CSS，经保序 `@import` 聚合加载）+ L3 组件/页面 colocated CSS（白名单搬迁）**。
重构纪律：渲染结果零视觉变化；既有 className 100% 稳定；主题变量契约不破坏。改动前请读完本文。

## 加载链（勿重排）

- 入口唯一：`src/main.tsx:14-16` 依次引入 `legacy.css` → `minimal.css` → `shadcn.css`。
- `legacy.css` 与 `components.css` 现为**纯 `@import` 聚合器**：Vite/postcss 按声明顺序内联展开，`@import` 的书写顺序即级联顺序，每条规则的相对位置不变。重排 import 顺序 = 重排级联，**禁止**。
- `components.css` 聚合 B1 拆出的 22 个域文件；`legacy.css` 先聚合共享层（tokens/layout/components/insights/setup/legacy-palette/theme-material/theme-primitives/topbar/forms/legacy-fonts/motion），再聚合 B2 拆出的 10 个经典主题域文件。
- lazy chunk 的 colocated CSS 追加在入口束之后加载（不插队）；这正是 L3 搬迁只允许 lazy chunk 组件的原因。
- 测试锚点：`src/app/themeContract.test.ts:27` 断言 `legacy.css` 文本包含 `theme-material.css`——聚合器里这行 `@import` 必须保留。

## L1 全局设计层（契约，禁改）

这些文件承载主题系统的变量契约与运行时依赖，**CSS 变量名与语义不得改动**，文件不得拆分搬迁：

| 文件 | 契约内容 | 证据 |
| --- | --- | --- |
| `tokens.css` | `:root` 首帧兜底值（`--bg`/`--surface`/`--text`/`--muted`/`--border`/`--accent`/`--radius`/`--sidebar*`/`--viewport-height`/`--syntax-*`/`--ui-scale` 等，15-30 行）；全局 reset；`prefers-reduced-motion` 总开关（61 行，`motion.css` 头注声明依赖它关闭全部动画） | 19-20 行注释要求兜底值与 legacy 浅色取值一致，改值会首帧闪白 |
| `legacy-palette.css` | 基础色板（无前缀）+ `--theme-<region>-<prop>` 八区八键契约（REGIONS×REGION_PROPS=64 键，被 `src/app/themeContract.test.ts:35-36` 钉死）+ colorSlots 登记键 | 1-3 行注释：「颜色槽位的契约名与 app/colorPalette.ts 的 colorSlots 一一对应，改名会破坏调色板」（`colorPalette.ts:33-91` 只接受登记 token） |
| `theme-material.css` | 材质轴（glass/plain）：plain 压平 + 全树 `backdrop-filter` 熄灭 | 28-32 行 `!important`，去掉即玻璃漏光；`e2e/production-style.spec.ts:34` 以 `toHaveCSS('backdrop-filter', …)` 锁定计算值 |
| `theme-primitives.css` | 消费层；含 instance-tabs 几何派生 | 192-194 行注释明言标签栏「结构、几何与交互在这里定义，各主题只改皮相」，必须整体保留同文件（195-212 行派生变量） |
| `minimal.css`、`shadcn.css` | shadcn/ui 接入层的 `--sc-*` 语义色（shadcn.css `@theme inline` 内 61 处映射） | shadcn.css 5-6 行注释：应用侧已有 `--accent`/`--border`/`--muted`/`--radius` 同名变量，`--sc-` 前缀防撞名 |
| 经典主题 rail-panel 变量段 | `--rail-panel-*`（`rail-panel.css`，原 legacy.css 1042-1047 整段保留）与玻璃段 `--rail-*`（`rail-panel-glass.css:23-39`） | rail-panel.css:17：「底色/描边/投影/滤镜都走 `--rail-panel-*` 变量」——调度器面板统一走变量而非高特异度选择器；rail-panel-glass.css 计算值被 e2e 锁定 |

主题切换运行时链 `applyCustomLayer`（`src/app/theme.ts:59`，docstring 明言「调色板永远最后写」：内联样式注入永远压过一切样式表）不属于 CSS 侧，任何样式改动都不得试图在 CSS 里与之竞争。

## L2 全局共享词汇域层（本目录域文件）

判定标准：类被 **≥2 个组件消费**，或被**任一主题/皮肤文件覆盖**（如 `.button` 被 9 个 CSS 文件覆盖、`.panel` 被 6 个、`.field-row`/`.toggle` 被 5 个），或四查判据有任一不过——都留在 L2。域文件头部注明原始行区间，规则文本逐字未改。

### B1 拆分（原 components.css 1300 行 → 22 个域文件，聚合于 components.css）

| 域文件 | 原 components.css 行区间 | 备注 |
| --- | --- | --- |
| `wallpaper.css` | 1-8 | |
| `buttons.css` | 9-26 | 含 tab-delete-confirm 抖动与 `@keyframes`（keyframes 随块搬迁、名字不变） |
| `panels.css` | 27-37 | |
| `resource-card.css` | 38-66 | `--resource-card-inset` 体系 |
| `log.css` | 67-117 | 日志面板 + LogCardView 卡片日志；`hl-*`/`log-ts` 留守，见「不搬清单」 |
| `map-grid.css` | 118-167 | 25 色单元格 |
| `error-card.css` | 168-257 | `.llm-markdown-view` 随本域留守 |
| `map-cost.css` | 258-275 | |
| `feedback.css` | 276-311 | 横幅/toast/modal/form-stack/toggle |
| `config.css` | 312-402 | |
| `config-manager.css` | 403-424 | |
| `config-fields.css` | 425-458 | |
| `config-list.css` | 459-470 | |
| `meow-report.css` | 已搬空 | 占位指针：meow 域整体 colocate 至 `../components/MeowfficerScorePanel.css`；聚合器 `@import` 勿删 |
| `announcement.css` | 548-673 | 跨段并入原 976-986 行 `.announcement-footer`/`.announcement-external-btn`（四查复核：与 markdown 段类名零交集、无同特异度属性竞争） |
| `markdown.css` | 已搬空 | 占位指针：Markdown 域整体 colocate 至 `../components/MarkdownView.css`；聚合器 `@import` 勿删 |
| `tiny-dot.css` | 988-993 | |
| `palette-picker.css` | 994-1056 | 孤儿待确认，见「死样式清单」 |
| `nav-collapse.css` | 1057-1091 | `@property --sidebar-width-preview` 随块保留全局作用 |
| `mock-preview.css` | 1092-1253 | 模拟预览/材质检视器 |
| `nav-search.css` | 1254-1265 | 留守，见「不搬清单」 |
| `context-menu.css` | 1266-1301 | 留守，见「不搬清单」 |

### B2 拆分（原 legacy.css 15-1754 → 10 个域文件，聚合于 legacy.css 16-25 行）

| 域文件 | 原 legacy.css 行区间 | 备注 |
| --- | --- | --- |
| `theme-legacy.css` | 15-325 | 静态覆写 + 紧凑开关 + skip-link + 侧栏/导航皮相 + 圆角 + MD3 按钮 |
| `rail-panel-early.css` | 326-416 | 初版皮相大半已被 1035+ 改版覆盖，属影子样式待确认 |
| `layout-legacy.css` | 417-552 | 外壳网格/按压反馈/页面入场/旧顶栏 |
| `nav-legacy.css` | 553-576 | 侧栏子菜单展开 + task-picker 下拉 |
| `layout-legacy-desktop.css` | 577-790 | ≥951px 桌面网格/拖拽把手/统计带/任务设置双列 |
| `skin-legacy.css` | 791-1010 | stat-card/monitor-tabs/modal/toast 皮相 + ≤950px 降级 + forced-colors 覆写 |
| `a11y-legacy.css` | 1011-1034 | 滚动条隐藏 + period-controls 隐藏 + 高对比覆写；含 dev-* 孤儿注释，见「死样式清单」 |
| `rail-panel.css` | 1035-1413 | 调度器面板改版；`--rail-panel-*` 变量段整体保留 |
| `rail-panel-glass.css` | 1414-1650 | 玻璃材质整段 `--rail-*`；计算值被 e2e 锁定 |
| `settings-legacy.css` | 1651-1754 | 任务设置三列网格 + 全局设置页 |

### B4 随迁说明（forms.css / topbar.css）

`forms.css`、`topbar.css` 主体留守 L2，仅按白名单把三个组件的规则搬到 L3。`@media`/`@supports` 覆写**按规则级摘出随迁**（不是整块搬）：`BackgroundPreferences.css:50,54` 重建窄屏与 forced-colors 块、`Updater.css:88` 重建 `@media (max-width: 950px)` 块，均位于对应基规则之后——否则 lazy 基规则反压入口层覆写，造成窄屏/强制色回归。

## L3 组件/页面 colocated CSS（白名单）

与组件同目录同名，tsx 顶部 `import './X.css'`。当前白名单成员（共 5 个，均 lazy chunk）：

| colocated CSS | 消费方（import 行） | 来源 |
| --- | --- | --- |
| `components/MeowfficerScorePanel.css` | `MeowfficerScorePanel.tsx:11` | 原 components.css meow 域（`.task-config-legacy .meow-panel` (0,2,0) 靠特异性压 lazy 层） |
| `components/MarkdownView.css` | `MarkdownView.tsx:12` | 原 components.css markdown 域（`.llm-markdown-view` 与 `.markdown-view` 平局随迁，胜负不变） |
| `components/FilterEditor.css` | `FilterEditor.tsx:25` | 原 forms.css cm-filter 域（e2e/mock.spec.ts:1936-1937 锁定计算值） |
| `components/BackgroundPreferences.css` | `BackgroundPreferences.tsx:12` | 原 forms.css（`.background-gallery-head .button` (0,2,0) 靠特异性） |
| `pages/Updater.css` | `Updater.tsx:14` | 原 forms.css（`.updater-head .button.secondary` (0,3,0) 靠特异性） |

entry 静态树组件（App/MaterialInspector 等）一律留 L2，不做 colocated。

### 四查判据（全绿才允许搬入 L3）

对每一个候选类/域：

1. **单文件定义**：grep 全 `styles/*.css`——该类名只在一个文件定义（排除同名选择器竞争）。
2. **单一消费者**：grep 全 `src/`——只被一个 tsx 消费。
3. **lazy chunk**：目标组件在 lazy chunk（colocated CSS 追加在入口束之后，不插队）；entry 静态树不搬。
4. **同特异度跨选择器竞争穷举**：对被搬选择器可能命中的每个元素状态（基态/伪类/禁用/hover），穷举后于源文件加载的全部样式表中的同特异度竞争属性。注意：第 1 查只排除【同名选择器】竞争，排除不了 `button:disabled` 这类元素+伪类组合的平局（如 `legacy.css` 原 321 行 `button:disabled` (0,1,1)）。

任何一查不过 → 留 L2 并标注竞争证据。

## 明确不搬清单（竞争证据待四查全绿再评估）

| 域 | 现状 | 竞争证据 |
| --- | --- | --- |
| `nav-search` | 留 L2（`nav-search.css`） | `.nav-search-hits` 同选择器双定义：`nav-search.css:3`（原 components.css:1254-1265）与 `theme-legacy.css:141`（原 legacy.css:154）`.nav-search-hits {margin-bottom: 12px}`——colocated 后加载顺序变化会翻转这条同选择器平局 |
| `hl-*` / `log-ts` | 留 L2（`log.css`） | 双定义：`log.css` 9 处（原 components.css:67-117）vs `theme-primitives.css:138-144` 6 处（`.log-ts, .hl-time, … {color: var(--theme-log-time)}` 等）——主题文件靠顺序覆盖日志域取色，搬迁即翻车 |
| `context-menu` | 留 L2（`context-menu.css`） | `.context-menu-item:disabled`（context-menu.css:35，(0,2,0)）与 `button:disabled`/`.button:disabled` 存在跨选择器竞争面：`theme-legacy.css:308-309`、`forms.css:75`、`skin-legacy.css:220`（forced-colors）——第 4 查的元素+伪类组合平局无法排除，B3 仲裁存疑不搬（记录在 context-menu.css:1 头注） |

## 死样式清单（孤儿待确认——只标注，未删除）

1. **`palette-picker.css` 调色板域**（原 components.css:994-1056）：`.palette-option`/`.palette-options` 等全 `src/` 无 tsx 消费者（grep `palette-option` 于 `*.tsx` 0 命中），仅 `e2e/themes.spec.ts:27,57` 引用；`settings-legacy.css:47-48` 另有 `.settings-page .palette-options`/`.custom-palette-actions` 引用。孤儿状态标注在 palette-picker.css:1 头注。
2. **`a11y-legacy.css:4-5` 的 dev-* 系**（原 legacy.css:1012-1013）：`.dev-state-box`/`.dev-shadow-grid`/`.dev-nav-preview` 全库无消费方（开发期残留）；「其后 `.field-control > .field-actions` 规则为活规则，勿一并标注」的警示在 a11y-legacy.css:3。
3. **四个无定义 token 类**：`text-warning`/`text-danger`/`text-success`/`text-mono`——`LogCardView.tsx:1079,1417,1564,1587` 等 tsx 消费，但全 styles/ 与 colocated CSS 均无 `.text-warning` 等规则定义，shadcn `@theme` 亦无 `--color-warning/--color-danger/--color-success`（grep 0 命中），当前渲染无效果。待确认是补定义还是清理类名，未动。

## 令牌三层命名规律（新令牌照此取名）

| 前缀 | 层 | 例子 | 定义处 |
| --- | --- | --- | --- |
| （无前缀） | 基础语义变量，全站共用 | `--bg` `--surface` `--text` `--accent` `--radius` | `tokens.css` 首帧兜底 + `legacy-palette.css` 契约色板 |
| `--theme-` | 主题契约键（八区八键 `--theme-<region>-<prop>` + 部件级键） | `--theme-surface-alpha` `--theme-radius-control` `--theme-tab-current-bg` | `legacy-palette.css` / 各主题文件覆盖取值 |
| `--sc-` | shadcn/ui 接入层专用 | `--sc-background` `--sc-primary` | `shadcn.css`（防与无前缀应用变量撞名） |

另有组件体系私有前缀（不进契约、但改名前先查 e2e）：`--rail-panel-*`/`--rail-*`（调度器面板）、`--resource-card-inset`（资源卡）、`--instance-tab-*`（标签栏几何，定义于 theme-primitives.css:195-212，全主题共用）。

## 新代码规范

- **新组件私有样式一律 colocated**：`Component.tsx` 与 `Component.css` 同目录同名，tsx 顶部 `import './Component.css'`；要求满足四查且组件在 lazy chunk。
- **共享词汇进对应域文件**：被 ≥2 个组件消费或被主题/皮肤覆盖的类，写进 L2 域文件（文件名即域），并在 tsx 头部加样式索引注释指向。
- **不动 `package.json` / `vite.config.ts`**；`src/components/ui/`（shadcn 风格）继续用 Tailwind 4 工具类自包含，零迁移。
- 改动任何样式后跑门禁：`npm run typecheck` → `npm run build` → `npm test`（基线 485 过/1 既有失败 `FleetTraining.test.ts`），并用 `npx vite build` 的 `dist/assets/*.css` 对比重构前快照（选择器集合、`@keyframes`/`@property` 名集合、规则相对顺序三者必须逐字一致，允许差异仅文件边界注释）。快照 diff 抓不到跨选择器同特异度平局翻转——该风险靠四查清单前置拦截。

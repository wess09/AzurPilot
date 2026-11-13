# AzurPilot 插件包（APU API 1）

在 WebUI 的「插件」页导入 `.apu`，再启用。已安装的包、启用状态与插件数据保存在 AzurPilot 服务的 `config/plugins/plugins.db`。其他设备打开同一个服务时也能使用已启用的插件。主题布局选择保存在当前浏览器，可以在插件页切回默认布局。卸载会删除该插件的数据，停用时会保留数据。

## 打包

在仓库根目录运行：

```powershell
uv run python -m dev_tools.pack_apu frontend/plugin-sdk/examples/workbench dist/workbench.apu
uv run python -m dev_tools.pack_apu frontend/plugin-sdk/examples/task-favorites dist/task-favorites.apu
uv run python -m dev_tools.pack_apu frontend/plugin-sdk/examples/compact-scheduler dist/compact-scheduler.apu
```

`.apu` 是 ZIP，根目录须有 `manifest.json`。可以用任意构建工具开发插件，导入的是可直接运行的 HTML、JS、CSS、图片和字体。使用 Vite 时设 `base: './'`，将 npm 依赖打入插件自己的构建产物，再把清单放进构建输出目录。包内路径使用英文字母、数字、点、下划线、连字符和斜杠。清单声明的入口和资源必须存在，导入失败会保留已安装版本。

## 清单

`id`、`name`、`version` 和 `apiVersion: 1` 必填。`theme`、`permissions`、`pages` 和 `panels` 可省略。相同 ID 重新导入会更新原插件，保留启用状态与数据。

| 字段 | 用途 |
| --- | --- |
| `theme.navigation` | `top`、`left`、`right` 或 `bottom`，选择工作台外壳的导航位置 |
| `theme.navigationView` | 用包内 HTML 替换主导航，通过 `navigation.items` 和 `navigation.open` 接入宿主路由 |
| `theme.overview` | 按顺序排列 `resources`、`scheduler`、`queue`、`logs`、`panels`，可省略个别内置块 |
| `theme.overviewView` | 用包内 HTML 替换总览主视图 |
| `theme.scheduler` | 用包内 HTML 完整替换调度器界面 |
| `theme.styles` | 为 `shell`、`navigation`、`overview`、`scheduler` 指定各自的 CSS |
| `theme.replaceSchedulerStyles` | 设为 `true` 后由插件 CSS 负责现代调度器的外观，保留原控件、状态和操作 |
| `theme.icons` | 将 `scheduler.title`、`scheduler.start`、`scheduler.stop` 指向包内图标 |
| `pages` | 每项有 `id`、`title`、`entry` 和可选 `scope`，`scope` 为 `global` 或默认的 `instance` |
| `panels` | 每项有 `id`、`title` 和 `entry`，在实例总览中出现 |
| `permissions` | 按需声明 `instance.read`、`storage` 和 `scheduler.control` |

现代调度器的公开样式部位是 `header`、`counts`、`running`、`pending`、`waiting` 和 `toggle`。用 `[data-apu-part="toggle"]` 之类的选择器定位部位。用 `:scope` 选择组件根节点，根节点的 `data-state` 为 `running` 或 `stopped`。CSS 由宿主限定在对应组件内，`url()` 按样式表位置解析包内图片或字体。支持 `@media`、`@supports`、`@font-face` 和 `@keyframes`。字体与动画名称以 `apu-<插件 id>-` 开头。

## 自定义页面、面板和调度器

`pack_apu` 会在包根目录加入 `apu.js`。从插件 HTML 中按相对路径导入：

```js
import { request, subscribe } from '../apu.js'

const instance = await request('instance.current')
const favorites = await request('storage.get', {key: 'favorites'})
subscribe('appearance', ({mode}) => { document.documentElement.style.colorScheme = mode })
```

| API | 权限和行为 |
| --- | --- |
| `instance.current`、`instance.overview` | `instance.read`，读取当前实例、资源和任务摘要 |
| `storage.get`、`storage.set`、`storage.delete` | `storage`，按插件和当前实例隔离；写入使用 `{key, value}` |
| `scheduler.toggle` | `scheduler.control`，只在调度器替换视图中可用；宿主负责保存配置后启动 |
| `subscribe('scheduler.state', fn)` | 调度器替换视图的状态和计数 |
| `subscribe('appearance', fn)` | 当前语言和明暗 |
| `subscribe('navigation.items', fn)`、`navigation.open` | 导航替换视图可用，订阅宿主提供的 `{title, to}[]` 并使用 `{to}` 打开其中一项 |

插件视图在沙箱 iframe 中运行。静态资源从同一插件版本加载，业务调用经宿主消息通道。把所需依赖与资源随包发布。调度器替换视图初始化失败时会回退到现代调度器。

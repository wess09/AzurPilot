# 终端界面（gui.py --tui）

> 基于 Textual 的全功能终端控制台：复用 WebUI 的配置与运行时服务，在同一终端内完成实例切换、调度启停、单任务执行、任务计划开关、参数编辑与实时日志查看。

## 1. 模块概述

TUI 是 WebUI 之外的第二套本地入口。它不重复实现业务逻辑：配置读写走 `module/api/config_service.py`，实例状态、日志与进程控制走 `module/api/runtime_service.py`，界面层只负责渲染与交互。适合无浏览器、SSH 或低资源环境使用。

## 2. 模块职责

### 负责

- 实例列表与运行状态展示、1-9 数字键快速切换。
- 启动/停止当前实例调度器、单独执行一次功能任务。
- 任务计划表：展示已启用与已禁用任务，回车切换启用状态。
- 任务参数编辑：按 `args.json` 元数据生成开关、下拉、文本、多行文本与多选控件。
- 实时日志增量拉取、清屏与自动滚屏开关。
- 资源看板汇总（Dashboard 数值 + 大世界月度统计）。

### 不负责

- 配置校验与落盘事务：`ConfigService.patch`。
- 进程生命周期与日志缓存：`ProcessManager` / `RuntimeService.logs`。
- 任务调度顺序与游戏内逻辑：`alas.py` 与 `module/` 各功能模块。

## 3. 模块位置

```text
gui.py                         统一入口：默认启动 WebUI，--tui 分支启动终端界面
module/tui/app.py              应用：布局、定时器、快捷键与后台任务编排
module/tui/backend.py          桥接后端：状态/总览/日志/启停/配置
module/tui/theme.tcss          深色主题与控件样式
module/tui/widgets/            Sidebar/TaskTable/LogView/HeaderBar/ResourceBar
                               ConfigModal/TaskModal/HelpScreen
```

## 4. 核心入口

| 入口 | 用途 |
| --- | --- |
| `uv run python gui.py --tui` | 自动选中排序后的第一个实例 |
| `uv run python gui.py --tui alas` | 指定启动实例；不存在时回退并在界面提示 |
| `F1` / `?` | 界面内帮助弹层 |
| `Q` | 退出 TUI（已在运行的实例进程继续运行） |

旧的独立入口 `tui.py` 与 `alas.py --tui` 已废弃：前者已合并进 `gui.py --tui`，后者会提示改用新命令并以退出码 2 结束。

## 5. 核心组件

| 区域 | 组件 | 说明 |
| --- | --- | --- |
| 顶部 | `HeaderBar` | 实例名、运行状态、当前任务、模拟器与服务器、时钟；数据异常时显示红色告警 |
| 左侧 | `Sidebar` | 实例列表（状态色点 + 当前任务）与启动/停止/配置/单任务/刷新按钮 |
| 中部 | `TaskTable` | 任务计划：运行中 / 待执行 / 等待中 / 已禁用；回车启闭，`E` 编辑 |
| 中部 | `ResourceBar` | 资源看板，数值带千分位，缺失值自动跳过 |
| 底部 | `LogView` | 级别着色日志、游标、自动滚屏、清屏；内存上限 2000 行 |
| 弹层 | `ConfigModal` | 任务选择 + 分组表单；`Ctrl+S` 保存、`Ctrl+R` 重载、`Esc` 取消 |
| 弹层 | `TaskModal` | 关键词过滤 + 列表选择单任务 |
| 弹层 | `HelpScreen` | 快捷键与使用说明 |

终端尺寸建议 100×30 以上以获得完整布局；80×24 仍可用，任务表会隐藏「下次执行」列，侧边栏与各弹层改为可滚动。

## 6. 工作流程

刷新分三档进行，避免每秒读取配置和统计库：

| 定时器 | 周期 | 数据来源 | 更新内容 |
| --- | --- | --- | --- |
| `tick_status` | 1s | `ProcessManager` 内存状态 | 实例状态、按钮可用性、顶栏 |
| `tick_overview` | 5s | `RuntimeService.overview` + 配置补全 | 任务计划表、资源看板、模拟器信息 |
| `tick_logs` | 0.35s | `RuntimeService.logs(after)` | 增量日志与序列号 |

启停、单任务、任务开关在 `asyncio.to_thread` 中执行，完成后回到主线程刷新；执行期间按钮禁用并拒绝重复触发。

## 7. 调用关系

```text
AzurPilotTUI
  ├─ TUIBackend ── ConfigService（读配置 / patch 保存）
  │             └─ RuntimeService（instances / overview / logs / start / stop）
  └─ widgets ── 通过 Textual Message 向上派发（InstanceSelected / ActionTriggered /
                TaskToggleRequested / TaskEditRequested）
```

## 8. 数据流

```text
任务表/侧边栏交互 ──> App._run_control ──> 线程池 ──> RuntimeService
                                              └──> notify + refresh_all_data

配置弹窗打开 ──> backend.get_task_config_schema（读 args + 当前配置）
保存 ──> ConfigService.patch(路径, 值) ──> 重新读取总览
```

## 9. 状态模型

| 界面状态 | 来源 | 表现 |
| --- | --- | --- |
| `running` | `ProcessManager.state == 1` | 绿色 ●，停止按钮可用 |
| `updating` | `state == 4` | 黄色 ◐ |
| `error` | `state == 3` | 红色 ● |
| `stopped` | 其余 | 灰色 ○ |
| 任务 `disabled` | `Scheduler.Enable == false` | 暗色 ⏸，回车可重新启用 |

## 10. 快捷键

| 键 | 功能 |
| --- | --- |
| `Space` | 启动 / 停止当前实例调度器 |
| `1` - `9` | 切换实例 |
| `Enter` | 任务表：启闭选中任务 |
| `E` / `C` | 编辑选中任务 / 打开配置中心 |
| `T` / `R` | 单任务执行 / 立即刷新 |
| `L` / `P` | 清屏 / 自动滚屏开关 |
| `?` / `F1` | 帮助 |
| `Q` | 退出 |

模态窗口打开或焦点位于输入框时，应用级快捷键自动屏蔽，避免输入空格误启停。

## 11. 异常与错误处理

- 后端返回 `ApiError.message` 时直接展示中文原因；未知异常显示 `操作异常: ...`。
- 数据刷新失败时顶部栏显示红色告警，同一错误只提示一次，恢复后自动清除。
- 日志缓存被裁剪（`reset=True`）时先清屏再重放，不产生重复行或断档。
- 配置保存前在本地做类型转换，非法整数/数字、无效多选值直接提示，不会提交半成品。
- 有未保存修改时按 `Esc` 需要二次确认，防止误丢改动。

## 12. 并发与线程模型

- Textual 主线程只做渲染与事件处理。
- 数据加载使用 `@work(exclusive=True, group="data")`，同一时刻只有一个读取任务；切换实例后旧任务结果按实例名丢弃。
- 控制操作使用 `@work(exclusive=True, group="control")`，`is_busy` 拒绝重入。
- 日志轮询保持同步，但只处理增量，单次渲染量受 `MAX_LINE_LENGTH` 与 `max_lines` 约束。

## 13. 缓存与持久化

TUI 自身不写任何文件；配置修改经 `ConfigService.patch` 原子写回实例 JSON，统计类数据由运行时服务读取普通总库。

## 14. 生命周期

`gui.py --tui` → `main()` 初始化存储（保留控制台日志以便观察迁移进度）→ `run_tui()` 设置 UTF-8/ANSI 与 `AZURPILOT_TUI` → 移除全局控制台日志 handler → 构造 `AzurPilotTUI` → `run()`。退出时只关闭界面，不停止已在运行的实例 worker。

## 15. 扩展方式

- **新增面板**：在 `module/tui/widgets/` 实现组件，于 `app.compose` 挂载，并在 `_apply_dashboard` 中分发数据。
- **新增后台能力**：在 `TUIBackend` 增加方法，避免在 widget 内直接访问服务层。
- **新增快捷键**：加入 `BINDINGS` 与 `APP_ACTIONS`，并在 `HelpScreen` 的说明中同步。

## 16. 修改注意事项

- `space` / `q` 是 `priority=True` 绑定，必须保留 `check_action` 的拦截，否则会在输入框里触发。
- 不要在每个 tick 里重建 `DataTable` / `OptionList`；组件内部已有签名比对，绕过会造成光标跳动。
- `get_overview` 会补全未启用任务，前端与测试都依赖 `enabled` 字段。
- 新增 `type` 时同步更新 `config_modal._build_field` 与 `_parse_value`，否则会退化成纯文本控件。

## 17. 已知限制

- 仅展示与编辑任务参数，不提供实例创建、删除与导入导出。
- 多行参数用 `TextArea` 编辑，超长 YAML 在窄终端中需要纵向滚动。
- 日志仅保留运行时服务缓存（约 400 条）与界面 2000 行，历史日志请查看 `log/` 文件。

## 18. 示例

```bash
uv run python gui.py --tui
uv run python gui.py --tui alas
```

## 19. 调试方法

- 界面无反应时先确认焦点：`Tab` 在实例列表、任务表与按钮之间循环。
- 启停失败会以通知显示 `ApiError` 原因；同步查看 WebUI 或 `log/` 中该实例的日志。
- 无头验证：`tests/test_tui_backend.py` 覆盖后端契约、配置弹窗挂载与帮助弹层。

## 20. 相关模块

- [运行时服务](../webui/runtime.md)：实例状态、日志缓存与进程控制。
- [API 服务](../webui/api.md)：TUI 复用的配置与运行时接口。
- [配置系统](../config.md)：`args.json` 元数据与保存事务。
- [WebUI 启动器](gui.md)：另一套本地入口。

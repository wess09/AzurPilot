# AGENTS.md

游戏识别基于 **1280×720** 截图。

- 本项目使用 uv 管理依赖
- 本项目使用 npm 管理 node.js 依赖
- 项目文档 https://doc.azurpilot.com/llms.txt

## 常用命令
| 用途 | 命令 |
| --- | --- |
| 启动 | `uv run python gui.py` |
| 启动终端界面 | `uv run python gui.py --tui` |
| 生成配置和前端选项 | `uv run -m module.config.config_updater` |

## 配置与生成文件

本项目的 json 配置文件由生成器生成非手动维护
`args.json`、`menu.json`、`module/config/config_generated.py` 与 `config/template.json` 由生成器维护

 `module/config/argument/` 

| 源文件 | 职责 |
| --- | --- |
| `task.yaml` | 任务、选项组映射与菜单 |
| `argument.yaml` | 参数类型、选项、默认值与校验 |
| `default.yaml` | 用户可修改的任务特定默认值 |
| `override.yaml` | 强制覆盖及隐藏等属性；与可修改默认值区分 |
| `gui.yaml` | GUI 翻译键 |
| `dashboard.yaml` | 仪表盘资源定义 |

添加 i18n 翻译时请先运行命令生成 json 再替换生成器生成的临时键值
示例：Campaign.Event.name
配置路径为 `<Task>.<Group>.<Argument>`，绑定任务后通过 `self.config.Group_Argument` 访问。涉及加载或迁移时注意 `AzurLaneConfig` 初始化可能保存配置，测试使用临时配置目录。

## 游戏交互

游戏流程采用持续的「截图 → 识别 → 操作」状态循环。用当前画面的正向状态确认退出，点击后继续循环获取新截图；不要用固定休眠猜测界面已就绪。

```python
def some_function(self, skip_first_screenshot=True):
    while True:
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            self.device.screenshot()

        if self.appear(END_CONDITION):
            break
        if self.appear_then_click(BUTTON_A, interval=2):
            continue
        if self.handle_popup():
            continue
```

- 退出检测用 `appear()`，不设 `interval`；`appear_then_click()` 用于操作，通常以 2–5 秒 `interval` 防止连击。
- 不在状态循环内调用 `sleep()`，不以负面识别条件控制循环，不嵌套状态循环；将状态分支合并到父循环。
- 游戏交互的 `handle_*()` 返回 `bool`：`True` 表示已操作、需要新截图，`False` 表示未操作。只有已有可用截图时才跳过首次截图。
- 复用 `GameStuckError`、`GameTooManyClickError` 等检测与上层恢复机制；不要用吞异常或无限重试绕过它们。异常语义见 `module/exception.py`。
- 页面跳转复用 `UI` / `Page` 导航。涉及界面前后置条件时，在 Google 风格 docstring 中用 `Pages:` 标注；注释解释状态和原因，不规定注释比例或为凑行数拆文件。
- 使用现有 `logger.hr()`、`logger.attr()` 记录阶段和状态。截图、日志、测试夹具中避免引入账号信息和密钥。

## 资源与接口生成

- 游戏图像资源位于 `assets/{cn,en,jp,tw}/`；按 1280×720 游戏画面的坐标约定提取，模板是局部裁剪。模板对象名称使用 `TEMPLATE_` 前缀。
- 修改完资源后运行 `uv run -m dev_tools.button_extract`，不要检查 `assets.py`。切换服务器进行离线识别时，在导入游戏模块前设置 `module.config.server.server`，避免资源已按其他服务器加载。

- `campaign/` 下关卡是 Python 地图定义与战斗逻辑；活动适配参考相近活动及 [campaign/Readme.md](campaign/Readme.md)。
- WebUI 业务通信使用 `/api/v1/ws`；前端位于 `frontend/`，后端接口与运行服务分别位于 `module/api/`、`module/runtime/`。
- 修改后端 API 参数模型或方法注册后，运行 `uv run python -m dev_tools.export_api_schema`，同步 `frontend/src/api/generated.ts` 与 `frontend/src/api/contract.json`

AI 自行创建 PR 或执行任何涉及提 PR 的操作时，必须按 [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) 模板填写：如实勾选变更类型与代码质量确认项（未执行的检查不勾选），并在描述中说明变更原因、验证结果与相关 Issue。
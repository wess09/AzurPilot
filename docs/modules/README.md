# 模块文档索引

> AzurPilot 模块文档体系入口。每篇文档对应一个独立职责，按三级标准撰写（S 250–500 行 / A 120–250 行 / B 40–100 行），统一 20 节结构（省略时保留编号）。

## 按主题检索

### 入口与全局

| 文档 | 主题 |
| --- | --- |
| [overview/directory-map.md](overview/directory-map.md) | 目录速查表与「任务方法 → 模块」映射规则 |
| [overview/conventions.md](overview/conventions.md) | 编码规范与横切设计模式 |
| [entry/alas.md](entry/alas.md) | 调度器：任务循环、错误恢复、任务派发 |
| [entry/gui.md](entry/gui.md) | WebUI 启动器 |
| [entry/mcp-server.md](entry/mcp-server.md) | 独立 MCP SSE 服务器 |
| [config.md](config.md) | 配置系统：定义、生成、事务与热重载 |

### 基础设施

| 文档 | 主题 |
| --- | --- |
| [base/index.md](base/index.md) | ModuleBase、Button/Template、Timer/Filter |
| [base/decorator-utils.md](base/decorator-utils.md) | 装饰器与工具函数 |
| [device.md](device.md) | 设备层：模拟器连接、截图与控制方法 |
| [ocr.md](ocr.md) | OCR 系统：模型、封装与基准 |
| [ui.md](ui.md) | UI 导航：页面图、控件库、未知页面恢复 |
| [handler.md](handler.md) | 处理器层：弹窗、登录、通用游戏处理 |
| [infra/daemon.md](infra/daemon.md) | 守护模式：画面守护、大世界守护、基准测试 |
| [infra/statistics.md](infra/statistics.md) | 统计与数据提交（drop 记录、azurstat） |
| [infra/persistence.md](infra/persistence.md) | 普通总库：SQLite v1 表结构、类型化兼容值、迁移与恢复 |
| [infra/notify-llm-logger.md](infra/notify-llm-logger.md) | 通知推送、LLM 错误分析、日志 |
| [infra/log-design-language.md](infra/log-design-language.md) | 日志设计语言规范（LDL）：数据模型、全项目语义词典与 WebUI 解析渲染标准 |
| [infra/submodule-tools.md](infra/submodule-tools.md) | 外部桥接（MAA/FGO）与 dev_tools 工具集 |
| [infra/deploy.md](infra/deploy.md) | 部署与启动链路：安装器、启动脚本、Docker、依赖自举 |
| [infra/testing.md](infra/testing.md) | 测试体系：Python 单测、前端单测与两套 e2e 的边界 |

### 战斗与地图

| 文档 | 主题 |
| --- | --- |
| [combat.md](combat.md) | 战斗系统：战斗循环、结算、阵容 |
| [map.md](map.md) | 地图系统与检测：网格感知、透视、寻路 |
| [campaign.md](campaign.md) | 战役执行：关卡选择、进图、任务入口聚合 |

### 大世界（Operation Siren）

| 文档 | 主题 |
| --- | --- |
| [os/index.md](os/index.md) | 大世界核心：导航、行动力经济、智能调度 |
| [os/auxiliary.md](os/auxiliary.md) | 大世界辅助包：os_handler/os_ash/os_combat/os_shop/os_simulator |

### 游戏功能

| 文档 | 主题 |
| --- | --- |
| [game/daily-maintenance.md](game/daily-maintenance.md) | 日常维护合集（委托、科研、商店等） |
| [game/misc.md](game/misc.md) | 其他游戏功能 |
| [game/commission.md](game/commission.md) | 委托系统 |
| [game/research.md](game/research.md) | 科研系统 |
| [game/shop.md](game/shop.md) | 商店系统 |
| [game/retire-equipment.md](game/retire-equipment.md) | 退役与装备管理 |
| [game/island.md](game/island.md) | 岛屿季度玩法 |
| [game/secretary.md](game/secretary.md) | 秘书舰轮换 |
| [game/game-settings.md](game/game-settings.md) | 游戏设置与 PlayerPrefs |

### WebUI

| 文档 | 主题 |
| --- | --- |
| [webui/index.md](webui/index.md) | WebUI 总览 |
| [webui/api.md](webui/api.md) | API 服务（WebSocket v1） |
| [webui/runtime.md](webui/runtime.md) | 运行时服务与进程管理 |
| [webui/frontend.md](webui/frontend.md) | 前端（React + TypeScript + Vite） |
| [webui/resource-management.md](webui/resource-management.md) | 资源管理：任务来源、用途、库存对账、桑基图与石油控制 |
| [webui/mind-calculator.md](webui/mind-calculator.md) | 心智单元计算器：船坞扫描、人工核对、费用计算及文件互通 |
| [webui/frontend-state.md](webui/frontend-state.md) | 前端状态机制：保存队列、草稿恢复与连接状态 |
| [webui/accounts.md](webui/accounts.md) | 实例账号管理：保险库加密、TPM/DPAPI 密钥与应用私有目录一致性 |

## 维护约定

- 新增模块文档时同步本索引，并按 [WRITING-GUIDE.md](WRITING-GUIDE.md) 的撰写规范执行（20 节结构、三级标准、写作原则）。
- 目录、依赖与行为以当前代码、清单及 CI 为准；文档与代码冲突时先修文档。

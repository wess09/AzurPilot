---
description:
alwaysApply: true
---

# 模块映射表

**生成日期**: 2026-05-27
**项目版本**: dev 分支

## 项目概述

- **项目类型**: 桌面自动化工具 + WebUI 管理界面
- **主要语言**: Python 3.14+
- **框架**: PyWebIO + Starlette + uvicorn (WebUI), ADB/uiautomator2 (设备控制)
- **包管理器**: uv (项目模式)
- **总文件数**: 2654 个 Python 文件

---

## 模块分层架构

### 第一层：入口层

| 模块名称 | 包含文件 | 说明 |
|---------|---------|------|
| **alas** | `alas.py` | 核心调度器入口 |
| **gui** | `gui.py` | WebUI 启动器 |
| **mcp_server** | `mcp_server_sse.py` | MCP SSE 服务器 |

### 第二层：核心基础层

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **base** | `module/base/` | 基础工具类：Button、Template、Filter、Timer、装饰器 |
| **config** | `module/config/` | 配置系统：YAML 解析、配置生成、i18n |
| **device** | `module/device/` | 设备连接层：ADB、截图、输入模拟 |
| **ui** | `module/ui/` | UI 导航系统：Page、路由 |
| **ocr** | `module/ocr/` | OCR 文字识别系统 |
| **handler** | `module/handler/` | 游戏处理器：登录、自动搜索、信息处理 |

### 第三层：战斗系统层

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **combat** | `module/combat/` | 战斗逻辑：自动/手动战斗、情绪、血量 |
| **combat_ui** | `module/combat_ui/` | 战斗 UI 界面 |
| **map** | `module/map/` | 地图处理：摄像机、舰队、网格 |
| **map_detection** | `module/map_detection/` | 地图检测：单应性、透视、网格预测 |
| **campaign** | `module/campaign/` | 战役执行逻辑 |

### 第四层：游戏功能模块

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **research** | `module/research/` | 科研系统 |
| **commission** | `module/commission/` | 委托系统 |
| **tactical** | `module/tactical/` | 战术学院 |
| **dorm** | `module/dorm/` | 宿舍管理 |
| **meowfficer** | `module/meowfficer/` | 指挥喵 |
| **guild** | `module/guild/` | 大舰队 |
| **shop** | `module/shop/` | 商店系统 |
| **shop_event** | `module/shop_event/` | 活动商店 |
| **reward** | `module/reward/` | 奖励收取 |
| **exercise** | `module/exercise/` | 演习 PvP |
| **gacha** | `module/gacha/` | 建造系统 |
| **daily** | `module/daily/` | 每日任务 |
| **hard** | `module/hard/` | 困难模式 |
| **sos** | `module/sos/` | SOS 任务 |
| **war_archives** | `module/war_archives/` | 作战档案 |
| **raid** | `module/raid/` | 突袭任务 |
| **event** | `module/event/` | 活动处理 |
| **eventstory** | `module/eventstory/` | 活动剧情 |
| **event_hospital** | `module/event_hospital/` | 医院活动 |
| **coalition** | `module/coalition/` | 联动活动 |
| **island** | `module/island/` | 岛屿系统 |
| **private_quarters** | `module/private_quarters/` | 私人休息室 |
| **shipyard** | `module/shipyard/` | 船坞系统 |
| **freebies** | `module/freebies/` | 免费福利 |
| **minigame** | `module/minigame/` | 小游戏 |
| **awaken** | `module/awaken/` | 觉醒系统 |
| **retire** | `module/retire/` | 退役系统 |
| **equipment** | `module/equipment/` | 装备管理 |
| **meta_reward** | `module/meta_reward/` | META 奖励 |

### 第五层：大世界系统

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **os** | `module/os/` | 大世界核心 |
| **os_combat** | `module/os_combat/` | 大世界战斗 |
| **os_handler** | `module/os_handler/` | 大世界事件处理 |
| **os_ash** | `module/os_ash/` | 余烬/信标系统 |
| **os_shop** | `module/os_shop/` | 大世界商店 |
| **os_simulator** | `module/os_simulator/` | 大世界模拟器 |

### 第六层：基础设施层

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **statistics** | `module/statistics/` | 掉落统计 |
| **azur_stats** | `module/azur_stats/` | AzurStats 数据提交 |
| **notify** | `module/notify/` | 推送通知 |
| **daemon** | `module/daemon/` | 守护模式 |
| **webui** | `module/webui/` | WebUI 应用 |
| **submodule** | `module/submodule/` | 外部桥接 |
| **llm** | `module/llm.py` | LLM 错误分析 |
| **logger** | `module/logger.py` | 日志系统 |

### 第七层：战役数据层

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **campaign_main** | `campaign/campaign_main/` | 主线战役数据 |
| **campaign_hard** | `campaign/campaign_hard/` | 困难战役数据 |
| **campaign_sos** | `campaign/campaign_sos/` | SOS 战役数据 |
| **event_*_cn** | `campaign/event_*/` | 各活动战役数据 |
| **war_archives_*_cn** | `campaign/war_archives_*/` | 作战档案数据 |

### 第八层：资源与工具层

| 模块名称 | 目录 | 说明 |
|---------|------|------|
| **assets** | `assets/` | UI 模板图像（按服务器组织） |
| **bin** | `bin/` | 二进制工具、OCR 模型 |
| **dev_tools** | `dev_tools/` | 开发工具 |
| **deploy** | `deploy/` | 部署脚本 |
| **config** | `config/` | 配置模板 |
| **webapp** | `webapp/` | Electron 桌面应用 |

---

## 模块依赖关系概览

```
入口层 (alas.py, gui.py, mcp_server_sse.py)
    ↓
核心基础层 (base, config, device, ui, ocr)
    ↓
战斗系统层 (combat, map, campaign)
    ↓
游戏功能层 (research, commission, dorm, ...)
    ↓
基础设施层 (statistics, notify, daemon, webui)
```

---

## 关键文件清单

### 入口文件
- `alas.py` - 核心调度器（约 500 行）
- `gui.py` - WebUI 启动器（约 150 行）
- `mcp_server_sse.py` - MCP 服务器（约 200 行）

### 配置文件
- `module/config/argument/*.yaml` - 配置源文件
- `module/config/argument/args.json` - 生成的配置
- `module/config/config_generated.py` - 生成的 Python 类
- `config/template.json` - 配置模板

### 核心模块入口
- `module/base/base.py` - ModuleBase 基类
- `module/config/config.py` - AzurLaneConfig 配置类
- `module/device/device.py` - Device 设备类
- `module/ui/ui.py` - UI 导航类
- `module/ocr/ocr.py` - OCR 识别类

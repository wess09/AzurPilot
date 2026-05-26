
# AzurPilot

<p align="center">
  <a href="https://deepwiki.com/wess09/AzurPilot">
    <img src="https://deepwiki.com/badge.svg" alt="DeepWiki" height="22">
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/github/license/wess09/AzurPilot?style=flat-square&label=License&color=2ea44f" alt="License">
  <img src="https://img.shields.io/github/stars/wess09/AzurPilot?style=flat-square&label=Stars&color=ffcc00" alt="Stars">
  <img src="https://img.shields.io/github/forks/wess09/AzurPilot?style=flat-square&label=Forks&color=58a6ff" alt="Forks">
  <img src="https://img.shields.io/github/issues/wess09/AzurPilot?style=flat-square&label=Issues&color=f85149" alt="Issues">
</p>

<p align="center">
  <img src="https://img.shields.io/github/last-commit/wess09/AzurPilot?style=flat-square&label=Last%20Commit&color=8b949e" alt="Last Commit">
  <img src="https://img.shields.io/github/commit-activity/m/wess09/AzurPilot?style=flat-square&label=Commit%20Activity&color=8957e5" alt="Commit Activity">
  <img src="https://img.shields.io/github/repo-size/wess09/AzurPilot?style=flat-square&label=Repo%20Size&color=orange" alt="Repo Size">
  <img src="https://img.shields.io/github/languages/top/wess09/AzurPilot?style=flat-square&label=Top%20Language&color=3776AB" alt="Top Language">
</p>

<p align="center">
  <img src="https://img.shields.io/github/contributors/wess09/AzurPilot?style=flat-square&label=Contributors&color=00b4d8" alt="Contributors">
  <img src="https://img.shields.io/github/issues-pr/wess09/AzurPilot?style=flat-square&label=Pull%20Requests&color=ffb703" alt="Pull Requests">
  <img src="https://img.shields.io/github/issues-pr-closed/wess09/AzurPilot?style=flat-square&label=PRs%20Closed&color=2ea44f" alt="Closed Pull Requests">
</p>

## 项目简介

AzurPilot 是基于 AzurLaneAutoScript 修改而来的碧蓝航线自动化辅助项目，保留原项目的核心能力，并在此基础上整合了多个分支、功能改进和实验性特性。

本项目代码基本由 AI 代码生成与辅助编写，存在较大的不确定性，欢迎提交 [Pull Request](https://github.com/wess09/AzurPilot/pulls) 改正。

项目原始来源与相关分支：

- LmeSzinc/AzurLaneAutoScript 原项目及其生态分支 @LmeSzinc
- yukikaze21/AzurLaneAutoScriptyukikaze21 大世界部分功能 @yukikaze21
- Zuosizhu/Alas-with-Dashboard 的仪表盘 @Zuosizhu
- guoh064/AzurLaneAutoScript 大世界部分功能 @guoh064
- sui-feng-cb/AzurLaneAutoScript 岛屿计划 @sui-feng-cb
- 其他社区贡献的实用 [Pull Request](https://github.com/LmeSzinc/AzurLaneAutoScript/pulls)

<div align="center">
  <a href="https://alas.nanoda.work">
    <img src="https://img.shields.io/badge/Web-下载-blue?style=for-the-badge&logo=google-chrome&logoColor=white" />
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://addgroup.nanoda.work/#/">
    <img src="https://img.shields.io/badge/交流群-QQ-red?style=for-the-badge&logo=tencent-qq&logoColor=white" />
  </a>
</div>

## GUI
<div align="center">
  <img src="doc/GUI.png" alt="GUI Preview" width="800">
</div>

## 依赖与启动

本项目使用 `uv` 和项目根目录 `.venv` 管理 Python 运行环境。发布版启动器会自带 uv、Python、ADB、Git，并在 `.venv` 中同步依赖；源码开发时可安装 uv 后运行：

```bash
uv sync --frozen --no-dev
uv run python gui.py
```

依赖声明在 `pyproject.toml` 中，锁定结果提交在 `uv.lock`。不要再维护或生成 `requirements*.txt`。

## 重要说明

本项目包含大量自动化逻辑和图像识别相关功能。使用前请确保已经按照本文档完成游戏内设置，否则可能导致识别失败、流程异常或任务无法正常执行。

本项目包含部分实验性功能，可能存在未知问题。建议在使用前备份相关配置，并在发现异常时及时反馈。

## 使用前设置

使用前必须按照以下标准修改游戏内设置。

路径：

主界面，右下角设置，左侧边栏选项。

| 设置名称 | 推荐值 |
| --- | --- |
| 帧数设置 | 60 帧 |
| 大型作战设置，减少 TB 引导 | 开 |
| 大型作战设置，自律时自动提交道具 | 开 |
| 大型作战设置，安全海域默认开启自律 | 关 |
| 剧情自动播放 | 开启 |
| 剧情自动播放速度调整 | 特快 |
| 待机模式设置，启用待机模式 | 关 |
| 其他设置，重复角色获得提示 | 关 |
| 其他设置，快速更换二次确认界面 | 关 |
| 其他设置，展示结算角色 | 关 |

### 大型作战设置

路径：

大型作战，右上角雷达，指令模块，潜艇支援。

| 设置名称 | 推荐值 |
| --- | --- |
| X 消耗时潜艇出击 | 取消勾选 |

### 一键退役设置

路径：

主界面，右下角建造，左侧边栏退役，左侧齿轮图标，一键退役设置。

| 设置名称 | 推荐值 |
| --- | --- |
| 选择优先级 1 | R |
| 选择优先级 2 | SR |
| 选择优先级 3 | N |
| 拥有满星的同名舰船时，保留几艘符合退役条件的同名舰船 | 不保留 |
| 没有满星的同名舰船时，保留几艘符合退役条件的同名舰船 | 满星所需或不保留 |

### 图像识别注意事项

请移除以下可能影响识别的内容：

- 角色设备装备
- 角色皮肤
- 可能遮挡界面元素的自定义显示内容

这些内容可能影响图像识别结果，导致自动化流程出现异常。

## 主要改动

本分支在原项目基础上加入或整合了以下内容：

1. 岛屿计划自动化
2. 共斗沉船（牺牲指定位置舰船）
3. 大世界智能调度（自动切换侵蚀1练级与黄币补充任务）
4. 大世界蒙特卡洛模拟器（估算侵蚀循环收益）
5. 拆解装备箱（按保留数量拆白/蓝/紫箱）
6. 全新 OCR 模型
7. 共用心情（多个出击任务共享同一队心情）
8. 自定义任务优先级
9. 大世界舰队经验检测（满经验推送）
10. 侵蚀一舰队自动配队（自动更换满经验舰船）
11. 塞壬研究装置（紫币换黄币，探测资源/敌人）
12. 大世界海域成就（刷安全海域星星）
13. 定时重启模拟器
14. 远程SSH管理（执行命令如重启docker）
15. 大世界独立推送（与错误推送分离）
16. 维修箱修船（支持侵蚀1单独阈值）
17. 大世界信息推送开关（侵蚀1和短猫信息）
18. 白票商店购买战役信息记录仪/隐秘海域记录仪
19. 每月开荒进度显示
20. 演习推迟策略（至下次更新前X小时）
21. GUI仪表盘（实时显示石油、物资、魔方、大世界币等）
22. OOBE首次设置向导（选择语言、服务器、模拟器等）
23. 日志备份管理（保留数量、压缩备份）
24. LLM错误分析（调用大模型分析报错原因）
25. 游戏卡死或ADB离线时自动重启模拟器
26. 物资超过阈值停止出击
27. 道中战斗失败可撤退或换队接管
28. 困难图自动配队（使用推荐阵容）
29. 关卡名称支持“7-2-3”格式（三战后撤退）
30. 科研魔方保留阈值（低于设定值时不选魔方项目）
31. 各商店独立开关（可单独关闭军火商、舰队商店等）
32. GPU加速推理（Windows DirectML / macOS ANE / ncnn Vulkan）
33. OCR设备选择（CPU / GPU / ANE）
34. 共斗每日支持沉船模式

* 由 DeepSeek 结合项目分析生成 实际请以实物为准

## 多平台启动器

<div align="center">
  <img src="doc/loading.png" alt="loading" width="500" />
  <p>启动加载界面</p>
  <img src="doc/GUI.png" alt="GUI" width="500" />
  <p>Windows 客户端界面</p>
  <img src="doc/macGUI.png" alt="macGUI" width="500" />
  <p>Mac 客户端界面</p>
</div>
启动器项目地：

[GitHub](https://github.com/wess09/alas-launcher) 源项目 [ALAS Launcher: 一种新型的 AzurLaneAutoScript 启动器](https://github.com/swordfeng/alas-launcher)

更改内容：
1. 增加托盘化功能
2. Windows原生推送
3. GUI样式美化

## MCP 服务

AzurPilot 提供 MCP 服务，可供支持 MCP 的客户端或工具调用。

通过 MCP 您可以方便的使用 Agent 管理 AzurPilot

### 本地连接配置

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://127.0.0.1:22267/mcp/sse"
    }
  }
}
```

### 云服务器或内网连接配置

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://[IP_ADDRESS]/mcp/sse"
    }
  }
}
```

请将 `[IP_ADDRESS]` 替换为实际服务器地址或内网地址。

## MCP 工具列表

当前可用 MCP 工具共 18 个。

### 实例管理

| 工具名称 | 功能 |
| --- | --- |
| list_instances | 列出所有实例 |
| get_status | 获取实例状态 |
| start_instance | 启动实例 |
| stop_instance | 停止实例 |

### 任务管理

| 工具名称 | 功能 |
| --- | --- |
| list_tasks | 列出所有任务 |
| get_task_help | 获取任务帮助 |
| trigger_task | 触发任务 |
| get_scheduler_queue | 获取调度队列 |
| clear_scheduler_queue | 清空调度队列 |

### 监控与信息

| 工具名称 | 功能 |
| --- | --- |
| get_current_running_task | 获取当前运行任务 |
| get_resources | 获取资源状态 |
| get_config | 获取实例配置 |
| get_recent_logs | 获取最近日志 |
| get_screenshot | 获取截图 |

### 配置管理

| 工具名称 | 功能 |
| --- | --- |
| update_config | 更新配置 |

### 维护工具

| 工具名称 | 功能 |
| --- | --- |
| restart_emulator | 重启模拟器 |
| restart_adb | 重启 ADB |
| update_alas | 更新 ALAS |

## 赞助支持

<p align="center">
  <a href="https://afdian.com/a/miaonaa">
    <img src="doc/afdian.jfif" alt="爱发电" width="200">
  </a>
  <br>
  <b>支持本项目(用于支付服务器费用或训练新模型等)</b>
</p>

## OCR 模型

本项目使用基于 PaddleOCR 的定制 OCR 模型，用于适配碧蓝航线界面字体和 Alas 截图场景。

感谢超算互联网提供算力支持。

相关项目：

[https://github.com/PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)

<p>
  <a href="https://arxiv.org/pdf/2507.05595">
    <img src="https://img.shields.io/badge/PaddleOCR_3.0-Technical%20Report-b31b1b.svg?logo=arXiv" alt="PaddleOCR Technical Report">
  </a>
  <img src="https://img.shields.io/badge/hardware-cpu%2C%20gpu%2C%20xpu%2C%20npu-yellow.svg" alt="Hardware">
</p>

### V1.0

| 项目 | 内容 |
| --- | --- |
| 支持语言 | zh-cn, en-us |
| 训练目标 | 针对碧蓝航线字体进行训练 |
| zh-cn 准确率 | 97% |
| en-us 准确率 | 98.6% |
| 已知问题 | zh-cn 存在边缘符号问题，en-us 可能出现负号问题 |
| 训练硬件 | 异构加速卡 BW 64G，NVIDIA Tesla A800 80G |
| 训练时间 | 2 小时 |

### V2.0

| 项目 | 内容 |
| --- | --- |
| 支持语言 | zh-cn, en-us |
| 训练目标 | 针对碧蓝航线字体与 Alas 截图特性进行训练 |
| 处理方式 | 灰度化 |
| zh-cn 表现 | 相对 V1.0 准确率降低 |
| en-us 准确率 | 99.8% |
| 已知问题 | en-us 基本无明显错误 |
| 训练硬件 | NVIDIA Tesla A800 80G |
| 训练时间 | 2 小时 |

### V2.5

| 项目 | 内容 |
| --- | --- |
| 支持语言 | zh-cn |
| 训练目标 | 修复 V2.0 中文模型问题 |
| 准确率 | 98.52% |
| 推理速度 | 约 10 ms |
| 训练硬件 | 异构加速卡 BW 64G，NVIDIA Tesla A800 80G |
| 训练时间 | 5 小时 |

## 贡献者

由于本项目基于 AzurLaneAutoScript 及其社区分支继续开发，贡献者列表不仅包含本仓库的直接贡献者，也包含上游项目与相关分支中的原始贡献者。

感谢所有为 AzurPilot、原上游 AzurLaneAutoScript 及相关分支做出贡献的开发者。

<a href="https://github.com/wess09/AzurPilot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/AzurPilot&max=1000" alt="AzurPilot Contributors">
</a>

感谢所有为启动器项目做出贡献的开发者。

<a href="https://github.com/wess09/alas-launcher/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/alas-launcher&max=1000" alt="Launcher Contributors">
</a>

## 开发说明

本项目基本完全是 VibeCoding 产物 不足之处请见谅

欢迎通过 Issue 或 Pull Request 反馈问题、提交修复或改进文档。

## 使用过的开发工具与模型

本项目开发过程中使用过多种 AI 模型与开发工具进行辅助。

### AI 模型

| 模型 | 模型 | 模型 |
| --- | --- | --- |
| Gemini 3 Flash | Gemini 3.1 Pro | Claude Opus 4.5 |
| Claude Sonnet 4.5 | MiMo V2.5 Pro | GPT 5.4 |
| GPT 5.3 Codex | Qwen 3 Max | DeepSeek v4 |
| Kimi K2.5 | GLM 4.7 | MiMo V2.5 |

### 开发工具

| 工具 | 工具 | 工具 | 工具 |
| --- | --- | --- | --- |
| Claude Code | Codex | Cursor | Antigravity |

## 许可证

本项目遵循原项目及相关上游项目的许可证要求。启动器项目遵循 GPL-3.0 协议开源。

使用、修改或分发本项目时，请同时遵守相关上游项目的许可证要求。

# 🌸 屎山代码分析报告 🌸

## 📑 目录

- [糟糕指数](#overall-score)
- [评分指标详情](#metrics-details)
- [最屎代码排行榜](#problem-files)
- [诊断结论](#conclusion)

![Score](https://img.shields.io/badge/Score-89%25-brightgreen)

## 糟糕指数 {#overall-score}

| 指标摘要 | 评分 |
|------|-------|
| **糟糕指数** | **88.95/100** |
| 屎山等级 | 🌸 偶有异味 |

> 清新宜人，初闻像早晨的露珠

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 1877 |
| 已跳过 | 16063 |
| 耗时 | 5052ms |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | 状态 |
|:-----|------:|:------:|
| 循环复杂度 | 3.80% | ✓✓ |
| 认知复杂度 | 4.91% | ✓✓ |
| 嵌套深度 | 1.09% | ✓✓ |
| 函数长度 | 2.09% | ✓✓ |
| 文件长度 | 0.84% | ✓✓ |
| 参数数量 | 2.13% | ✓✓ |
| 代码重复 | 7.99% | ✓✓ |
| 结构分析 | 1.78% | ✓✓ |
| 错误处理 | 5.26% | ✓✓ |
| 注释比例 | 55.48% | • |
| 命名规范 | 4.25% | ✓✓ |

## 最屎代码排行榜 {#problem-files}

### 1. module\webui\app.py

**糟糕指数: 49.33**

**问题**: 🔄 复杂度问题: 34, ⚠️ 其他问题: 28, 🏗️ 结构问题: 22, ❌ 错误处理问题: 43, 📝 注释问题: 1, 🏷️ 命名问题: 10

- 🔄 `_render_ap_chart()` L448: 复杂度: 86
- 🔄 `_render_opsi_stats()` L1095: 复杂度: 80
- 🔄 `export_opsi_csv()` L1700: 复杂度: 30
- 🔄 `_render_ship_exp()` L1869: 复杂度: 14
- 🔄 `_render_commission_income()` L2030: 复杂度: 31
- 🔍 ...还有 130 个问题实在太屎，列不完了

### 2. mcp_server_sse.py

**糟糕指数: 48.13**

**问题**: 🔄 复杂度问题: 5, ⚠️ 其他问题: 3, 🏗️ 结构问题: 3, ❌ 错误处理问题: 4, 📝 注释问题: 1

- 🔄 `call_tool()` L202: 复杂度: 57
- 🔄 `call_tool()` L202: 认知复杂度: 71
- 🔄 `mcp_asgi_app()` L458: 认知复杂度: 18
- 🔄 `call_tool()` L202: 嵌套深度: 7
- 🔄 `mcp_asgi_app()` L458: 嵌套深度: 4
- 🔍 ...还有 9 个问题实在太屎，列不完了

### 3. module\os\map.py

**糟糕指数: 43.93**

**问题**: 🔄 复杂度问题: 37, ⚠️ 其他问题: 15, 📋 重复问题: 3, 🏗️ 结构问题: 21, ❌ 错误处理问题: 1, 📝 注释问题: 1, 🏷️ 命名问题: 7

- 🔄 `os_init()` L48: 复杂度: 18
- 🔄 `handle_storage_fleet_repair()` L406: 复杂度: 11
- 🔄 `handle_fleet_repair_by_config()` L455: 复杂度: 17
- 🔄 `os_auto_search_daemon()` L902: 复杂度: 30
- 🔄 `os_auto_search_daemon_until_combat()` L1007: 复杂度: 24
- 🔍 ...还有 77 个问题实在太屎，列不完了

### 4. module\os\tasks\hazard_leveling.py

**糟糕指数: 41.10**

**问题**: 🔄 复杂度问题: 17, ⚠️ 其他问题: 9, 📋 重复问题: 1, 🏗️ 结构问题: 6, ❌ 错误处理问题: 8, 📝 注释问题: 1, 🏷️ 命名问题: 10

- 🔄 `_cl1_smart_scheduling_check()` L43: 复杂度: 24
- 🔄 `os_check_leveling()` L408: 复杂度: 28
- 🔄 `_format_check_report()` L567: 复杂度: 14
- 🔄 `_collect_ship_data_with_retry()` L738: 复杂度: 12
- 🔄 `_check_custom_positions_full_exp()` L877: 复杂度: 12
- 🔍 ...还有 45 个问题实在太屎，列不完了

### 5. module\os_simulator\simulator.py

**糟糕指数: 40.39**

**问题**: 🔄 复杂度问题: 9, ⚠️ 其他问题: 5, 📋 重复问题: 3, 🏗️ 结构问题: 3, ❌ 错误处理问题: 1, 📝 注释问题: 1, 🏷️ 命名问题: 10

- 🔄 `_simulate_one()` L48: 复杂度: 22
- 🔄 `get_paras()` L197: 复杂度: 14
- 🔄 `simulate()` L377: 复杂度: 11
- 🔄 `_simulate_one()` L48: 认知复杂度: 30
- 🔄 `_simulate_batch_kernel()` L140: 认知复杂度: 19
- 🔍 ...还有 25 个问题实在太屎，列不完了

### 6. module\statistics\cl1_database.py

**糟糕指数: 39.08**

**问题**: 🔄 复杂度问题: 17, ⚠️ 其他问题: 9, 📋 重复问题: 3, 🏗️ 结构问题: 13, ❌ 错误处理问题: 31, 📝 注释问题: 1, 🏷️ 命名问题: 10

- 🔄 `_normalize_meow_hazard_stats()` L258: 复杂度: 20
- 🔄 `_reconcile_meow_counts()` L372: 复杂度: 19
- 🔄 `migrate_from_json()` L726: 复杂度: 11
- 🔄 `get_meow_stats()` L940: 复杂度: 31
- 🔄 `_check_key_migration()` L105: 认知复杂度: 16
- 🔍 ...还有 77 个问题实在太屎，列不完了

### 7. module\device\connection.py

**糟糕指数: 38.47**

**问题**: 🔄 复杂度问题: 16, ⚠️ 其他问题: 8, 🏗️ 结构问题: 12, ❌ 错误处理问题: 9, 🏷️ 命名问题: 8

- 🔄 `retry_wrapper()` L32: 复杂度: 12
- 🔄 `_nc_server_host_port()` L435: 复杂度: 13
- 🔄 `adb_connect()` L774: 复杂度: 18
- 🔄 `detect_device()` L1079: 复杂度: 42
- 🔄 `retry_wrapper()` L32: 认知复杂度: 18
- 🔍 ...还有 47 个问题实在太屎，列不完了

### 8. module\map\fleet.py

**糟糕指数: 37.16**

**问题**: 🔄 复杂度问题: 28, ⚠️ 其他问题: 6, 🏗️ 结构问题: 17, ❌ 错误处理问题: 2, 📝 注释问题: 1

- 🔄 `round_wait()` L196: 复杂度: 11
- 🔄 `_goto()` L256: 复杂度: 70
- 🔄 `goto()` L475: 复杂度: 16
- 🔄 `full_scan()` L550: 复杂度: 11
- 🔄 `track_movable()` L611: 复杂度: 30
- 🔍 ...还有 46 个问题实在太屎，列不完了

### 9. module\commission\commission.py

**糟糕指数: 36.00**

**问题**: 🔄 复杂度问题: 22, ⚠️ 其他问题: 9, 📋 重复问题: 1, 🏗️ 结构问题: 9, 📝 注释问题: 1, 🏷️ 命名问题: 10

- 🔄 `_commission_choose()` L116: 复杂度: 21
- 🔄 `_commission_ensure_mode()` L234: 复杂度: 11
- 🔄 `_commission_start_click()` L356: 复杂度: 13
- 🔄 `_record_commission_income()` L523: 复杂度: 18
- 🔄 `_commission_receive()` L622: 复杂度: 28
- 🔍 ...还有 44 个问题实在太屎，列不完了

### 10. module\shop_event\shop_event.py

**糟糕指数: 35.21**

**问题**: 🔄 复杂度问题: 6, ⚠️ 其他问题: 2, 🏗️ 结构问题: 3, 📝 注释问题: 1, 🏷️ 命名问题: 1

- 🔄 `handle_items_related_with_urpt()` L35: 复杂度: 28
- 🔄 `handle_items_related_with_urpt()` L35: 认知复杂度: 44
- 🔄 `_run()` L187: 认知复杂度: 15
- 🔄 `run()` L244: 认知复杂度: 18
- 🔄 `handle_items_related_with_urpt()` L35: 嵌套深度: 8
- 🔍 ...还有 7 个问题实在太屎，列不完了

## 诊断结论 {#conclusion}

🌸 **偶有异味** - 基本没事，但是有伤风化

👍 继续保持，你是编码界的一股清流，代码洁癖者的骄傲

---

*由 [fuck-u-code](https://github.com/Done-0/fuck-u-code) 生成*

### 以上问题待解决（没招了 请求手搓大手子）

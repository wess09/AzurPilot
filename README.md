**| [English](README_en.md) | 简体中文 | [日本語](README_jp.md) |**

# AzurPilot

碧蓝航线小助手，无缝委托科研，全自动大世界 基于 AzurLaneAutoScript 二次修改 感觉用原名不太好 所以改了（ 本质上还是ALAS 

[下载链接](https://alas.nanoda.work/download.html)

我们屁眼通红(Python)真的太有实力了

此分支是[雪风源（目前仓库已删库）](https://gitee.com/yukikaze21/AzurLaneAutoScriptyukikaze21)的 fork 分支 [原版雪风源](https://gitee.com/wqeaxc/AzurLaneAutoScriptyukikaze21)

- 注：之前fork了[原版雪风源](https://gitee.com/wqeaxc/AzurLaneAutoScriptyukikaze21)你可以在这个仓库查看雪风的提交 下面的雪风源也是 fork 版

## 修改游戏设置

使用前**必须**对照这个表格修改游戏内的设置，~~正常玩过游戏的都这么设置~~。

> 对着改的意思是，这是统一的标准，照着给定的内容执行，不要问为什么，不允许有不一样的。

主界面 => 右下角：设置 => 左侧边栏：选项

| 设置名称                            | 值   |
| ----------------------------------- | ---- |
| 帧数设置                            | 60帧 |
| 大型作战设置 - 减少TB引导           | 开   |
| 大型作战设置 - 自律时自动提交道具   | 开   |
| 大型作战设置 - 安全海域默认开启自律 | 关   |
| 剧情自动播放                        | 开启 |
| 剧情自动播放速度调整                | 特快 |
| 待机模式设置 - 启用待机模式         | 关    |
| 其他设置 - 重复角色获得提示         | 关   |
| 其他设置 - 快速更换二次确认界面     | 关   |
| 其他设置 - 展示结算角色             | 关   |

大世界 => 右上角：雷达 => 指令模块(order)：潜艇支援：
| 设置名称                                                 | 值               |
| -------------------------------------------------------- | ---------------- |
| X 消耗时潜艇出击  |取消勾选|

主界面 => 右下角：建造 => 左侧边栏： 退役 => 左侧齿轮图标：一键退役设置：

| 设置名称                                                 | 值               |
| -------------------------------------------------------- | ---------------- |
| 选择优先级1                                              | R                |
| 选择优先级2                                              | SR               |
| 选择优先级3                                              | N                |
| 「拥有」满星的同名舰船时，保留几艘符合退役条件的同名舰船 | 不保留           |
| 「没有」满星的同名舰船时，保留几艘符合退役条件的同名舰船 | 满星所需或不保留 |

将角色设备的装备外观移除，以免影响图像识别

## 添加了

1. 智能调度
2. 解除大世界限制
3. 对 侵蚀1 的一些功能*
4. Lme没合的一些陈旧PR等
5. 自动卡吊机BUG
6. 舰娘等级识别
7. 侵蚀1的一些统计
8. 模拟器管理
9. 一些奇怪的小东西awa
10. 迁移至 Python 3.14
11. 更换 OCR 模型 支持 GPU 加速推理
12. Alas MCP 服务

## 多平台启动器说明

启动器项目 https://github.com/wess09/alas-launcher fork于 https://github.com/swordfeng/alas-launcher 进行了部分修改

严格遵守上游许可证延续使用 GPL-3 协议开源

## MCP 服务

本地
```json
{
  "mcpServers": {
    "alas": {
      "url": "http://127.0.0.1:22267/mcp/sse"
    }
  }
}
```
云服务器或内网
```json
{
  "mcpServers": {
    "alas": {
      "url": "http://[IP_ADDRESS]/mcp/sse"
    }
  }
}
```

## 当前可用的 MCP 工具（共 18 个）：

实例管理

- mcp_alas_list_instances - 列出所有实例
- mcp_alas_get_status - 获取实例状态
- mcp_alas_start_instance - 启动实例
- mcp_alas_stop_instance - 停止实例

任务管理

- mcp_alas_list_tasks - 列出所有任务
- mcp_alas_get_task_help - 获取任务帮助
- mcp_alas_trigger_task - 触发任务
- mcp_alas_get_scheduler_queue - 获取调度队列
- mcp_alas_clear_scheduler_queue - 清空调度队列

监控与信息

- mcp_alas_get_current_running_task - 获取当前运行任务
- mcp_alas_get_resources - 获取资源状态
- mcp_alas_get_config - 获取实例配置
- mcp_alas_get_recent_logs - 获取最近日志
- mcp_alas_get_screenshot - 获取截图

配置管理

- mcp_alas_update_config - 更新配置

维护工具

- mcp_alas_restart_emulator - 重启模拟器
- mcp_alas_restart_adb - 重启 ADB
- mcp_alas_update_alas - 更新 ALAS

*侵蚀1功能：大部分来自下面
## 部分功能（大部分）来自[Zuosizhu(仪表盘等)](https://github.com/Zuosizhu/Alas-with-Dashboard)，[guoh064(大世界等)](https://github.com/guoh064/AzurLaneAutoScript)，[sui-feng-cb(岛屿等)](https://github.com/sui-feng-cb/AzurLaneAutoScript), [雪风源](https://gitee.com/wqeaxc/AzurLaneAutoScriptyukikaze21)

 [有任何问题请加 QQ 群](https://addgroup.nanoda.work/#/)

 # OCR 模型
感谢 [超算互联网](www.scnet.cn) 提供算力支持 模型基于 [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)

[![arXiv](https://img.shields.io/badge/PaddleOCR_3.0-Technical%20Report-b31b1b.svg?logo=arXiv)](https://arxiv.org/pdf/2507.05595)![hardware](https://img.shields.io/badge/hardware-cpu%2C%20gpu%2C%20xpu%2C%20npu-yellow.svg)[![AI Studio](https://img.shields.io/badge/PaddleOCR-_Offiical_Website-1927BA?logo=data:image/png;base64,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&labelColor=white)](https://www.paddleocr.com)


## V1.0
v1.0 zh-cn&en-us
针对碧蓝航线字体进行训练
zh-cn 准确率 97% 有边缘符号问题
en-us 准确率 98.6% 会出现负号问题
训练信息:
异构加速卡BW 64G
NVIDIA Tesla A800 80G
训练时间: 2h

## V2.0
v2.0 zh-cn&en-us
针对碧蓝航线字体 + Alas 截图的特殊性进行训练(灰度化)
中文模型相对 v1.0 准确率降低
en-us 准确率 99.8% 几乎没有错误
训练信息:
NVIDIA Tesla A800 80G
训练时间: 2h

## V2.5
v2.5 zh-cn
修复2.0模型的问题
准确率达到 98.52%
推理速度仅需 10ms
训练信息:
异构加速卡BW 64G
NVIDIA Tesla A800 80G
训练时间: 5h

## 感谢
感谢以下开发者对本项目做出的贡献


<a href="https://github.com/wess09/AzurPilot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/AzurPilot&max=1000" />
</a>

感谢以下开发者对启动器项目做出的贡献

<a href="https://github.com/wess09/alas-launcher/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/alas-launcher&max=1000" />
</a>

## 感谢某不知名 AI IDE

注：本项目大量使用 **AI生成** 代码质量极其垃圾 **可能存在未知Bug**

~~因为本来是自用来着 没想公开~~


## 感谢以下 AI 模型

Gemini 3 Flash

Gemini 3.1Pro

Claude Opus 4.5

Claude Sonnet 4.5

GPT 5.4

GPT 5.3-codex

Qwen 3 Max

DeepSeek v3.2

Kimi K2.5

GLM 4.7

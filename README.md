**| [English](README_en.md) | 简体中文 | [日本語](README_jp.md) |**

# AzurLaneAutoScript

我们屁眼通红(Python)真的太有实力了

此分支是[雪风源（目前仓库已删库）](https://gitee.com/yukikaze21/AzurLaneAutoScriptyukikaze21)的 fork 分支 [原版雪风源](https://gitee.com/wqeaxc/AzurLaneAutoScriptyukikaze21)

- 注：之前fork了[原版雪风源](https://gitee.com/wqeaxc/AzurLaneAutoScriptyukikaze21)你可以在这个仓库查看雪风的提交 下面的雪风源也是 fork 版

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

*侵蚀1功能：大部分来自下面
## 部分功能（大部分）来自[Zuosizhu(仪表盘等)](https://github.com/Zuosizhu/Alas-with-Dashboard)，[guoh064(大世界等)](https://github.com/guoh064/AzurLaneAutoScript)，[sui-feng-cb(岛屿等)](https://github.com/sui-feng-cb/AzurLaneAutoScript), [雪风源](https://gitee.com/wqeaxc/AzurLaneAutoScriptyukikaze21)

## 感谢某不知名 AI IDE

注：本项目大量使用 **AI生成** 代码质量极其垃圾 **可能存在未知Bug**

~~因为本来是自用来着 没想公开~~

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
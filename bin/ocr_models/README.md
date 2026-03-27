# OCR 模型
感谢 www.scnet.cn 提供算力支持 基于 paddleocr

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

## V2.6
v3 zh-cn
准确率提升
准确率达到 99.78%
训练信息:
异构加速卡BW 64G
训练时间: 2h
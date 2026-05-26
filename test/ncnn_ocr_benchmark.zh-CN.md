# ncnn OCR 基准测试说明

本文档说明 `test/ncnn_ocr_benchmark.py` 这个 OCR 基准测试。EN/CN/JP/TW 单行识别已迁移到 ncnn；该脚本继续用于复测不同平台、不同 GPU/后端上的真实延迟、功耗和准确率，防止迁移后出现性能或准确率回退。

当前 ncnn 的主要吸引点是：可以通过 Vulkan 在多个平台上使用相对统一的 GPU 后端。它减少了 DirectML/CoreML/CUDA/ROCm 等平台分支，但仍需要各平台实测数据来决定默认策略。

## 为什么测试 ncnn

迁移前的加速路径大致是分平台的，迁移后仍需用它们作为对照：

| 平台 | 当前可能路径 | 说明 |
| --- | --- | --- |
| Windows | ONNX Runtime DirectML | 基于 DX12，适合 Windows，但不能迁移到 Linux。 |
| macOS arm64 | ONNX Runtime CoreML / ANE | 可能很好地利用 Apple Silicon/ANE，但依然是平台独有实现。 |
| Linux | ONNX Runtime CPU | 没有轻量GPU支持，引入cuda/rocm将导致数GiB的依赖，且其与系统级软件包高度绑定，实现复杂度过高。 |
| 全平台 | ncnn CPU / Vulkan | 理论上可覆盖 Linux、Windows、Android 的 Vulkan 设备；macOS 需要单独验证，通常要考虑 MoltenVK。 |

需要回答的问题不是简单的“Vulkan 是否更快”，而是：

- EN/CN 基准集是否都保持 `100%` 准确率？
- JP/TW 转换后的模型是否能稳定加载和推理？
- 延迟是否足够低，值得引入新的推理路径？
- 能耗是否下降，还是只是把 CPU 工作转移到 GPU？
- AMD、NVIDIA、Intel、Apple、Windows 等环境上的表现是否稳定？

## 依赖

Python 侧依赖：

```bash
rtk uv pip install ncnn onnx onnxsim
```

部分发行版的 `ncnn` 包不提供 `onnx2ncnn`。如果没有该工具，需要从 ncnn 源码构建工具。在本次测试环境中，源码位于 `/tmp/ncnn`。
> 生产使用的已转换版本位于 `bin/ocr_models/ncnn`；`test/ncnn_models` 仅保留早期实验产物。
```bash
rtk cmake -S /tmp/ncnn -B /tmp/ncnn/build-tools -G Ninja \
  -DNCNN_BUILD_TOOLS=ON \
  -DNCNN_BUILD_EXAMPLES=OFF \
  -DNCNN_BUILD_BENCHMARK=OFF \
  -DNCNN_BUILD_TESTS=OFF \
  -DNCNN_VULKAN=OFF \
  -DNCNN_PYTHON=OFF

rtk cmake --build /tmp/ncnn/build-tools --target onnx2ncnn ncnnoptimize
```

构建完成后应能找到：

```bash
/tmp/ncnn/build-tools/tools/onnx/onnx2ncnn
/tmp/ncnn/build-tools/tools/ncnnoptimize
```

## 模型转换

将项目内置的 ONNX 识别模型转换为 ncnn param/bin：

```bash
rtk .venv/bin/python test/ncnn_ocr_benchmark.py \
  --convert \
  --convert-only \
  --ncnn-model-dir bin/ocr_models/ncnn \
  --onnx2ncnn /tmp/ncnn/build-tools/tools/onnx/onnx2ncnn \
  --ncnnoptimize /tmp/ncnn/build-tools/tools/ncnnoptimize \
  --models en cn jp tw
```

脚本转换流程：

- 使用固定输入形状 `[1, 3, 48, 320]` 简化 ONNX。
- 使用 `onnx2ncnn` 转换。
- 修补 `onnx2ncnn` 无法正确表达的 AzurPilot OCR attention 子图。
- EN/CN 使用 `ncnnoptimize` 后再修补；JP/TW 的 raw 图需要先修补动态 slice/attention，且当前直接落盘 raw-patched 图，避免 `ncnnoptimize` 破坏输入 blob。

目前仓库只内置 EN/CN 的验证集。JP/TW 可通过 `--convert-only` 完成转换，并用生产 `NcnnRecOCR` 做加载/推理 smoke test。

## 测试指令

运行所有本机可用后端：

```bash
rtk .venv/bin/python test/ncnn_ocr_benchmark.py \
  --backend all \
  --ncnn-model-dir bin/ocr_models/ncnn \
  --models en cn \
  --count 100 \
  --warmup 5
```

指定 Vulkan GPU。我的测试机中，`GPU1` 是独显：

```bash
rtk vulkaninfo --summary

rtk .venv/bin/python test/ncnn_ocr_benchmark.py \
  --backend ncnn-vulkan \
  --ncnn-model-dir bin/ocr_models/ncnn \
  --gpu-index 1 \
  --models en cn \
  --count 100 \
  --warmup 5
```

只测试 ncnn CPU：

```bash
rtk .venv/bin/python test/ncnn_ocr_benchmark.py \
  --backend ncnn-cpu \
  --ncnn-model-dir bin/ocr_models/ncnn \
  --models en cn \
  --count 100 \
  --warmup 5
```

只测试当前 RapidOCR / ONNX Runtime 路径：

```bash
rtk .venv/bin/python test/ncnn_ocr_benchmark.py \
  --backend onnx-cpu \
  --ncnn-model-dir bin/ocr_models/ncnn \
  --models en cn \
  --count 100 \
  --warmup 5
```

注意：脚本中的 `onnx-cpu` 表示迁移前的 RapidOCR / ONNX Runtime baseline，仅用于实验对照；生产单行识别不再回退到该路径。

## 当前准确率安全默认值

当前默认值以准确率优先：

```bash
--output-name auto
--ncnn-fp16 model
```

`--output-name auto` 会按模型选择最终 softmax 前的 logits：EN/CN 使用 `Add.227`，JP/TW 使用 `Add.223`。CTC 解码只依赖 argmax，softmax 不改变 argmax。跳过最终 softmax 对 CN/JP/TW 很重要，因为这些模型的最终分类头有 `18385` 个类别。

`--ncnn-fp16 model` 当前含义：

- `en`：关闭 fp16，因为 RX6800S 上 fp16 曾造成少量准确率损失。
- `cn`：使用 ncnn auto fp16，因为 CN 保持 `1000/1000`，并且速度更快。
- `jp/tw`：关闭 fp16，优先保持实验分支的转换稳定性。

测试原始 post-softmax 输出：

```bash
rtk .venv/bin/python test/ncnn_ocr_benchmark.py \
  --backend ncnn-vulkan \
  --ncnn-model-dir bin/ocr_models/ncnn \
  --gpu-index 1 \
  --models cn \
  --output-name fetch_name_0
```

强制 fp32：

```bash
rtk .venv/bin/python test/ncnn_ocr_benchmark.py \
  --backend ncnn-vulkan \
  --ncnn-model-dir bin/ocr_models/ncnn \
  --gpu-index 1 \
  --models en cn \
  --ncnn-fp16 off
```

## 当前 RX6800S 测试结果

环境：

- Arch Linux(7.0.9-1-cachyos)
- Mesa RADV
- CPU AMD Ryzen 9 6900HS
- GPU AMD Radeon RX 6800S，使用 `--gpu-index 1`
- ncnn 输出 blob：`auto`，EN/CN 对应 `Add.227`
- ncnn fp16 策略：`model`

当前本机结果：

| 后端 | 模型 | 准确率 | 平均 ms | P95 ms | IPS | Watts | mJ/inf |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| onnx-cpu | en | 1000/1000 | 9.279 | 10.633 | 107.8 | 55.69 | 516.77 |
| ncnn-cpu | en | 1000/1000 | 9.153 | 10.293 | 109.3 | 51.60 | 472.24 |
| ncnn-vulkan | en | 1000/1000 | 6.154 | 8.599 | 162.5 | 60.23 | 370.69 |
| onnx-cpu | cn | 1000/1000 | 11.196 | 14.485 | 89.3 | 54.90 | 614.69 |
| ncnn-cpu | cn | 1000/1000 | 12.307 | 16.307 | 81.3 | 50.79 | 625.12 |
| ncnn-vulkan | cn | 1000/1000 | 10.819 | 12.625 | 92.4 | 72.68 | 786.32 |

初步解读：

- EN 在 Vulkan 上延迟和能耗都明显受益。
- CN 在跳过 softmax 并使用模型级 fp16 策略后，Vulkan 已经快于 CPU，但这台机器上测得功耗更高，其可能受到部分其他进程影响，仅供参考
- CN 的最终分类头很大，GPU->CPU 输出回传和最终 head 成本很关键。继续优化 CN 的方向很可能是 GPU 侧 CTC argmax/top1，而不是把完整 `(40, 18385)` logits 张量回传到 CPU。

## 结果回填模板

期望好心人填写以下信息，以评估当前变更是否应该推进

| 字段 | 内容 |
| --- | --- |
| OS | 例如 Windows 11 / Arch Linux / macOS |
| CPU | |
| GPU / 加速器 | |
| 驱动 | 例如 NVIDIA driver、Mesa RADV、AMDVLK、DirectML、CoreML |
| 测试命令 | |
| `--gpu-index` | |
| `--ncnn-fp16` | |
| `--output-name` | |
| EN/CN 准确率 | |
| EN/CN 平均延迟 | |
| EN/CN P95 延迟 | |
| 功耗/能耗测量方式 | sysfs / powermetrics / 厂商工具 / 插座功率计 |
| 备注 | 温度状态、电源模式、是否插电、是否有其他负载 |

有 Vulkan 的协作者建议先运行：

```bash
rtk .venv/bin/python test/ncnn_ocr_benchmark.py \
  --backend all \
  --ncnn-model-dir bin/ocr_models/ncnn \
  --models en cn \
  --count 100 \
  --warmup 5 \
  --gpu-index <GPU_INDEX>
```

`test/ncnn_ocr_benchmark.json` 是机器可读结果产物，可以直接回传。

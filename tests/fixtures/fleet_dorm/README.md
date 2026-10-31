# 换船休息离线截图

来源：用户在本次功能请求中提供的国服 1280×720 原始截图。

- `picker_selected.png`：`MuMu12-20261031-124333.png`；六艘已选，顶部容量等账号相关区域已遮黑。
- `picker_scrolled.png`：`MuMu12-20261031-124425.png`；滚动后的第 4 舰队三艘先锋，顶部已遮黑。
- `vanguard_top_slow.png` / `vanguard_row_slow.png`：`MuMu12-20261031-151041.png` / `MuMu12-20261031-151045.png`；顶部已选一艘第 1 舰队先锋，轻移一排后另两艘可见，顶部账号区域已遮黑。
- `picker_partial_last.png`：`MuMu12-20261031-185236.png`；已选5/6，长蛇号已选中，最后一艘仅露出部分卡片。顶部账号区域已遮黑，用于复现旧阈值漏认选中状态、阻塞继续滚动的问题。
- `training.png` / `rest.png`：`MuMu12-20261031-124243.png` / `MuMu12-20261031-124246.png`；仅保留页签、数量与关闭按钮，其他区域全部遮黑。
- `training_handoff.png`：`MuMu12-20261031-210104.png`，保留原生训练面板，顶部账号区域遮黑；复现目标为二楼休息、画面仍在训练时，选船入口需要切换页签后继续的问题。
- `exp_popup.png`：`MuMu12-20261031-211506.png`，仅保留经验结算确认按钮附近原生像素，其余遮黑；验证复用喂食的`DORM_INFO`模板并继续换船。
- `picker_overlap_selected.png` / `picker_overlap_cleared.png`：`MuMu12-20261031-212209.png` / `codex-clipboard-a3070042-18f3-48d5-a5ec-0055d9301d66.png`，顶部账号区域已遮黑。长蛇号在滚动重叠行中从已选中变为未选中、数量5/6变为4/6；用于验证文字平滑及跨滚动卡面核对，后续应选择水星号。

按钮素材由同批截图通过 `dev_tools.button_region_editor` 提取，运行 `dev_tools.button_extract` 生成。
识别测试使用项目引擎和显式 CPU OCR 配置；不连接模拟器，不读写真实账号配置。

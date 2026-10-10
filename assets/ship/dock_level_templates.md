# 船坞等级模板

`dock_level_prefix.png` 和 `dock_level_digits.png` 来自国服 1280×720 实机船坞截图。
复用 `StorageAmountGlyphs` 的原生灰度画布、误差与候选差距门槛，独立保存船坞字体，
不修改仓库数量、舰队管理或其共享识别器。

`dock_fleet_label.png` 从 `mind_dock_fleet_priority.png` 第一张卡片提取“编队”文字，
只用于编号不确定时确认确有编队标记。蓝色背景本身不作为编队证据。
`mind_fleet_blue.png` 保留实机误判的三个蓝卡区域，用于防止早停条件被错误阻断。

`tests/fixtures/mind_levels.png` 仅保留等级区域，无账号信息。每格 64×32，七列三行组成一页。
`mind_levels.json` 记录人工逐格核实的等级、原截图尺寸、行位置和 SHA-256。
页 1、2、3、10、20、60 用于模板提取，页 40 留作独立验证，不参与提取。
裁剪坐标相对于现有 `CARD_GRIDS` 卡片左上角为 `(74, 0, 138, 32)`。

修改标签或增加样本后运行：

```powershell
uv run python -m dev_tools.mind_level_extract
```

保留原生抗锯齿，不按二值包围盒缩放数字。Lv 灰度锚点决定数字区域和位数；
完整数字不能严格匹配时，使用现有数字 OCR 对原色、白字和放大图交叉核对。
至少两次读数一致、位数相符且无同位数冲突才接受。不能确认时重新截图，不能猜补百位或导入 0 级。

名称回归样本为 `tests/fixtures/mind_names.png`，每格 152×30，裁剪区域沿用舰队扫描器
相对于卡片的 `(-10, 160, 142, 190)`；预处理直接复用其 19 像素文字行。
`mind_names.json` 记录人工核实名称、原截图 SHA-256 与坐标，仅用于回归，不训练模糊名称匹配。

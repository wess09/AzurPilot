# 船坞编队文字的原生灰度模板

`dock_fleet_label_gray.png` 来自国服 1280×720 船坞卡片的“编队”文字，裁取编号下方的两字，使用 `extract_white_letters(threshold=96)` 保留抗锯齿，原生尺寸 29×15，不缩放。

用途是给编号模板追加文字证据，避免立绘细线偶然命中数字 1。与已有二值文字模板并用，匹配门槛仍为 0.75；文字与数字都确认才返回编队编号。原生多相位与立绘反例分别由 `tests.test_mind_scan_stuck` 和 `mind_low_native_phase.png` 覆盖。

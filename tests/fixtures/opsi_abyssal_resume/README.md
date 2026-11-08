这些夹具来自用户提供的国服 MuMu 1280×720 截图。使用项目的
`dev_tools.button_region_editor.process_button_image()` 将顶部资源栏和左侧舰船栏置黑，
保留地图、雷达、舰队编号、深渊目标和退出入口。士气提示同样保留原始像素，不缩放。

- `stage1.png`、`stage2.png`：第一、第二阶段入口问号。
- `boss.png`：Boss 已出现，当前舰队仍可自由移动。
- `engaged.png`：正在与 Boss 交战，显示行动中和脱离。
- `withdrawn.png`：脱离后 Boss 位于当前舰队后方。
- `damaged.png`：受损舰队仍处于行动中。
- `low_resolve.png`：无法与强敌战斗的士气提示。

识别资源 `ABYSSAL_MAP_CHECK` 取自第一阶段右侧任务目标，`ABYSSAL_LOW_RESOLVE`
取自士气提示首行；`ABYSSAL_STAGE_2` 取自第二阶段黄色封锁格，关闭按钮复用
`LEAVE_OS_POPUP_CLOSE`。测试不连接真实设备。

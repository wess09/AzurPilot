# 自选轻量复刻登录截图

`select.png` 是用户提供的 1280×720 原始游戏报错截图，画面为自选轻量复刻活动选择页；未缩放、未添加标注，无账号信息。

- `assets/cn/ui/CAPSULE_RERUN_CHECK.png` 使用原图右下角 `CAPSULE RERUN` 标识，不包含活动卡片、收藏数量或日期。
- 返回按钮复用 `BACK_ARROW_WHITE`，无需新增返回键或主页键资源。
- `tests/test_capsule_rerun_login.py` 通过正式 `appear()`、主界面弹窗链和登录状态循环回放；主界面确认使用既有两种主题的资源像素构造画面，时间由虚拟时钟推进。
- 这些检查属于离线回放，不代表真实模拟器验收。

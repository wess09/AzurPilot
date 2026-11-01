# 游戏设置与 PlayerPrefs

> 在启动游戏前，以白名单和可恢复的文件替换流程应用推荐设置。

## 1. 模块概述

游戏设置有两条不同用途的链路：运行时修改 Android PlayerPrefs，以及开发时从 Lua 源码提取设置目录。运行时写入规则集中在 `player_prefs.py`，并不直接采用提取器生成的全部字段。

## 2. 模块职责

### 负责

- 校验目标包、进程状态、访问权限与 PlayerPrefs 文件。
- 更新白名单键，保留其他设置的语义，校验写入结果并在失败时恢复。
- 提供离线 XML 转换与 Lua 设置提取工具。

### 不负责

- 在游戏运行期间强制修改设置，或批量应用所有提取出来的字段。
- 用户任务 JSON 的配置生成与迁移。

## 3. 模块位置

| 源码 | 职责 |
| --- | --- |
| [player_prefs.py](../../../module/game_setting/player_prefs.py) | 白名单、XML 转换、设备访问与写入事务 |
| [setting_extractor.py](../../../module/game_setting/setting_extractor.py) | 解析 Lua 中的 `PlayerPrefs.Get*` 调用 |
| [setting_generated.py](../../../module/game_setting/setting_generated.py) | 提取器生成的设置目录 |
| [channel_float.py](../../../module/game_setting/channel_float.py) | 关闭并锁定应用宝渠道服 YSDK 悬浮球开关 |
| [device.py](../../../module/device/device.py) | 启动游戏前调用运行时入口 |

## 4. 核心入口

`Device.app_start()` 在 `Emulator_GameSettings` 开启时调用 `apply_recommended_game_settings()`，随后启动游戏。配置路径为 `Alas.Emulator.GameSettings`。重启流程可通过 `wait_for_stop` 允许短暂等待进程退出。

`Emulator_DisableChannelFloat` 开启时，同一位置随后调用 `disable_channel_float()`，两者共用重启时的 `wait_for_stop`。

离线入口 `update_player_prefs_xml(content)` 接收字节串并返回新 XML 与 `PlayerPrefsChanges`，不需要创建 `Device`。

## 5. 核心组件

| 组件 | 作用 |
| --- | --- |
| `PlayerPrefsManager` | 设备端校验、写入、验证与回滚 |
| `PlayerPrefsMetadata` | 保存 UID、GID、权限及 SELinux 信息 |
| `PlayerPrefsChanges` | 记录更新数量和已发现的动态键 |
| `verify_player_prefs_xml()` | 验证目标设置，而非将整个 XML 当作任意键值字典覆盖 |

## 6. 工作流程

1. HTTP 设备直接跳过；以设备串号与包名取得跨进程文件锁。
2. 确认目标包及其子进程已经停止，准备 root 访问；无法确定停止状态也不写入。
3. 定位唯一的 `.v2.playerprefs.xml`，检查 Android 原子写入备份 `.bak`，读取文件内容与元数据。
4. 在内存中生成白名单修改。没有变化便返回成功。
5. 再次确认停机，将结果写到同目录随机临时文件，恢复元数据并回读比较。
6. 替换前再次检查停机，再以移动临时文件的方式替换目标，验证设置及元数据。
7. 替换后失败则尝试用内存中的原文件执行同样的恢复流程；退出时清理本次临时文件，并恢复本次临时改变的 adbd root 状态。

这套流程会多次检查进程状态，以缩小游戏重新启动后覆盖文件的窗口；进程检查与文件移动不是系统级联合事务。

### 渠道服悬浮球（YSDK）

`ChannelFloatManager` 继承 `PlayerPrefsManager`，复用跨进程锁、停机检查、root 准备、元数据与临时文件替换，只在包名属于 `YSDK_PACKAGES`（目前为腾讯应用宝渠道服）时运行，其他包名直接跳过且不尝试提权。

- 机制：YSDK 的 `IconModule.init()` 在进程启动时读取一次 `YSDK_ICON_SWITCH`，为 `false` 时不注册登录回调，悬浮球不会创建。读取顺序是云配置 `shared_prefs/YSDK_CONFIG*.xml`，然后才是 APK 内 `ysdkconf.ini`。
- 每次登录 SDK 会清空云配置并写回服务器值 `true`，所以写入 `false` 后用 `chattr +i` 锁定 `YSDK_CONFIG.xml`。之后 SDK 的写盘会失败（logcat 出现 `Couldn't rename ... to backup file`），服务器值只留在本进程内存，不影响登录。
- 已锁定且为 `false` 时不写入；文件不存在（首次安装未登录）时跳过，下次启动再处理；写入失败时保持原状，不阻止启动。
- 关闭配置项不会解锁。恢复悬浮球需要 root 执行 `chattr -i` 并删除该文件，下次登录 SDK 会重建。
- 验证：logcat 出现 `YSDK ICON: icon is closed_init`，`dumpsys window` 不再有 `Panel:<包名>/...MainActivity` 子窗口。

4399 等其他渠道服使用不同 SDK，仍由 [handler](../handler.md) 的 `channel_float` 以截图拖拽处理。

## 8. 数据流

原 XML 通过 ADB 读取为内存字节串，不将完整原文件备份到主机磁盘。临时文件放在设备端目标文件所在目录，以便在替换时保持文件系统边界一致。

XML 序列化可能改变格式；“保留其他设置”指保留其语义，不代表输出文件逐字节不变。

## 10. 配置与白名单

| 键或规则 | 目标值 |
| --- | --- |
| `fps_limit` | `60` |
| `world_flag_story_tips`、`world_flag_consume_item`、`story_autoplay_flag` | `1` |
| `world_flag_auto_save_area`、`display_ship_get_effect`、`QUICK_CHANGE_EQUIP` | `0` |
| `BATTLERESULT_DISPAY_PAINTING`、`world_sub_auto_call` | `0` |
| `_WorldBossProgressTipFlag_` | 空字符串 |
| 已存在的 `story_speed_flag[0-9]+` | `9` |
| 已存在的 `STANDBY_MODE_KEY_[0-9]+` | `0` |

静态键可补建；带玩家标识的动态键只修改已存在的匹配项，不猜测标识，也不创建没有标识的替代键。目标键重复、类型不符或根节点不是 `map` 时拒绝转换。

## 11. 异常与错误处理

- `PlayerPrefsUnsupported`：条件不满足，记录跳过并返回 `False`。
- 替换前发生写入错误：保留原文件；替换后发生错误：先恢复原文件。
- 恢复失败：抛出 `RequestHumanTakeover`，阻止正常进入后续启动流程。
- 已存在 Android `.bak` 时拒绝接管，不把它当作本模块遗留文件清理。

`False` 表示未应用，不一定是致命错误；上层仍可继续启动游戏。不能把回滚失败同样降级成普通跳过。

## 12. 并发与线程模型

锁文件位于 `cache/`，名字由串号与包名散列生成；Windows 和 POSIX 使用各自的文件锁实现。锁约束同一目标的本模块写入，不控制游戏自身或其他外部工具。

## 15. 扩展方式

新增运行时设置时，同步更新白名单、类型校验、验证函数与对应测试。带账号后缀的键沿用“仅更新已存在键”的规则。

Lua 提取器使用 `SettingExtractor.generate(folder, output=...)`；`folder` 必须指向准备好的 Lua 源码目录。文件中的直接运行示例目录为空，需要先指定输入，不能作为一条开箱即用的生成命令。提取结果用于理解设置，不自动扩大运行时写入范围。

## 18. 离线示例

```python
from module.game_setting.player_prefs import update_player_prefs_xml

source = b'<map><int name="fps_limit" value="30" /></map>'
updated, changes = update_player_prefs_xml(source)
assert changes.changed
_, second_changes = update_player_prefs_xml(updated)
assert not second_changes.changed
```

## 19. 调试方法

从仓库根运行 `uv run python -m unittest tests.test_game_setting_player_prefs`。该模块使用内存 XML 和模拟设备调用验证白名单、类型拒绝、回滚及 root 回退；通过这些测试不代表已验证某款模拟器的权限与 SELinux 行为。

设备问题按停机判断、root 获取、目标文件、元数据、替换验证、回滚顺序定位。日志不应打印完整 PlayerPrefs 或包含账号信息的设备命令输出。

## 20. 相关模块

- [设备层](../device.md)
- [配置系统](../config.md)
- [测试与验证](../infra/testing.md)

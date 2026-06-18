
# AzurPilot

<p align="center">
  <img src="doc/logo.webp" alt="AzurPilot Logo" width="400">
</p>

<p align="center">
  <a href="https://deepwiki.com/wess09/AzurPilot">
    <img src="https://deepwiki.com/badge.svg" alt="DeepWiki" height="22">
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/github/license/wess09/AzurPilot?style=flat-square&label=License&color=2ea44f" alt="License">
  <img src="https://img.shields.io/github/stars/wess09/AzurPilot?style=flat-square&label=Stars&color=ffcc00" alt="Stars">
  <img src="https://img.shields.io/github/forks/wess09/AzurPilot?style=flat-square&label=Forks&color=58a6ff" alt="Forks">
  <img src="https://img.shields.io/github/issues/wess09/AzurPilot?style=flat-square&label=Issues&color=f85149" alt="Issues">
</p>

<p align="center">
  <img src="https://img.shields.io/github/last-commit/wess09/AzurPilot?style=flat-square&label=Last%20Commit&color=8b949e" alt="Last Commit">
  <img src="https://img.shields.io/github/commit-activity/m/wess09/AzurPilot?style=flat-square&label=Commit%20Activity&color=8957e5" alt="Commit Activity">
  <img src="https://img.shields.io/github/repo-size/wess09/AzurPilot?style=flat-square&label=Repo%20Size&color=orange" alt="Repo Size">
  <img src="https://img.shields.io/github/languages/top/wess09/AzurPilot?style=flat-square&label=Top%20Language&color=3776AB" alt="Top Language">
</p>

<p align="center">
  <img src="https://img.shields.io/github/contributors/wess09/AzurPilot?style=flat-square&label=Contributors&color=00b4d8" alt="Contributors">
  <img src="https://img.shields.io/github/issues-pr/wess09/AzurPilot?style=flat-square&label=Pull%20Requests&color=ffb703" alt="Pull Requests">
  <img src="https://img.shields.io/github/issues-pr-closed/wess09/AzurPilot?style=flat-square&label=PRs%20Closed&color=2ea44f" alt="Closed Pull Requests">
</p>

## 项目简介

AzurPilot 是基于 AzurLaneAutoScript 修改而来的碧蓝航线自动化辅助项目，保留原项目的核心能力，并在此基础上整合了多个分支、功能改进和实验性特性。

本项目代码基本由 AI 代码生成与辅助编写，存在较大的不确定性，欢迎提交 [Pull Request](https://github.com/wess09/AzurPilot/pulls) 改正。

项目原始来源与相关分支：

- LmeSzinc/AzurLaneAutoScript 原项目及其生态分支 @LmeSzinc
- yukikaze21/AzurLaneAutoScriptyukikaze21 大世界部分功能 @yukikaze21
- Zuosizhu/Alas-with-Dashboard 的仪表盘 @Zuosizhu
- guoh064/AzurLaneAutoScript 大世界部分功能 @guoh064
- sui-feng-cb/AzurLaneAutoScript 岛屿计划 @sui-feng-cb
- 其他社区贡献的实用 [Pull Request](https://github.com/LmeSzinc/AzurLaneAutoScript/pulls)

<div align="center">
  <a href="https://alas.nanoda.work">
    <img src="https://img.shields.io/badge/Web-下载-blue?style=for-the-badge&logo=google-chrome&logoColor=white" />
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://addgroup.nanoda.work/#/">
    <img src="https://img.shields.io/badge/交流群-QQ-red?style=for-the-badge&logo=tencent-qq&logoColor=white" />
  </a>
</div>

## GUI
<div align="center">
  <img src="doc/GUI.png" alt="GUI Preview" width="800">
</div>

## 依赖与启动

本项目使用 `uv` 和项目根目录 `.venv` 管理 Python 运行环境。发布版启动器会自带 uv、Python、ADB、Git，并在 `.venv` 中同步依赖；源码开发时可安装 uv 后运行：

```bash
uv sync --frozen --no-dev
uv run python gui.py
```

依赖声明在 `pyproject.toml` 中，锁定结果提交在 `uv.lock`。不要再维护或生成 `requirements*.txt`。

## Termux 真机安装运行指南

> 适用于无 root 的 Android 真机，通过 Termux + proot-distro 运行 AzurPilot。

### 前置说明

| 项目 | 说明 |
|---|---|
| 环境 | 无 root、Android、Termux、proot-distro、Ubuntu |
| 工具 | ADB、SSH、Escrcpy |
| 测试安卓版本 | Android 12 / Android 14 |
| 安卓架构 | `android_24_arm64_v8a` |

**关键注意事项：**

- 登录 Ubuntu 后**必须修改时区为国内**，否则更新和部分包安装会出问题
- 所有操作都需要换源到国内镜像
- 调试时**必须通过 ADB 配对**
- 确认 Ubuntu 环境为标准 Linux (manylinux)
- **必须安装轻量桌面**，否则无法运行
- 获取文件权限，否则中间会因路径异常出现问题

### ADB 指令速查

| 操作 | 指令 |
|---|---|
| 配对 | `adb pair ip:port` |
| 连接 | `adb connect ip` |
| 验证 | `adb devices` |
| 调整分辨率 | `adb shell wm size 720x1280` |
| 重置分辨率 | `adb shell wm size reset` |
| 查看默认 DPI | `adb shell wm density` |
| 调整 DPI | `adb shell wm density 480` |
| 打开碧蓝航线 | `adb shell am start -n com.bilibili.azurlane/com.manjuu.azurlane.MainActivity` |
| 关闭碧蓝航线 | `adb shell am force-stop com.bilibili.azurlane` |

### 常用指令速查

| 操作 | 指令 |
|---|---|
| 登录 Ubuntu | `proot-distro login ubuntu` |
| 获取文件权限 | `termux-setup-storage` |
| 切换目录 | `cd` |
| 更新包 | `pkg update -y && pkg upgrade -y` |
| SSH 连接 | `ssh u0_xxxx@192.168.1.23 -p 8022` |
| 查看用户 | `whoami` |

### 安装步骤

#### 1. 下载 Termux 和 Escrcpy

1. **Termux**：手机模拟 Linux 环境 — [GitHub](https://github.com/termux/termux-app#uninstallation)
2. **Escrcpy**：局域网条件下电脑操作手机 — [GitHub Releases](https://github.com/viarotel-org/escrcpy/releases)
   - 根据自己的电脑操作系统选择对应版本
   - 推荐选择 2.10.2 的 `win-setup-x64.exe`，或选择自己对应的版本

#### 2. 准备环境

1. 手机与电脑连接**同一网络**
2. 打开手机**无线调试**，记住 **IP 地址**后续要用
3. 打开 Escrcpy 的终端与手机配对，否则断开后需要重新连接
   ```bash
   # 配对
   adb pair 192.168.1.23:37453
   # 连接
   adb connect 192.168.1.23
   # 验证
   adb devices
   ```
4. 成功后出现手机画面

#### 3. Termux 准备工作

1. 使用 **Escrcpy** 的内嵌镜像打开真机
2. 使用 **Escrcpy** 安装 **Termux**
3. 打开 Termux，检查架构是否为 `arm64_v8a`
4. 将 Termux 设置为：不会被杀后台、允许悬浮窗、允许文件权限
5. 打开 Termux，换源并更新：
   ```bash
   # 输入后选择清华源 (Tsinghua)，等待更新
   termux-change-repo

   # 更新包
   pkg update && pkg upgrade
   # 出现选项全部默认，电脑直接回车
   ```
6. 安装基础工具包：
   ```bash
   pkg install termux-tools termux-api
   ```
   - 这是为了补全一些环境，等待更新完成

#### 4. SSH 准备工作

1. 安装 openssh 方便操作：
   ```bash
   pkg install openssh -y
   ```
2. 设置密码并启动 SSH 服务：
   ```bash
   passwd          # 输入密码两次，设置简单自己能记住的
   sshd            # 启动服务
   whoami          # 出现的 u0_xxxx 就是用户名
   ```
3. 电脑打开 **CMD**，连接 SSH：
   ```bash
   ssh u0_a356@192.168.1.23 -p 8022
   ```
   - 将 `u0_a356` 换成自己的**用户名**
   - 将 `192.168.1.23` 换成自己的**IP**（无线调试页面显示过，遗忘则打开手机查看）
4. 第一次连接会提示输入 `yes`，然后输入自己设置的密码
5. 如果出现 `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!`，需要清除旧缓存：
   ```bash
   ssh-keygen -R "[192.168.1.23]:8022"
   ```
6. SSH 连接成功后会弹出 Termux 的初始页面
   - 可以设置自动启动 SSH，这样就不会每次打开都要运行 `sshd`
7. 安装 ADB 工具：
   ```bash
   pkg install android-tools
   ```
8. 将 Termux 与本机连接配对：
   ```bash
   # 配对（将 37833 换成正确的端口）
   adb pair 127.0.0.1:37833
   # 输入配对码

   # 连接本机（将 5555 换成无线调试页面第一行的端口）
   adb connect 127.0.0.1:5555
   ```
9. 成功后会出现 Termux 的用户，测试 ADB 打开/关闭碧蓝航线：
   ```bash
   # 打开碧蓝航线
   adb shell am start -n com.bilibili.azurlane/com.manjuu.azurlane.MainActivity
   # 关闭碧蓝航线
   adb shell am force-stop com.bilibili.azurlane
   ```

#### 5. proot-distro 准备工作

1. 安装 proot-distro：
   ```bash
   pkg install proot-distro
   ```
2. 安装 Ubuntu 系统（使用清华源，避免网络问题）：
   ```bash
   proot-distro install -n ubuntu https://mirrors.tuna.tsinghua.edu.cn/ubuntu-cdimage/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz
   ```
   - 出现 `proot-distro login ubuntu` 说明 Ubuntu 安装成功
3. 获取真机文件权限（手机会有弹窗，必须同意）：
   ```bash
   termux-setup-storage
   ```

#### 6. 登录 Ubuntu 并换源

1. 登录 Ubuntu：
   ```bash
   proot-distro login ubuntu
   ```
   - 成功登录会出现 `root` 用户
2. 更新工具包：
   ```bash
   apt update
   ```
3. 安装 nano 并更换清华源：
   ```bash
   apt install -y ca-certificates nano
   ```
4. 编辑软件源文件：
   ```bash
   nano /etc/apt/sources.list.d/ubuntu.sources
   ```
   - 多次按 `Ctrl+K` 直到全部删完
   - 复制以下内容到文件中，然后按 `Ctrl+X` → `Y` → `回车` 保存：

   ```
   Types: deb
   URIs: https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/
   Suites: noble noble-updates noble-backports
   Components: main restricted universe multiverse
   Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

   Types: deb
   URIs: https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/
   Suites: noble-security
   Components: main restricted universe multiverse
   Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
   ```

#### 7. Ubuntu 更换时区

1. 安装时区工具：
   ```bash
   apt update && apt install tzdata
   ```
2. 设置时区：
   ```bash
   tzselect
   ```
   - 假设有 `more` 就按回车
   - 提示选择时按 4、11、1、1，选择正确的国内时区
3. 验证时区：
   ```bash
   date
   ```
   - 与电脑时间一致就是正确
4. 更新软件包：
   ```bash
   apt update
   ```

#### 8. 安装必备软件包

```bash
apt install -y build-essential python3-dev curl git wget cmake clang
```

等待安装完毕，如果有选择直接回车选择默认。

#### 9. 安装 uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
uv --version    # 提示版本号即成功
```

#### 10. 安装轻量桌面

安装轻量桌面是为了让 AP 能正确运行，有些软件包需要用到桌面，否则会直接报错。

```bash
apt install -y lxde-core lxterminal tigervnc-standalone-server
```

- 安装过程中出现交互，如果是 `more` 按回车下一步
- 记下选择 `china`、`chinese` 的编号
- 出现 `keyboard` 的时候输入 `20`、`1`（默认选择中文）

#### 11. 克隆项目

1. 打开 [https://gh-proxy.com/](https://gh-proxy.com/) 下载代理源项目
2. 将 `https://github.com/wess09/AzurPilot.git` 复制到页面的输入框
3. 点击 **git clone** 获取最新的链接
4. 用最新的链接替换下面的 `url`：
   ```bash
   git clone --depth 1 <url>
   ```
5. 等待下载完毕

#### 12. 编译项目

```bash
ls                  # 查看目录，AzurPilot 会以特殊颜色显示
cd AzurPilot        # 进入项目目录
uv sync --frozen --no-dev   # 编译
```

#### 13. Ubuntu 创建密钥

创建密钥是为了让 AP 能够打开碧蓝航线，公钥密钥为 PEM 格式。

```bash
cd                          # 回到根目录
apt install openssl libssl-dev

# 生成 RSA 私钥（PEM 格式）
openssl genrsa -out private_key.pem 2048

# 从私钥生成 RSA 公钥
openssl rsa -in private_key.pem -RSAPublicKey_out -out public_key.pem

# 查看公钥
cat public_key.pem
```

将输出的完整公钥复制到 AP 中，格式如下：

```
-----BEGIN RSA PUBLIC KEY-----
MIIBCgKCAQEAuCzcbDBfniG+LWOTr5xFirnxjkD+6WKAAOwmRlepSgKHIdF8t9pc
s61KBmDlxnQssUwbCQZCeDX65s/pclZrGhz5Wt0MG2Y294sTiyAC6xvgbLqeh5at
...
-----END RSA PUBLIC KEY-----
```

#### 14. 运行项目

1. 检查是否处于 Ubuntu 的模拟 root 环境：
   - 如果使用 **CMD + SSH** 方式：手机处于 Termux 界面，需要登录到 Ubuntu：
     ```bash
     proot-distro login ubuntu
     ```
   - 如果使用 **Escrcpy + Termux** 方式：手机已经处于 Ubuntu，无需登录

2. 进入项目目录并运行：
   ```bash
   cd AzurPilot
   uv run python gui.py
   ```

3. 等待页面初始化完毕，浏览器提前打开 `http://手机IP:22267`
   - 出现 `success`
   - 出现 `0.0.0.0:22267`
   - 页面无报错
   - 浏览器出现初始化页面说明项目安装完成

#### 15. 配置模拟器设置

点击 **智慧港区 → 模拟器设置**，按以下配置：

| 配置项 | 值 | 说明 |
|---|---|---|
| 模拟器 Serial | `127.0.0.1:5555` | 端口换成真机的调试端口 |
| 模拟器截图方案 | `ADB_NC` | |
| 模拟器控制方案 | `ADB` | |
| 模拟器类型 | `SSH` | |
| 远程服务器地址 | 真机的 IP | 禁止填 `127.0.0.1` 或 `localhost`（指向 Ubuntu 内部） |
| 端口号 | `8022` | |
| 用户名 | Termux 的 `u0_xxxx` | |
| SSH 公钥 | Ubuntu 创建的公钥 | 不是演示公钥 |
| 远程启动指令 | 见下方 | |
| 远程停止指令 | 见下方 | |
| OCR 设备 | `CPU` | |

远程启动/停止指令（将 `40347` 改为自己的真机调试端口）：

```bash
# 远程启动指令
adb -s 127.0.0.1:40347 shell am start -n com.bilibili.azurlane/com.manjuu.azurlane.MainActivity

# 远程停止指令
adb -s 127.0.0.1:40347 shell am force-stop com.bilibili.azurlane
```

> **提示**：工具里的模拟器管理器与这里的配置是一致的。

#### 16. 调整分辨率

使用 CMD 窗口连接 SSH，调整手机分辨率：

```bash
adb shell wm size 720x1280
adb shell wm density 320   # 从 180-600 之间调整，直到屏幕效果满意
```

重置分辨率和像素比到默认值：

```bash
adb shell wm size reset
adb shell wm density reset
```

> 如果 `adb shell wm density reset` 无效，先执行 `adb shell wm density` 查看 `Physical density` 的初始值，再执行 `adb shell wm density <初始值>` 还原。

#### 17. 完成

启动**性能测试**和 **OCR 测试**，AP 会安装 ATX 和工具包来辅助控制碧蓝航线，过程中会有安装提示。

**到此所有调试完毕，可以正常设置 AP 并启动。**

## 重要说明

本项目包含大量自动化逻辑和图像识别相关功能。使用前请确保已经按照本文档完成游戏内设置，否则可能导致识别失败、流程异常或任务无法正常执行。

本项目包含部分实验性功能，可能存在未知问题。建议在使用前备份相关配置，并在发现异常时及时反馈。

## 使用前设置

使用前必须按照以下标准修改游戏内设置。

路径：

主界面，右下角设置，左侧边栏选项。

| 设置名称 | 推荐值 |
| --- | --- |
| 帧数设置 | 60 帧 |
| 大型作战设置，减少 TB 引导 | 开 |
| 大型作战设置，自律时自动提交道具 | 开 |
| 大型作战设置，安全海域默认开启自律 | 关 |
| 剧情自动播放 | 开启 |
| 剧情自动播放速度调整 | 特快 |
| 待机模式设置，启用待机模式 | 关 |
| 其他设置，重复角色获得提示 | 关 |
| 其他设置，快速更换二次确认界面 | 关 |
| 其他设置，展示结算角色 | 关 |

### 大型作战设置

路径：

大型作战，右上角雷达，指令模块，潜艇支援。

| 设置名称 | 推荐值 |
| --- | --- |
| X 消耗时潜艇出击 | 取消勾选 |

### 一键退役设置

路径：

主界面，右下角建造，左侧边栏退役，左侧齿轮图标，一键退役设置。

| 设置名称 | 推荐值 |
| --- | --- |
| 选择优先级 1 | R |
| 选择优先级 2 | SR |
| 选择优先级 3 | N |
| 拥有满星的同名舰船时，保留几艘符合退役条件的同名舰船 | 不保留 |
| 没有满星的同名舰船时，保留几艘符合退役条件的同名舰船 | 满星所需或不保留 |

### 图像识别注意事项

请移除以下可能影响识别的内容：

- 角色设备装备
- 角色皮肤
- 可能遮挡界面元素的自定义显示内容

这些内容可能影响图像识别结果，导致自动化流程出现异常。

## 主要改动

本分支在原项目基础上加入或整合了以下内容：

1. 岛屿计划自动化
2. 共斗沉船（牺牲指定位置舰船）
3. 大世界智能调度（自动切换侵蚀1练级与黄币补充任务）
4. 大世界蒙特卡洛模拟器（估算侵蚀循环收益）
5. 拆解装备箱（按保留数量拆白/蓝/紫箱）
6. 全新 OCR 模型
7. 共用心情（多个出击任务共享同一队心情）
8. 自定义任务优先级
9. 大世界舰队经验检测（满经验推送）
10. 侵蚀一舰队自动配队（自动更换满经验舰船）
11. 塞壬研究装置（紫币换黄币，探测资源/敌人）
12. 大世界海域成就（刷安全海域星星）
13. 定时重启模拟器
14. 远程SSH管理（执行命令如重启docker）
15. 大世界独立推送（与错误推送分离）
16. 维修箱修船（支持侵蚀1单独阈值）
17. 大世界信息推送开关（侵蚀1和短猫信息）
18. 白票商店购买战役信息记录仪/隐秘海域记录仪
19. 每月开荒进度显示
20. 演习推迟策略（至下次更新前X小时）
21. GUI仪表盘（实时显示石油、物资、魔方、大世界币等）
22. OOBE首次设置向导（选择语言、服务器、模拟器等）
23. 日志备份管理（保留数量、压缩备份）
24. LLM错误分析（调用大模型分析报错原因）
25. 游戏卡死或ADB离线时自动重启模拟器
26. 物资超过阈值停止出击
27. 道中战斗失败可撤退或换队接管
28. 困难图自动配队（使用推荐阵容）
29. 关卡名称支持“7-2-3”格式（三战后撤退）
30. 科研魔方保留阈值（低于设定值时不选魔方项目）
31. 各商店独立开关（可单独关闭军火商、舰队商店等）
32. GPU加速推理（Windows DirectML / macOS ANE / ncnn Vulkan）
33. OCR设备选择（CPU / GPU / ANE）
34. 共斗每日支持沉船模式

* 由 DeepSeek 结合项目分析生成 实际请以实物为准

## 多平台启动器

<div align="center">
  <img src="doc/loading.png" alt="loading" width="500" />
  <p>启动加载界面</p>
  <img src="doc/GUI.png" alt="GUI" width="500" />
  <p>Windows 客户端界面</p>
  <img src="doc/macGUI.png" alt="macGUI" width="500" />
  <p>Mac 客户端界面</p>
</div>
启动器项目地：

[GitHub](https://github.com/wess09/alas-launcher) 源项目 [ALAS Launcher: 一种新型的 AzurLaneAutoScript 启动器](https://github.com/swordfeng/alas-launcher)

更改内容：
1. 增加托盘化功能
2. Windows原生推送
3. GUI样式美化
4. uv化

## MCP 服务

AzurPilot 提供 MCP 服务，可供支持 MCP 的客户端或工具调用。

通过 MCP 您可以方便的使用 Agent 管理 AzurPilot

### 本地连接配置

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://127.0.0.1:22267/mcp/sse"
    }
  }
}
```

### 云服务器或内网连接配置

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://[IP_ADDRESS]/mcp/sse"
    }
  }
}
```

请将 `[IP_ADDRESS]` 替换为实际服务器地址或内网地址。

## MCP 工具列表

当前可用 MCP 工具共 18 个。

### 实例管理

| 工具名称 | 功能 |
| --- | --- |
| list_instances | 列出所有实例 |
| get_status | 获取实例状态 |
| start_instance | 启动实例 |
| stop_instance | 停止实例 |

### 任务管理

| 工具名称 | 功能 |
| --- | --- |
| list_tasks | 列出所有任务 |
| get_task_help | 获取任务帮助 |
| trigger_task | 触发任务 |
| get_scheduler_queue | 获取调度队列 |
| clear_scheduler_queue | 清空调度队列 |

### 监控与信息

| 工具名称 | 功能 |
| --- | --- |
| get_current_running_task | 获取当前运行任务 |
| get_resources | 获取资源状态 |
| get_config | 获取实例配置 |
| get_recent_logs | 获取最近日志 |
| get_screenshot | 获取截图 |

### 配置管理

| 工具名称 | 功能 |
| --- | --- |
| update_config | 更新配置 |

### 维护工具

| 工具名称 | 功能 |
| --- | --- |
| restart_emulator | 重启模拟器 |
| restart_adb | 重启 ADB |
| update_alas | 更新 AzurPilot |

## 赞助支持

<p align="center">
  <a href="https://afdian.com/a/miaonaa">
    <img src="doc/afdian.jfif" alt="爱发电" width="200">
  </a>
  <br>
  <b>支持本项目(用于支付服务器费用或训练新模型等)</b>
</p>

## OCR 模型

本项目使用基于 PaddleOCR 的定制 OCR 模型，用于适配碧蓝航线界面字体和 AzurPilot 截图场景。

感谢超算互联网提供算力支持。

相关项目：

[https://github.com/PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)

<p>
  <a href="https://arxiv.org/pdf/2507.05595">
    <img src="https://img.shields.io/badge/PaddleOCR_3.0-Technical%20Report-b31b1b.svg?logo=arXiv" alt="PaddleOCR Technical Report">
  </a>
  <img src="https://img.shields.io/badge/hardware-cpu%2C%20gpu%2C%20xpu%2C%20npu-yellow.svg" alt="Hardware">
</p>

### V1.0

| 项目 | 内容 |
| --- | --- |
| 支持语言 | zh-cn, en-us |
| 训练目标 | 针对碧蓝航线字体进行训练 |
| zh-cn 准确率 | 97% |
| en-us 准确率 | 98.6% |
| 已知问题 | zh-cn 存在边缘符号问题，en-us 可能出现负号问题 |
| 训练硬件 | 异构加速卡 BW 64G，NVIDIA Tesla A800 80G |
| 训练时间 | 2 小时 |

### V2.0

| 项目 | 内容 |
| --- | --- |
| 支持语言 | zh-cn, en-us |
| 训练目标 | 针对碧蓝航线字体与 AzurPilot 截图特性进行训练 |
| 处理方式 | 灰度化 |
| zh-cn 表现 | 相对 V1.0 准确率降低 |
| en-us 准确率 | 99.8% |
| 已知问题 | en-us 基本无明显错误 |
| 训练硬件 | NVIDIA Tesla A800 80G |
| 训练时间 | 2 小时 |

### V2.5

| 项目 | 内容 |
| --- | --- |
| 支持语言 | zh-cn |
| 训练目标 | 修复 V2.0 中文模型问题 |
| 准确率 | 98.52% |
| 推理速度 | 约 10 ms |
| 训练硬件 | 异构加速卡 BW 64G，NVIDIA Tesla A800 80G |
| 训练时间 | 5 小时 |

## 贡献者

由于本项目基于 AzurLaneAutoScript 及其社区分支继续开发，贡献者列表不仅包含本仓库的直接贡献者，也包含上游项目与相关分支中的原始贡献者。

感谢所有为 AzurPilot、原上游 AzurLaneAutoScript 及相关分支做出贡献的开发者。

<a href="https://github.com/wess09/AzurPilot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/AzurPilot&max=1000" alt="AzurPilot Contributors">
</a>

感谢所有为启动器项目做出贡献的开发者。

<a href="https://github.com/wess09/alas-launcher/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/alas-launcher&max=1000" alt="Launcher Contributors">
</a>

## 开发说明

本项目基本完全是 VibeCoding 产物 不足之处请见谅

欢迎通过 Issue 或 Pull Request 反馈问题、提交修复或改进文档。

## 使用过的开发工具与模型

本项目开发过程中使用过多种 AI 模型与开发工具进行辅助。

### AI 模型

| 模型 | 模型 | 模型 |
| --- | --- | --- |
| Gemini 3 Flash | Gemini 3.1 Pro | Claude Opus 4.5 |
| Claude Sonnet 4.5 | MiMo V2.5 Pro | GPT 5.4 |
| GPT 5.3 Codex | Qwen 3 Max | DeepSeek v4 |
| Kimi K2.5 | GLM 4.7 | MiMo V2.5 |

### 开发工具

| 工具 | 工具 | 工具 | 工具 |
| --- | --- | --- | --- |
| Claude Code | Codex | Cursor | Antigravity |

## 许可证

本项目遵循原项目及相关上游项目的许可证要求。启动器项目遵循 GPL-3.0 协议开源。

使用、修改或分发本项目时，请同时遵守相关上游项目的许可证要求。

# 🌸 屎山代码分析报告 🌸

## 📑 目录

- [糟糕指数](#overall-score)
- [评分指标详情](#metrics-details)
- [最屎代码排行榜](#problem-files)
- [诊断结论](#conclusion)

![Score](https://img.shields.io/badge/Score-89%25-brightgreen)

## 糟糕指数 {#overall-score}

| 指标摘要 | 评分 |
|------|-------|
| **糟糕指数** | **88.95/100** |
| 屎山等级 | 🌸 偶有异味 |

> 清新宜人，初闻像早晨的露珠

### 📊 统计信息

| 指标 | 数值 |
|--------|-------|
| 总文件数 | 1877 |
| 已跳过 | 16063 |
| 耗时 | 5052ms |

## 评分指标详情 {#metrics-details}

| 指标摘要 | 评分 | 状态 |
|:-----|------:|:------:|
| 循环复杂度 | 3.80% | ✓✓ |
| 认知复杂度 | 4.91% | ✓✓ |
| 嵌套深度 | 1.09% | ✓✓ |
| 函数长度 | 2.09% | ✓✓ |
| 文件长度 | 0.84% | ✓✓ |
| 参数数量 | 2.13% | ✓✓ |
| 代码重复 | 7.99% | ✓✓ |
| 结构分析 | 1.78% | ✓✓ |
| 错误处理 | 5.26% | ✓✓ |
| 注释比例 | 55.48% | • |
| 命名规范 | 4.25% | ✓✓ |

## 最屎代码排行榜 {#problem-files}

### 1. module\webui\app.py

**糟糕指数: 49.33**

**问题**: 🔄 复杂度问题: 34, ⚠️ 其他问题: 28, 🏗️ 结构问题: 22, ❌ 错误处理问题: 43, 📝 注释问题: 1, 🏷️ 命名问题: 10

- 🔄 `_render_ap_chart()` L448: 复杂度: 86
- 🔄 `_render_opsi_stats()` L1095: 复杂度: 80
- 🔄 `export_opsi_csv()` L1700: 复杂度: 30
- 🔄 `_render_ship_exp()` L1869: 复杂度: 14
- 🔄 `_render_commission_income()` L2030: 复杂度: 31
- 🔍 ...还有 130 个问题实在太屎，列不完了

### 2. mcp_server_sse.py

**糟糕指数: 48.13**

**问题**: 🔄 复杂度问题: 5, ⚠️ 其他问题: 3, 🏗️ 结构问题: 3, ❌ 错误处理问题: 4, 📝 注释问题: 1

- 🔄 `call_tool()` L202: 复杂度: 57
- 🔄 `call_tool()` L202: 认知复杂度: 71
- 🔄 `mcp_asgi_app()` L458: 认知复杂度: 18
- 🔄 `call_tool()` L202: 嵌套深度: 7
- 🔄 `mcp_asgi_app()` L458: 嵌套深度: 4
- 🔍 ...还有 9 个问题实在太屎，列不完了

### 3. module\os\map.py

**糟糕指数: 43.93**

**问题**: 🔄 复杂度问题: 37, ⚠️ 其他问题: 15, 📋 重复问题: 3, 🏗️ 结构问题: 21, ❌ 错误处理问题: 1, 📝 注释问题: 1, 🏷️ 命名问题: 7

- 🔄 `os_init()` L48: 复杂度: 18
- 🔄 `handle_storage_fleet_repair()` L406: 复杂度: 11
- 🔄 `handle_fleet_repair_by_config()` L455: 复杂度: 17
- 🔄 `os_auto_search_daemon()` L902: 复杂度: 30
- 🔄 `os_auto_search_daemon_until_combat()` L1007: 复杂度: 24
- 🔍 ...还有 77 个问题实在太屎，列不完了

### 4. module\os\tasks\hazard_leveling.py

**糟糕指数: 41.10**

**问题**: 🔄 复杂度问题: 17, ⚠️ 其他问题: 9, 📋 重复问题: 1, 🏗️ 结构问题: 6, ❌ 错误处理问题: 8, 📝 注释问题: 1, 🏷️ 命名问题: 10

- 🔄 `_cl1_smart_scheduling_check()` L43: 复杂度: 24
- 🔄 `os_check_leveling()` L408: 复杂度: 28
- 🔄 `_format_check_report()` L567: 复杂度: 14
- 🔄 `_collect_ship_data_with_retry()` L738: 复杂度: 12
- 🔄 `_check_custom_positions_full_exp()` L877: 复杂度: 12
- 🔍 ...还有 45 个问题实在太屎，列不完了

### 5. module\os_simulator\simulator.py

**糟糕指数: 40.39**

**问题**: 🔄 复杂度问题: 9, ⚠️ 其他问题: 5, 📋 重复问题: 3, 🏗️ 结构问题: 3, ❌ 错误处理问题: 1, 📝 注释问题: 1, 🏷️ 命名问题: 10

- 🔄 `_simulate_one()` L48: 复杂度: 22
- 🔄 `get_paras()` L197: 复杂度: 14
- 🔄 `simulate()` L377: 复杂度: 11
- 🔄 `_simulate_one()` L48: 认知复杂度: 30
- 🔄 `_simulate_batch_kernel()` L140: 认知复杂度: 19
- 🔍 ...还有 25 个问题实在太屎，列不完了

### 6. module\statistics\cl1_database.py

**糟糕指数: 39.08**

**问题**: 🔄 复杂度问题: 17, ⚠️ 其他问题: 9, 📋 重复问题: 3, 🏗️ 结构问题: 13, ❌ 错误处理问题: 31, 📝 注释问题: 1, 🏷️ 命名问题: 10

- 🔄 `_normalize_meow_hazard_stats()` L258: 复杂度: 20
- 🔄 `_reconcile_meow_counts()` L372: 复杂度: 19
- 🔄 `migrate_from_json()` L726: 复杂度: 11
- 🔄 `get_meow_stats()` L940: 复杂度: 31
- 🔄 `_check_key_migration()` L105: 认知复杂度: 16
- 🔍 ...还有 77 个问题实在太屎，列不完了

### 7. module\device\connection.py

**糟糕指数: 38.47**

**问题**: 🔄 复杂度问题: 16, ⚠️ 其他问题: 8, 🏗️ 结构问题: 12, ❌ 错误处理问题: 9, 🏷️ 命名问题: 8

- 🔄 `retry_wrapper()` L32: 复杂度: 12
- 🔄 `_nc_server_host_port()` L435: 复杂度: 13
- 🔄 `adb_connect()` L774: 复杂度: 18
- 🔄 `detect_device()` L1079: 复杂度: 42
- 🔄 `retry_wrapper()` L32: 认知复杂度: 18
- 🔍 ...还有 47 个问题实在太屎，列不完了

### 8. module\map\fleet.py

**糟糕指数: 37.16**

**问题**: 🔄 复杂度问题: 28, ⚠️ 其他问题: 6, 🏗️ 结构问题: 17, ❌ 错误处理问题: 2, 📝 注释问题: 1

- 🔄 `round_wait()` L196: 复杂度: 11
- 🔄 `_goto()` L256: 复杂度: 70
- 🔄 `goto()` L475: 复杂度: 16
- 🔄 `full_scan()` L550: 复杂度: 11
- 🔄 `track_movable()` L611: 复杂度: 30
- 🔍 ...还有 46 个问题实在太屎，列不完了

### 9. module\commission\commission.py

**糟糕指数: 36.00**

**问题**: 🔄 复杂度问题: 22, ⚠️ 其他问题: 9, 📋 重复问题: 1, 🏗️ 结构问题: 9, 📝 注释问题: 1, 🏷️ 命名问题: 10

- 🔄 `_commission_choose()` L116: 复杂度: 21
- 🔄 `_commission_ensure_mode()` L234: 复杂度: 11
- 🔄 `_commission_start_click()` L356: 复杂度: 13
- 🔄 `_record_commission_income()` L523: 复杂度: 18
- 🔄 `_commission_receive()` L622: 复杂度: 28
- 🔍 ...还有 44 个问题实在太屎，列不完了

### 10. module\shop_event\shop_event.py

**糟糕指数: 35.21**

**问题**: 🔄 复杂度问题: 6, ⚠️ 其他问题: 2, 🏗️ 结构问题: 3, 📝 注释问题: 1, 🏷️ 命名问题: 1

- 🔄 `handle_items_related_with_urpt()` L35: 复杂度: 28
- 🔄 `handle_items_related_with_urpt()` L35: 认知复杂度: 44
- 🔄 `_run()` L187: 认知复杂度: 15
- 🔄 `run()` L244: 认知复杂度: 18
- 🔄 `handle_items_related_with_urpt()` L35: 嵌套深度: 8
- 🔍 ...还有 7 个问题实在太屎，列不完了

## 诊断结论 {#conclusion}

🌸 **偶有异味** - 基本没事，但是有伤风化

👍 继续保持，你是编码界的一股清流，代码洁癖者的骄傲

---

*由 [fuck-u-code](https://github.com/Done-0/fuck-u-code) 生成*

### 以上问题待解决（没招了 请求手搓大手子）

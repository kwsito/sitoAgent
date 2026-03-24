---
name: "appagent-mobile-runner"
description: "Builds/installs the open-source AppAgent Android app and runs tasks via the in-app input box + ADB artifacts. Invoke when users want to build APK, install, run tasks, or export logs."
---

# AppAgent Mobile Runner (Open-Source)

本技能用于把本仓库的开源版 AppAgent Android 应用跑起来：构建 APK、安装到设备、用应用内输入框执行任务，并通过 ADB 导出任务产物与日志。

## 何时调用

- 用户要“构建/打包 APK、安装到手机、快速迭代构建”
- 用户要“在手机上输入任务并执行”，并希望确认任务产物是否生成
- 用户要“导出 tasks/ 日志/截图/XML”，用于排查自动化失败原因
- 用户要“开源前检查涉密内容/清理构建产物”

## 前置条件

- Windows 上能运行 PowerShell 7
- 已安装 WSL（Ubuntu）并可运行 `wsl.exe`
- 已安装 adb，并且 `adb devices` 能看到至少一个 `device`
- Android 侧已开启开发者选项与 USB 调试（或无线调试）

## 构建与安装

### 方式 A：一键构建 + 安装（推荐）

在仓库根目录运行：

```powershell
.\one_click_build_install.ps1
```

多设备时指定目标：

```powershell
.\one_click_build_install.ps1 -Serial <adb_device_serial>
```

只构建不安装：

```powershell
.\one_click_build_install.ps1 -SkipInstall
```

### 方式 B：快速构建（开发迭代）

```powershell
.\quick_build.ps1 -Install
```

需要清缓存再试：

```powershell
.\quick_build.ps1 -Clean -Install
```

说明：

- `quick_build.ps1` 与 `one_click_build_install.ps1` 现在使用相同的 APK 选择规则（优先 arm64-v8a debug 包），避免“安装版本不一致”。

## 运行任务（开源版行为）

- 应用不再有账号/订单/后台轮询入口
- 任务来源仅来自应用界面底部输入框
- 点击发送（或侧边栏 Run Task）后开始执行

执行成功的常见产物（每轮）：

- `*_N.png`：截图
- `*_N.xml`：UI 树
- `*_N_labeled.png`：标注图（如果标注开启/可用）

## 示例：创建一个简单测试任务（小红书）

目标：验证“打开小红书 → 浏览首页第一篇笔记”这条最小闭环是否正常（截图/XML/动作执行/任务产物生成）。

前置条件：

- 手机已安装并可正常打开“小红书”
- 已完成小红书的首次登录/隐私弹窗处理（避免首启弹窗干扰自动化）
- AppAgent 已安装并能正常运行

操作步骤：

1. 在 AppAgent 底部输入框粘贴下面的任务文本并发送：

```text
打开小红书（如果未在前台就切换到小红书）。进入首页后，点击列表中的第一篇笔记打开，向下滑动浏览 2-3 屏，然后返回到首页，最后结束任务。
```

2. 等待任务结束后，用 ADB 导出任务目录：

```powershell
adb pull /data/user/0/org.test.orderquery/files/tasks .\downloaded_tasks
```

3. 验证导出的最新任务目录中存在多轮 `*_N.png` 与 `*_N.xml`（以及可选的 `*_N_labeled.png`）。

## 脚本接口：发送任务到 AppAgent（推荐）

开源版提供一个“脚本投递”接口（推荐使用 Intent）：脚本通过 adb 启动 AppAgent 并携带任务文本，AppAgent 会自动读取并像“粘贴到输入框并发送”一样触发执行。

使用方式（Windows / PowerShell）：

```powershell
.\send_task.ps1 -Task "打开小红书，浏览首页第一篇笔记，向下滑动2-3屏后返回首页并结束"
```

多设备时：

```powershell
.\send_task.ps1 -Serial <adb_device_serial> -Task "..."
```

参数说明：

- `-LaunchApp`：推送任务后拉起 AppAgent（可选）
- `-WaitSeconds`：等待 AppAgent 消费 inbox 文件的秒数（默认 10，设为 0 则不等待）
- `-UseFileInbox`：使用文件投递模式（兼容旧方案），默认不启用

## 导出任务产物（ADB）

导出 tasks 目录：

```powershell
adb pull /data/user/0/org.test.orderquery/files/tasks .\downloaded_tasks
```

多设备时：

```powershell
adb -s <adb_device_serial> pull /data/user/0/org.test.orderquery/files/tasks .\downloaded_tasks
```

## 配置与密钥策略（开源）

- 不要把真实模型 Key 提交到仓库
- 推荐通过环境变量或本机私有配置注入
- 仓库已提供 `.gitignore` 以忽略：`*.apk`、`logs/`、`tasks/`、`*.log`、调试截图等运行产物

## 失败排查清单（快速）

- `adb devices` 是否显示 `device`（不是 `unauthorized`）
- 设备侧截图/XML目录是否可写（见 `config.yaml` 的 `ANDROID_SCREENSHOT_DIR/ANDROID_XML_DIR`）
- 模型 Key 是否已在本机配置（否则执行器会提示未配置并跳过/失败）
- 导出 `tasks/` 后查看最新任务目录中的日志与每轮产物，判断是截图/XML失败还是模型响应/动作解析失败

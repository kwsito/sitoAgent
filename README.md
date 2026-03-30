# AppAgent Mobile（开源版）

这是一个可在 Android 真机上运行的移动端 GUI Agent（Kivy + python-for-android），通过 ADB 采集截图/XML 并执行点击/滑动等动作。

开源版特性：

- 支持脚本投递任务到手机（ADB Intent / 可选文件 inbox 方式）
- 提供了skill技能，可以直接交给龙虾模型调用

## 目录结构

- [main.py](./main.py)：Android App（UI + 任务执行入口）
- [scripts/](./scripts)：ADB 控制、模型调用、任务执行器
- [config.yaml](./config.yaml)：模型与运行参数
- [安装部署说明.md](./安装部署说明.md)：Windows + WSL 构建/安装与导出说明

## 快速开始

### 1) 准备

- Windows（推荐 PowerShell 7）
- WSL（Ubuntu）+ buildozer + python-for-android
- 电脑端adb 可用：`adb devices` 能看到至少一个 `device`（下载地址：[ADB环境地址](https://developer.android.com/studio/releases/platform-tools)）
- Android 侧已开启开发者选项与 USB 调试
- 如果需要模型输入文字，手机端需要安装ADB输入法（如：[ADB输入法地址](https://github.com/senzhk/ADBKeyBoard)）

### 2) 配置（本机私有）

编辑 [config.yaml](./config.yaml)：

- `OPENAI_API_KEY` / `DASHSCOPE_API_KEY` / `ARK_API_KEY`：只在本机填写或通过环境变量注入，不要提交到仓库
- `ANDROID_SCREENSHOT_DIR` / `ANDROID_XML_DIR`：设备侧中间产物目录

### 3) 构建并安装

推荐使用：

```powershell
.\one_click_build_install.ps1
```

开发迭代：

```powershell
.\quick_build.ps1 -Install
```

### 4) 运行任务

- 手机上启动 App（包名：`org.test.orderquery`）
- 在底部输入框输入任务文本，点击发送（或侧边栏 Run Task）
- 任务产物默认在应用私有目录（常见路径）：`/data/user/0/org.test.orderquery/files/app/tasks/`

### 5) 脚本投递任务（推荐）

通过 Intent 投递任务：

```powershell
.\send_task.ps1 -Task "打开小红书，浏览首页第一篇笔记，向下滑动2-3屏后返回首页并结束"
```

使用文件 inbox（可选）：

```powershell
.\send_task.ps1 -UseFileInbox -LaunchApp -Task "..."
```

## License

MIT License，见 [LICENSE](./LICENSE)。

# SitoAgent（开源版）

[English README](./README_EN.md)

这是一个可在 Android 真机上运行的移动端 GUI Agent（Kivy + python-for-android）app，通过 ADB 采集截图/XML 并执行点击/滑动等动作。

![demo](./assets/demo.png)

开源版特性：

- 支持脚本投递任务到手机（ADB Intent / 可选文件 inbox 方式）
- 提供了skill技能，可以直接交给龙虾模型调用

 使用前须知：本项目仅供研究和学习使用。严禁用于非法获取信息、干扰系统或任何违法活动。如开发者/用户在使用中未遵循相应的法律法规、政策、行业标准（包括但不限于技术规范、安全标准）及本开源项目的约定，由此产生的全部法律责任、经济损失及一切不良后果，均由开发者 / 用户自行独立承担。

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

开发者模式与 USB 调试：

- 开发者模式启用：通常启用方法是，找到 设置-关于手机-版本号，然后连续快速点击 10 次左右，直到弹出弹窗显示“开发者模式已启用”。不同手机会有些许差别，如果找不到，可以上网搜索一下教程。
- USB 调试启用：启用开发者模式之后，会出现 设置-开发者选项-USB 调试，勾选启用
- 部分机型在设置开发者选项以后，可能需要重启设备才能生效。可以测试一下：将手机用 USB 数据线连接到电脑后，执行 `adb devices` 查看是否有设备信息；如果没有说明连接失败。
- 请务必仔细检查相关权限

安装 ADB Keyboard（仅 Android 设备需要，用于文本输入）：

- 下载安装包并在对应的安卓设备中进行安装
- 安装完成后还需要到 设置-输入法 或者 设置-键盘列表 中启用 ADB Keyboard 才能生效（或使用命令：`adb shell ime enable com.android.adbkeyboard/.AdbIME`）

### 2) 配置（本机私有）

编辑 [config.yaml](./config.yaml)：

- `ARK_API_KEY`：只需要选择对应的模型，并填写对应模型的API Key就可以使用了。

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

本项目基于 [AppAgent](https://github.com/TencentQQGYLab/AppAgent) 进行二次开发，
原项目由 Jiaxuan Liu 创建，采用 MIT 许可证。

MIT License，见 [LICENSE](./LICENSE)。

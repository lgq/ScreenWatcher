# 打包说明（ScreenWatcher / TaskEngine）

本文档说明如何使用 `packaging/build.ps1` 打包两套应用：

- ScreenWatcher（原方案）
- TaskEngine（新方案）

## 1. 前置条件

1. 在项目根目录执行，且可用 Python（优先 `.venv`）。
2. 已安装打包依赖（脚本会自动安装）：PyInstaller、Pillow、WinRT 相关包。
3. 若需生成安装包（Setup.exe），需安装 Inno Setup 6（`ISCC.exe`）。
4. 若本地没有 `platform-tools/adb.exe`，脚本会自动下载 Android platform-tools（可通过参数关闭下载）。

## 2. 通用命令格式

```powershell
.\packaging\build.ps1 -Target <ScreenWatcher|TaskEngine|All> -Version <版本号> [可选参数]
```

可选参数：

- `-SkipInstaller`：只生成 PyInstaller 产物，不生成安装包。
- `-SkipPlatformToolsDownload`：禁止自动下载 platform-tools（本地必须已有可用 adb）。

## 3. 只打包 ScreenWatcher

```powershell
.\packaging\build.ps1 -Target ScreenWatcher -Version 1.0.0
```

只生成可执行目录（不生成安装包）：

```powershell
.\packaging\build.ps1 -Target ScreenWatcher -Version 1.0.0 -SkipInstaller
```

## 4. 只打包 TaskEngine

```powershell
.\packaging\build.ps1 -Target TaskEngine -Version 1.0.0
```

只生成可执行目录（不生成安装包）：

```powershell
.\packaging\build.ps1 -Target TaskEngine -Version 1.0.0 -SkipInstaller
```

## 5. 同时打包两套（默认）

```powershell
.\packaging\build.ps1
```

等价写法：

```powershell
.\packaging\build.ps1 -Target All -Version 1.0.0
```

## 6. 产物位置

- PyInstaller 目录产物：
  - `dist/ScreenWatcher/`
  - `dist/TaskEngine/`
- Inno Setup 安装包：
  - `packaging/output/ScreenWatcher-Setup-<Version>.exe`
  - `packaging/output/TaskEngine-Setup-<Version>.exe`

## 7. 常见问题

1. 找不到 `ISCC.exe`：安装 Inno Setup 6，或使用 `-SkipInstaller`。
2. `platform-tools` 下载失败：检查网络，或手动准备 `platform-tools/adb.exe` 后加 `-SkipPlatformToolsDownload`。
3. 想快速验证结构：先用 `-SkipInstaller`，确认 `dist/` 下两个目录能正常运行后再生成安装包。

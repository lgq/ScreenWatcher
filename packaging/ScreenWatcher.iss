#define MyAppName "ScreenWatcher"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define MyAppPublisher "ScreenWatcher"
#define MyAppExeName "ScreenWatcher.exe"
#define MyAppAssocName MyAppName + " Application"
#define BuildOutputDir AddBackslash(SourcePath) + "..\dist\ScreenWatcher"

[Setup]
AppId={{F5E56B1F-A8A1-41AF-8FB5-2B9C47D89D47}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma
SolidCompression=yes
WizardStyle=modern
OutputDir={#SourcePath}\output
OutputBaseFilename=ScreenWatcher-Setup-{#AppVersion}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked
Name: "cleanupuserdata"; Description: "卸载时清理用户数据（%LOCALAPPDATA%\\ScreenWatcher）"; GroupDescription: "卸载选项:"; Flags: unchecked

[Files]
Source: "{#BuildOutputDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

; 默认保留用户数据目录，只有勾选 cleanupuserdata 才执行删除。
[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\ScreenWatcher"; Tasks: cleanupuserdata

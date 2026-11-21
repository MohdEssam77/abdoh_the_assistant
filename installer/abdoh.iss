; Krekos's Windows installer, built with Inno Setup 6 by scripts/build_installer.py (which passes
; /DAppVersion=x.y.z). It installs for the current user only, so no admin rights are needed.
; Your settings and commands (%APPDATA%\Krekos) are kept when you uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E0A9C7B-5B8F-4C1F-9D59-2B1A7A3C4D10}
AppName=Krekos
AppVersion={#AppVersion}
AppVerName=Krekos {#AppVersion}
AppPublisher=Krekos
AppPublisherURL=https://github.com/MohdEssam77/abdoh_the_assistant
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Krekos
; Xanthos and Abdoh (the old names) lived in Programs\Xanthos and Programs\Abdoh. The same
; AppId replaces them, in the new folder.
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Krekos-Setup
SetupIconFile=..\build\krekos.ico
UninstallDisplayIcon={app}\Krekos.exe
UninstallDisplayName=Krekos
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "startup"; Description: "Start Krekos when I sign in to Windows"

[InstallDelete]
; What Xanthos and Abdoh (the old names) left behind.
Type: filesandordirs; Name: "{localappdata}\Programs\Xanthos"
Type: files; Name: "{autoprograms}\Xanthos.lnk"
Type: files; Name: "{autodesktop}\Xanthos.lnk"
Type: filesandordirs; Name: "{localappdata}\Programs\Abdoh"
Type: files; Name: "{autoprograms}\Abdoh.lnk"
Type: files; Name: "{autodesktop}\Abdoh.lnk"

[Files]
Source: "..\dist\Krekos\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Krekos"; Filename: "{app}\Krekos.exe"; Parameters: "run --show"; Comment: "Krekos, your voice assistant"
Name: "{autodesktop}\Krekos"; Filename: "{app}\Krekos.exe"; Parameters: "run --show"; Tasks: desktopicon

[Registry]
; The same startup entry Krekos's own "Start at sign-in" switch uses, so the switch can turn it off.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Krekos"; ValueData: """{app}\Krekos.exe"" run --minimized"; Flags: uninsdeletevalue; Tasks: startup
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Xanthos"; Flags: deletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Abdoh"; Flags: deletevalue

[Run]
Filename: "{app}\Krekos.exe"; Parameters: "run --show"; Description: "Start Krekos now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM Krekos.exe"; Flags: runhidden; RunOnceId: "StopKrekos"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN Krekos /F"; Flags: runhidden; RunOnceId: "RemoveTask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Close a running Krekos (or Xanthos or Abdoh, its old names) before its files are replaced,
// and remove the old names' start-at-sign-in tasks.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Krekos.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Xanthos.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Abdoh.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /TN Xanthos /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /TN Abdoh /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

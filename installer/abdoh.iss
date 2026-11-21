; Abdoh's Windows installer, built with Inno Setup 6 by scripts/build_installer.py (which passes
; /DAppVersion=x.y.z). It installs for the current user only, so no admin rights are needed.
; Your settings and commands (%APPDATA%\Abdoh) are kept when you uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E0A9C7B-5B8F-4C1F-9D59-2B1A7A3C4D10}
AppName=Abdoh
AppVersion={#AppVersion}
AppVerName=Abdoh {#AppVersion}
AppPublisher=Abdoh
AppPublisherURL=https://github.com/MohdEssam77/abdoh_the_assistant
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Abdoh
; Krekos and Xanthos (the names it had for a while) lived in Programs\Krekos and
; Programs\Xanthos. The same
; AppId replaces them, in the new folder.
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Abdoh-Setup
SetupIconFile=..\build\abdoh.ico
UninstallDisplayIcon={app}\Abdoh.exe
UninstallDisplayName=Abdoh
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "startup"; Description: "Start Abdoh when I sign in to Windows"

[InstallDelete]
; What Krekos and Xanthos (the names it had for a while) left behind.
Type: filesandordirs; Name: "{localappdata}\Programs\Krekos"
Type: files; Name: "{autoprograms}\Krekos.lnk"
Type: files; Name: "{autodesktop}\Krekos.lnk"
Type: filesandordirs; Name: "{localappdata}\Programs\Xanthos"
Type: files; Name: "{autoprograms}\Xanthos.lnk"
Type: files; Name: "{autodesktop}\Xanthos.lnk"

[Files]
Source: "..\dist\Abdoh\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Abdoh"; Filename: "{app}\Abdoh.exe"; Parameters: "run --show"; Comment: "Abdoh, your voice assistant"
Name: "{autodesktop}\Abdoh"; Filename: "{app}\Abdoh.exe"; Parameters: "run --show"; Tasks: desktopicon

[Registry]
; The same startup entry Abdoh's own "Start at sign-in" switch uses, so the switch can turn it off.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Abdoh"; ValueData: """{app}\Abdoh.exe"" run --minimized"; Flags: uninsdeletevalue; Tasks: startup
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Krekos"; Flags: deletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Xanthos"; Flags: deletevalue

[Run]
Filename: "{app}\Abdoh.exe"; Parameters: "run --show"; Description: "Start Abdoh now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM Abdoh.exe"; Flags: runhidden; RunOnceId: "StopAbdoh"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN Abdoh /F"; Flags: runhidden; RunOnceId: "RemoveTask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Close a running Abdoh (or Krekos or Xanthos, names it had for a while) before its files are
// replaced,
// and remove the old names' start-at-sign-in tasks.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Abdoh.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Krekos.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Xanthos.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /TN Krekos /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /TN Xanthos /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

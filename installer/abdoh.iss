; Xanthos's Windows installer, built with Inno Setup 6 by scripts/build_installer.py (which passes
; /DAppVersion=x.y.z). It installs for the current user only, so no admin rights are needed.
; Your settings and commands (%APPDATA%\Xanthos) are kept when you uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E0A9C7B-5B8F-4C1F-9D59-2B1A7A3C4D10}
AppName=Xanthos
AppVersion={#AppVersion}
AppVerName=Xanthos {#AppVersion}
AppPublisher=Xanthos
AppPublisherURL=https://github.com/MohdEssam77/abdoh_the_assistant
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Xanthos
; Abdoh (the old name) lived in Programs\Abdoh. The same AppId replaces it, in the new folder.
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Xanthos-Setup
SetupIconFile=..\build\xanthos.ico
UninstallDisplayIcon={app}\Xanthos.exe
UninstallDisplayName=Xanthos
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "startup"; Description: "Start Xanthos when I sign in to Windows"

[InstallDelete]
; What Abdoh (Xanthos's old name) left behind.
Type: filesandordirs; Name: "{localappdata}\Programs\Abdoh"
Type: files; Name: "{autoprograms}\Abdoh.lnk"
Type: files; Name: "{autodesktop}\Abdoh.lnk"

[Files]
Source: "..\dist\Xanthos\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Xanthos"; Filename: "{app}\Xanthos.exe"; Parameters: "run --show"; Comment: "Xanthos, your voice assistant"
Name: "{autodesktop}\Xanthos"; Filename: "{app}\Xanthos.exe"; Parameters: "run --show"; Tasks: desktopicon

[Registry]
; The same startup entry Xanthos's own "Start at sign-in" switch uses, so the switch can turn it off.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Xanthos"; ValueData: """{app}\Xanthos.exe"" run --minimized"; Flags: uninsdeletevalue; Tasks: startup
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Abdoh"; Flags: deletevalue

[Run]
Filename: "{app}\Xanthos.exe"; Parameters: "run --show"; Description: "Start Xanthos now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM Xanthos.exe"; Flags: runhidden; RunOnceId: "StopXanthos"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN Xanthos /F"; Flags: runhidden; RunOnceId: "RemoveTask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Close a running Xanthos (or Abdoh, its old name) before its files are replaced, and remove
// Abdoh's start-at-sign-in task.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Xanthos.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Abdoh.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /TN Abdoh /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

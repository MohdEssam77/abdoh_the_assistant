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
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Abdoh-Setup
SetupIconFile=..\build\abdoh.ico
UninstallDisplayIcon={app}\Abdoh.exe
UninstallDisplayName=Abdoh
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "startup"; Description: "Start Abdoh when I sign in to Windows"

[Files]
Source: "..\dist\Abdoh\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Abdoh"; Filename: "{app}\Abdoh.exe"; Parameters: "run --show"; Comment: "Abdoh, your voice assistant"
Name: "{autodesktop}\Abdoh"; Filename: "{app}\Abdoh.exe"; Parameters: "run --show"; Tasks: desktopicon

[Registry]
; The same startup entry Abdoh's own "Start at sign-in" switch uses, so the switch can turn it off.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Abdoh"; ValueData: """{app}\Abdoh.exe"" run --minimized"; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\Abdoh.exe"; Parameters: "run --show"; Description: "Start Abdoh now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM Abdoh.exe"; Flags: runhidden; RunOnceId: "StopAbdoh"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN Abdoh /F"; Flags: runhidden; RunOnceId: "RemoveTask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Close a running Abdoh before its files are replaced.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Abdoh.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

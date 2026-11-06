; Windows installer for the app: DotaCoachSetup.exe, built by Inno Setup
; (https://jrsoftware.org/isinfo.php) from the dist\DotaCoach folder that
; packaging/build_exe.py makes:
;
;     iscc /DAppVersion=0.1.0 packaging\installer.iss
;
; Installs for the current user only (no admin prompt) into
; %LOCALAPPDATA%\Programs\Dota 2 Live Coach, with a Start menu shortcut, an
; optional desktop shortcut and an uninstaller. Settings and recordings in
; %APPDATA%\Dota2LiveCoach are left alone on uninstall.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "Dota 2 Live Coach"
#define AppExe "Dota 2 Live Coach.exe"

[Setup]
; Never change AppId: Windows uses it to find the installed app on updates.
AppId={{D4D95C67-2FE8-4D21-AF62-7AF69A7383B1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=DotaCoachSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\DotaCoach\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Writes Dota 2's Game State Integration file now, so the first match just works.
Filename: "{app}\DotaCoach.exe"; Parameters: "install"; StatusMsg: "Setting up Dota 2 Game State Integration..."; Flags: runhidden
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: postinstall nowait skipifsilent

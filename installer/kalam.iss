; Inno Setup script for Kalam-Setup.exe
; Build:  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\kalam.iss   (after pyinstaller kalam.spec)

#define AppName "Kalam"
#define AppVersion "1.3.1"
#define AppExe "Kalam.exe"
; test builds:  ISCC /DTEST installer\kalam.iss  -> separate identity, so installing / uninstalling a
; test copy never touches the real Kalam's entry in Settings > Apps or its start-with-Windows value
#ifdef TEST
  #define AppGuid "{{5f3b1c2e-9a7d-4e61-b8f0-2d4c6a9e1b73}"
  #define AppSuffix "-test"
#else
  #define AppGuid "{{80adecd5-f36d-4e72-8224-7c116d7d1be6}"
  #define AppSuffix ""
#endif

[Setup]
; never change AppId: it is how Windows recognises upgrades of the same app
AppId={#AppGuid}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Mohamed ElGohary
AppPublisherURL=https://github.com/datimore/kalam
AppSupportURL=https://github.com/datimore/kalam/issues
; per-user install: no admin prompt, lands in %LOCALAPPDATA%\Programs\Kalam
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
SetupIconFile=..\assets\kalam.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}: Egyptian Arabic + English dictation
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
OutputDir=output
OutputBaseFilename=Kalam-Setup-{#AppVersion}{#AppSuffix}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; close a running Kalam before installing / uninstalling
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start Kalam when I sign in to Windows"; GroupDescription: "Startup:"

[Files]
Source: "..\dist\Kalam\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; same value the app's own "Start with Windows" menu item writes
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Kalam"; \
  ValueData: """{app}\{#AppExe}"" --tray"; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open Kalam now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Messages]
FinishedLabel=Kalam is installed.%n%nThe first start downloads the speech model (about 3 GB, one time only) and the Kalam window shows the progress. After that: hold Right Ctrl, talk, let go.

[Code]
// The "Start with Windows" value is also written by the app itself, so remove it on uninstall either way
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
#ifndef TEST
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Kalam');
#endif
    if SuppressibleMsgBox('Also delete your Kalam settings and dictation history?' + #13#10 +
       '(' + ExpandConstant('{userappdata}\Kalam') + ')', mbConfirmation, MB_YESNO, IDNO) = IDYES then
      DelTree(ExpandConstant('{userappdata}\Kalam'), True, True, True);
  end;
end;

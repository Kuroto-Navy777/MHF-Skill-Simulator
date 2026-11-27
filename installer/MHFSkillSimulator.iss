; Build with build_installer.py from the verified portable release.
#ifndef AppVersion
  #error AppVersion must be supplied
#endif
#ifndef IncludeDB
  #error IncludeDB must be supplied (0 or 1)
#endif
#ifndef PayloadDir
  #error PayloadDir must be supplied
#endif
#ifndef OutputFolder
  #error OutputFolder must be supplied
#endif
#if IncludeDB == 1
  #define SetupVariant "with_DB"
#else
  #define SetupVariant "no_DB"
#endif
[Setup]
AppId={{D31AD25E-E787-4399-BA41-6982F1519B3B}
AppName=MHF Skill Simulator
AppVersion={#AppVersion}
AppPublisher=MHF Skill Simulator (Unofficial)
AppPublisherURL=https://github.com/Kuroto-Navy777/MHF-Skill-Simulator
AppUpdatesURL=https://github.com/Kuroto-Navy777/MHF-Skill-Simulator/releases/latest
DefaultDirName={localappdata}\Programs\MHFSkillSimulator
DefaultGroupName=MHF Skill Simulator
DisableDirPage=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
MinVersion=10.0
AppMutex=Local\MHFSkillSimulator.InstallerGuard
SetupMutex=Local\MHFSkillSimulator.Setup
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\MHFSimulator.exe
SetupIconFile={#PayloadDir}\app\web\favicon.ico
OutputDir={#OutputFolder}
OutputBaseFilename=MHF_SkillSimulator_{#AppVersion}_Setup_win_x64_{#SetupVariant}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
japanese.ExistingInstall=既にインストールされています。アプリを起動して自動更新してください。再インストールする場合は、先にアンインストールしてください。
english.ExistingInstall=Already installed. Use the in-app updater, or uninstall first to reinstall.
japanese.BadLocation=安全な更新のため、既定のインストール先を使用してください。
english.BadLocation=For safe updates, use the default installation folder.
japanese.NeedDB=DB非同梱版です。起動前に正規に入手・生成した mhf_master.sqlite をインストール先へ配置してください。WebView2 Runtime が必要です。
english.NeedDB=Database not included. Place your lawfully obtained/generated mhf_master.sqlite in the installation folder before launching. WebView2 Runtime is required.
japanese.KeepData=アンインストール後もDB・お気に入り・所持品・バックアップを保持します。
english.KeepData=The database, favorites, inventory and backups remain after uninstall.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PayloadDir}\MHFSimulator.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PayloadDir}\release_source.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#PayloadDir}\README.txt"; DestDir: "{app}"; Flags: ignoreversion
#if IncludeDB == 1
; Preserve existing local DB, including on uninstall/reinstall.
Source: "{#PayloadDir}\mhf_master.sqlite"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
#endif

[Icons]
Name: "{autoprograms}\MHF Skill Simulator"; Filename: "{app}\MHFSimulator.exe"; WorkingDir: "{app}"; AppUserModelID: "MHFSkillSimulator.Desktop"
Name: "{autodesktop}\MHF Skill Simulator"; Filename: "{app}\MHFSimulator.exe"; WorkingDir: "{app}"; AppUserModelID: "MHFSkillSimulator.Desktop"; Tasks: desktopicon

[Run]
Filename: "{app}\MHFSimulator.exe"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,MHF Skill Simulator}"; Flags: nowait postinstall skipifsilent; Check: HasDatabase

[UninstallDelete]
; The updater can create files that were not listed in the original installer.
; Remove only managed program trees, never the install root, database or profile.
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\.app_previous"
Type: filesandordirs; Name: "{app}\.launcher-handoff"
Type: files; Name: "{app}\.launcher_previous.exe"
Type: files; Name: "{app}\.update_pending"
Type: files; Name: "{app}\.rollback_requested"

[Code]
function HasDatabase(): Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\mhf_master.sqlite'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Target: String;
begin
  Result := '';
  Target := ExpandConstant('{app}');
  { Refuse installer upgrades/downgrades and arbitrary path overrides. }
  if CompareText(Target, ExpandConstant('{localappdata}\Programs\MHFSkillSimulator')) <> 0 then
    Result := CustomMessage('BadLocation')
  else if FileExists(Target + '\MHFSimulator.exe') or DirExists(Target + '\app') or
          DirExists(Target + '\.app_previous') or DirExists(Target + '\.launcher-handoff') or
          FileExists(Target + '\.launcher_previous.exe') then
    Result := CustomMessage('ExistingInstall');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not HasDatabase() and not WizardSilent() then
    MsgBox(CustomMessage('NeedDB') + #13#10 + ExpandConstant('{app}'), mbInformation, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command, Target: String;
begin
  if CurUninstallStep = usUninstall then begin
    { Remove auto-start only if it points to this installation, not another portable copy. }
    Target := ExpandConstant('{app}\MHFSimulator.exe');
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'MHFSkillSimulator.Desktop', Command) then
      if (CompareText(Command, '"' + Target + '" --background') = 0) or
         (CompareText(Command, Target + ' --background') = 0) then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'MHFSkillSimulator.Desktop');
  end;
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent() then
    MsgBox(CustomMessage('KeepData'), mbInformation, MB_OK);
end;

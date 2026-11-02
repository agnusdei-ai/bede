; Bede source-free Windows release-candidate installer.
; Bundles only the verified operator manifest and bootstrap, never source code.
; Installer signing is performed separately, after explicit owner approval.
; Build via build-bede-operator.yml using the same exact SHA as the Mac DMG.
#define MyAppName "Bede Installer"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Agnus Dei Technologies, LLC"
#define MyAppURL "https://agnusdei.ai"

[Setup]
AppId={{9A5E5DB4-7802-41D1-B6D0-44D2F8AD4A90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={localappdata}\Bede\ReleaseCandidate
DefaultGroupName=Bede
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=BedeRelease
SetupIconFile=assets\bede.ico
UninstallDisplayIcon={app}\bede.ico
WizardStyle=modern
WizardSmallImageFile=assets\bede-wizard-small.bmp
Compression=lzma2
SolidCompression=yes
LicenseFile=..\..\LICENSE
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; Populated by the packaging CI job from the SHA-pinned Linux/amd64
; Standard operator artifact. No source checkout or mutable image tag.
Source: "release-payload\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\bede.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Bede Installer"; Filename: "powershell.exe"; Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\Install-Bede.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\bede.ico"
Name: "{autodesktop}\Bede Installer"; Filename: "powershell.exe"; Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\Install-Bede.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\bede.ico"; Tasks: desktopicon

[Run]
; Explicit opt-in; merely installing the shell cannot launch Docker or store data.
Filename: "powershell.exe"; Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\Install-Bede.ps1"""; WorkingDir: "{app}"; Description: "Start guided Bede setup"; Flags: postinstall nowait skipifsilent unchecked

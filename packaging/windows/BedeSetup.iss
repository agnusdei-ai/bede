; Bede Setup — Inno Setup script. Same scope as the WiX MSI it replaced: a
; small installer whose only job is landing Setup-Bede.ps1 on disk and
; giving the family a shortcut to run it. All Docker Desktop / Ollama /
; repo-download / wizard-launching logic lives in that script (see its own
; header comment and docs/WINDOWS_INSTALLER.md) — deliberately NOT
; reimplemented here, the same "don't reimplement the wizard" principle
; setup-gui.bat/.command/.sh already follow for macOS/Linux.
;
; Inno Setup chosen over WiX/MSI specifically for its default wizard UI
; (License -> Destination -> Start Menu Folder -> Additional Tasks ->
; Install progress) — a better match for this project's actual audience
; (a family, not an IT department) than MSI's enterprise-oriented features
; (GPO deployment, SCCM/Intune) that Bede has no use for. See
; docs/WINDOWS_INSTALLER.md.

#define MyAppName "Bede Setup"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Agnus Dei Technologies, LLC"
#define MyAppURL "https://github.com/agnusdei-ai/bede"

[Setup]
AppId={{7B1F2B3E-9C4A-4D5E-8F6A-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Bede
DefaultGroupName=Bede
DisableProgramGroupPage=no
; Docker Desktop (chain-installed by Setup-Bede.ps1) requires 64-bit Windows
; 10/11 — genuine 32-bit Windows can't run Bede at all regardless of what
; this installer itself would allow. Refusing up front here is more honest
; than letting the wizard open and fail confusingly partway through.
ArchitecturesAllowed=x64compatible
; Per-user install (no admin prompt for the shell itself) — Setup-Bede.ps1
; requests elevation on its own, only for the one step that needs it
; (installing Docker Desktop), and only when Docker Desktop isn't already
; present. Same rationale the WiX version's Scope="perUser" had.
PrivilegesRequired=lowest
LicenseFile=..\..\LICENSE
OutputDir=Output
OutputBaseFilename=BedeSetup
SetupIconFile=assets\bede.ico
WizardStyle=modern
WizardSmallImageFile=assets\bede-wizard-small.bmp
UninstallDisplayIcon={app}\bede.ico
Compression=lzma2
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "Setup-Bede.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\bede.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Bede Setup"; Filename: "powershell.exe"; Parameters: "-NoLogo -ExecutionPolicy Bypass -File ""{app}\Setup-Bede.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\bede.ico"
Name: "{group}\Uninstall Bede Setup"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Bede Setup"; Filename: "powershell.exe"; Parameters: "-NoLogo -ExecutionPolicy Bypass -File ""{app}\Setup-Bede.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\bede.ico"; Tasks: desktopicon

[Run]
; The classic Inno "launch after Finish" checkbox — unchecked by default so
; a family who just wants the shortcut for later isn't forced through the
; whole Docker Desktop/Ollama flow immediately.
Filename: "powershell.exe"; Parameters: "-NoLogo -ExecutionPolicy Bypass -File ""{app}\Setup-Bede.ps1"""; WorkingDir: "{app}"; Description: "Launch Bede Setup now"; Flags: postinstall nowait skipifsilent unchecked

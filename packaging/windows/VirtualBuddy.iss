; Inno Setup script - wraps the PyInstaller build into a friendly Windows installer.
; Produces VirtualBuddy-Setup.exe: Start-menu + desktop shortcut, uninstaller.
; Built automatically by CI (see .github/workflows/release.yml).

#define AppName "VirtualBuddy"
#define AppVer  "0.2.1"

[Setup]
AppName={#AppName}
AppVersion={#AppVer}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputBaseFilename=VirtualBuddy-Setup
OutputDir=Output
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
WizardStyle=modern

[Files]
; the PyInstaller onedir output (dist\VirtualBuddy) sits two levels up from this script
Source: "..\..\dist\VirtualBuddy\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\VirtualBuddy";        Filename: "{app}\VirtualBuddy.exe"
Name: "{commondesktop}\VirtualBuddy"; Filename: "{app}\VirtualBuddy.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\VirtualBuddy.exe"; Description: "Launch VirtualBuddy"; Flags: nowait postinstall skipifsilent

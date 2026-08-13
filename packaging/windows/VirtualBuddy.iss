; Inno Setup script for the VirtualBuddy installer.
;
;   iscc packaging\windows\VirtualBuddy.iss /DAppVersion=0.6.1
;
; Installs per user into Local AppData, so there is no UAC prompt and no admin
; account needed. User data lives in %USERPROFILE%\.virtualbuddy and is left
; alone by both install and uninstall.

#ifndef AppVersion
  #define AppVersion "0.6.1"
#endif

#define AppName "VirtualBuddy"
#define AppPublisher "VirtualBuddy"
#define AppURL "https://sahilsidhu7.github.io/VirtualBuddy/"
#define AppExe "VirtualBuddy.exe"

[Setup]
AppId={{7B2F1C64-3E2A-4E2B-9A66-6C5E8B1D4A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL=https://github.com/SahilSidhu7/VirtualBuddy/issues
AppUpdatesURL=https://github.com/SahilSidhu7/VirtualBuddy/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\..\dist
; No version in the filename on purpose: it keeps
; /releases/latest/download/VirtualBuddy-Setup.exe working forever, which is
; what the website links to. The version lives in the file's properties.
OutputBaseFilename=VirtualBuddy-Setup
SetupIconFile=virtualbuddy.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startupicon"; Description: "Start {#AppName} when I sign in"; GroupDescription: "Handy:"
Name: "desktopicon"; Description: "Put a shortcut on my desktop"; GroupDescription: "Handy:"; Flags: unchecked

[Files]
Source: "..\..\dist\VirtualBuddy\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\VirtualBuddy\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} on the web"; Filename: "{#AppURL}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Say hello to {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Messages]
; The buddy lives on the desktop, so say where it will appear rather than
; leaving people hunting for a window that never opens.
FinishedLabel=VirtualBuddy is installed. It appears in the bottom right of your screen: click it to open the panel, drag it anywhere, right click it for settings.

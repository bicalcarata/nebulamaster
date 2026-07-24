[Setup]
AppId=com.bicalcarata.nebulamaster
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Bicalcarata
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\Nebula Master.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Nebula Master.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Nebula Master.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Nebula Master.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

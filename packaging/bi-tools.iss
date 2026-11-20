; Inno Setup 6 - installer BI Tools.
;
; Dikompilasi oleh packaging/build.ps1 atau alur rilis GitHub:
;   ISCC.exe /DMyAppVersion=0.2.0 packaging\bi-tools.iss
;
; Sumber file: ..\dist\BI Tools\ (hasil PyInstaller onedir, sudah memuat
; templates\, libs\, web\, dan rules\ di samping exe).
;
; Catatan penting:
; - Default pemasangan per pengguna ({autopf} = %LOCALAPPDATA%\Programs) supaya
;   tidak perlu UAC dan folder aplikasi bisa ditulis. Opsi "all users" tetap
;   tersedia; dalam kasus itu core\paths.py otomatis memindahkan outputs\ dan
;   data\ ke %LOCALAPPDATA%\BI Tools.
; - outputs\ dan data\ dibuat saat runtime dan TIDAK terdaftar sebagai file
;   installer, jadi uninstaller tidak menghapusnya. Jangan menambahkan
;   [UninstallDelete] untuk kedua folder itu.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "BI Tools"
#define MyAppPublisher "BI Tools"
#define MyAppExeName "BI Tools.exe"
#define MyAppCliName "bi-tools-cli.exe"
#define MyAppId "{{6F1B2C4A-9E7D-4B8C-9A21-3E5D7F0B8C11}"
#define BuildDir "..\dist\BI Tools"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=BITools-Setup-{#MyAppVersion}
SetupIconFile=bi-tools.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AllowNoIcons=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "downloadbrowser"; Description: "Unduh Chromium untuk fitur screenshot TSD (perlu internet, sekitar 150 MB)"; GroupDescription: "Fitur opsional:"

[Files]
; outputs\, data\, dan TSD_assets\ dibuat saat runtime; jangan ikut installer.
Source: "{#BuildDir}\*"; DestDir: "{app}"; Excludes: "outputs\*,data\*,TSD_assets\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Perintah baris {#MyAppName}"; Filename: "{app}\{#MyAppCliName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppCliName}"; Parameters: "install-browser"; StatusMsg: "Mengunduh Chromium untuk screenshot TSD..."; Flags: runhidden waituntilterminated; Tasks: downloadbrowser

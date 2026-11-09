$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$appSpec = Join-Path $root "build\spec-app"
$setupSpec = Join-Path $root "build\spec-setup"

& $py -m pip install -q -r requirements.txt pyinstaller pillow
& $py tools\make_icon.py

$out = Join-Path $root "Output"
New-Item -ItemType Directory -Force $out | Out-Null
New-Item -ItemType Directory -Force $appSpec, $setupSpec | Out-Null

& $py -m PyInstaller --noconfirm --clean --onefile --windowed --name PowerPulse `
    --icon "$root\assets\icon.ico" --add-data "$root\assets\icon.ico;assets" `
    --distpath $out --workpath "$root\build\app" --specpath $appSpec "$root\run.py"

& $py -m PyInstaller --noconfirm --clean --onefile --windowed --name PowerPulse-Setup `
    --icon "$root\assets\icon.ico" --add-data "$root\assets\icon.ico;." `
    --paths "$root" `
    --add-data "$out\PowerPulse.exe;." `
    --distpath $out --workpath "$root\build\setup" --specpath $setupSpec "$root\installer\setup.py"

Get-ChildItem $out | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"

& $py -m pip install -q -r requirements.txt pyinstaller pillow
& $py tools\make_icon.py

$out = Join-Path $root "Output"
New-Item -ItemType Directory -Force $out | Out-Null

& $py -m PyInstaller --noconfirm --clean --onefile --windowed --name PowerPulse `
    --icon "$root\assets\icon.ico" --add-data "$root\assets\icon.ico;assets" `
    --distpath $out --workpath build\app --specpath build "$root\run.py"

& $py -m PyInstaller --noconfirm --clean --onefile --windowed --name PowerPulse-Setup `
    --icon "$root\assets\icon.ico" --add-data "$root\assets\icon.ico;." `
    --add-data "$out\PowerPulse.exe;." `
    --distpath $out --workpath build\setup --specpath build "$root\installer\setup.py"

Get-ChildItem $out | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }


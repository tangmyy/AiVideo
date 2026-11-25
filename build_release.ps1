$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.pyinstaller-cache'
$distRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'dist'))
foreach ($name in @('AiVideo', 'AiVideoTranscriber')) {
    $old = [IO.Path]::GetFullPath((Join-Path $distRoot $name))
    if (-not $old.StartsWith($distRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid release path' }
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }
}
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean AiVideo.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --console --name AiVideoTranscriber --hidden-import faster_whisper --collect-submodules bilibili_api.clients --collect-data faster_whisper --collect-binaries ctranslate2 --collect-binaries onnxruntime --collect-binaries av --exclude-module PyQt5 --exclude-module PySide6 media_outputs.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$source = Join-Path $PSScriptRoot 'dist\AiVideoTranscriber'
$target = Join-Path $PSScriptRoot 'dist\AiVideo\transcriber'
if (-not [IO.Path]::GetFullPath($target).StartsWith([IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'dist\AiVideo')) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid release target' }
if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
Copy-Item -LiteralPath $source -Destination $target -Recurse
Write-Host "Ready: $PSScriptRoot\dist\AiVideo\AiVideo.exe"

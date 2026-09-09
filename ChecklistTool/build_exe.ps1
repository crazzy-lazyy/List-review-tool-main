param(
  [string]$Python = "python",
  [string]$VenvDir = ".venv",
  [switch]$NoVenv
)

$ErrorActionPreference = "Stop"

function Ensure-Venv {
  if ($NoVenv) { return }
  if (-not (Test-Path $VenvDir)) {
    & $Python -m venv $VenvDir
  }
  $venvPython = Join-Path $VenvDir "Scripts\python.exe"
  if (-not (Test-Path $venvPython)) {
    throw "Venv create failed: $venvPython missing"
  }
  $script:Python = $venvPython
}

Push-Location $PSScriptRoot
try {
  Ensure-Venv

  & $Python -m pip install -U pip
  & $Python -m pip install -r requirements.txt

  # Clean old outputs
  if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
  if (Test-Path "build") { Remove-Item -Recurse -Force "build" }

  # Build entry: main.py (windowed, no console)
  $args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "ChecklistTool_v2.0",
    "--paths", "$PSScriptRoot",
    "$PSScriptRoot\main.py"
  )
  & $Python @args

  Write-Host ""
  Write-Host "Done. EXE at: $PSScriptRoot\dist\ChecklistTool_v2.0\ChecklistTool_v2.0.exe"
} finally {
  Pop-Location
}


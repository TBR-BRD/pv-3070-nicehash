$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (!(Test-Path $Python)) { throw "Virtual environment not found. Create .venv and install requirements first." }
$Action = New-ScheduledTaskAction -Execute $Python -Argument '-m src.main' -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'PV-3070-NiceHash' -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force
Write-Host 'Scheduled task PV-3070-NiceHash installed.'

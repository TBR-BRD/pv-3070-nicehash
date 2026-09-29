$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (!(Test-Path $Python)) { throw "Virtual environment not found. Create .venv and install requirements first." }
$Action = New-ScheduledTaskAction -Execute $Python -Argument '-m src.main' -WorkingDirectory $Root
# Runs at logon as the current interactive user (not SYSTEM): NiceHash Miner
# is a GUI app and needs an actual user session plus its user-profile config
# (C:\Users\<you>\AppData\Local\Programs\NiceHash Miner\...) to work the same
# way it did in manual, interactive testing. This does mean Windows needs to
# actually log this user in for the task to fire - see the README note on
# auto-logon if the PC also wakes unattended overnight.
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'PV-3070-NiceHash' -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force
Write-Host "Scheduled task PV-3070-NiceHash installed (runs at logon as $env:USERNAME with admin rights)."

$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask -TaskName 'PV-3070-NiceHash' -Confirm:$false -ErrorAction SilentlyContinue
Write-Host 'Scheduled task PV-3070-NiceHash removed.'

# Registers a Windows Scheduled Task that runs the ProjectWall ops cron
# every 15 minutes (liveness check, update check, health digest email).
#
# Usage (one time, from the ProjectWall folder):
#   powershell -ExecutionPolicy Bypass -File scripts\register_wall_cron.ps1
#
# Remove later with:
#   Unregister-ScheduledTask -TaskName "ProjectWall Ops Cron" -Confirm:$false

$ErrorActionPreference = "Stop"

$root   = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts\wall_cron.py"

if (-not (Test-Path $python)) { $python = "python" }  # fall back to PATH

$action  = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
            -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
            -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName "ProjectWall Ops Cron" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "ProjectWall liveness + update + health digest" -Force

Write-Output "Registered 'ProjectWall Ops Cron' (every 15 min)."
Write-Output "Python : $python"
Write-Output "Script : $script"
Write-Output ""
Write-Output "Set SMTP env vars (User scope) for email alerts to work:"
Write-Output '  [Environment]::SetEnvironmentVariable("WALL_SMTP_USER","you@gmail.com","User")'
Write-Output '  [Environment]::SetEnvironmentVariable("WALL_SMTP_PASSWORD","<gmail app password>","User")'

# Registers the daily run (scripts\daily_run.py) in the Windows Task Scheduler for the current user
# (no administrator rights needed). Run it once from the project folder, in PowerShell:
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1            # every day at 23:00
#   powershell -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1 -Time 23:30
#
# Remove the task:  Unregister-ScheduledTask -TaskName "TradingAgentPro daily" -Confirm:$false
# See docs\LOCAL_RUN.md.

param(
    [string]$Time = '23:00',
    [string]$TaskName = 'TradingAgentPro daily'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root 'scripts\daily_run.py'

# Prefer the project's virtual environment; pythonw.exe runs without a console window.
$python = Join-Path $root 'venv\Scripts\pythonw.exe'
if (-not (Test-Path $python)) { $python = Join-Path $root 'venv\Scripts\python.exe' }
if (-not (Test-Path $python)) { $python = (Get-Command python).Source }
if (-not (Test-Path (Join-Path $root '.env'))) {
    Write-Warning "No .env file in ${root}: the API keys will be missing (see .env.example)."
}

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
# StartWhenAvailable: a run missed while the PC was off starts at the next opportunity.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description 'Trading Agent Pro: collect, analyze and paper every day, stage 3 record on weekends, weekly report on Sundays (scripts\daily_run.py)' | Out-Null

Write-Host "Task '$TaskName' registered: every day at $Time with $python"
Write-Host "Test it now:   Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Logs:          $root\data\logs  (last_run.json = summary of the latest run)"

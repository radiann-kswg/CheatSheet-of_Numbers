param(
	[switch]$StopExisting = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-VenvPythonPath {
	$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
	$py = Join-Path $repoRoot '.venv\Scripts\python.exe'
	if (-not (Test-Path $py)) {
		throw "venv Python not found: $py"
	}
	return (Resolve-Path $py).Path
}

function Stop-GenerateProcesses {
	# Stop any stale generator processes to avoid duplicate writes / confusing mtime checks.
	$procs = Get-CimInstance Win32_Process |
	Where-Object { $_.CommandLine -and ($_.CommandLine -match 'tools\\generate_numbers\.py') }

	foreach ($p in $procs) {
		try {
			Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
			Write-Host "[info] Stopped stale generator PID=$($p.ProcessId)"
		}
		catch {
			Write-Host "[warn] Failed to stop PID=$($p.ProcessId): $($_.Exception.Message)"
		}
	}
}

$pythonExe = Get-VenvPythonPath
if ($StopExisting) {
	Stop-GenerateProcesses
}

& $pythonExe (Join-Path $PSScriptRoot 'refresh_and_generate_all.py')
exit $LASTEXITCODE

# Read-only Power BI environment probe. Does not modify an existing report/model.
$ErrorActionPreference = 'Stop'
$process = Get-Process PBIDesktop -ErrorAction Stop | Select-Object -First 1
$bin = Split-Path $process.Path
$engine = Get-CimInstance Win32_Process | Where-Object Name -eq 'msmdsrv.exe' | Select-Object -First 1
$result = [ordered]@{
    identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    powerBiBin = $bin
    engineCommand = $engine.CommandLine
    sharedProject = (Test-Path '\Mac\Home\Documents\ChatGPT\PBI')
    assemblies = @(Get-ChildItem -LiteralPath $bin -Filter 'Microsoft.AnalysisServices*.dll' | Select-Object -ExpandProperty Name)
}
$result | ConvertTo-Json -Depth 4 -Compress

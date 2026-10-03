# Read-only engine verification. Open and Refresh this project's PBIP in Power BI first.
# Run in Windows as the account running Power BI. No refresh/write/delete is performed here.
param(
    [Parameter(Mandatory=$true)][string]$Project,
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$Cases,
    [Parameter(Mandatory=$true)][string]$Output
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
function Get-Sha256Hex([byte[]]$Bytes) {
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try { return -join ($sha256.ComputeHash($Bytes) | ForEach-Object { $_.ToString('x2') }) }
    finally { $sha256.Dispose() }
}
$bin = Split-Path (Get-Process PBIDesktop | Select-Object -First 1).Path
foreach ($file in @('Microsoft.AnalysisServices.Server.Core.dll','Microsoft.AnalysisServices.Server.Tabular.dll','Microsoft.AnalysisServices.Server.Tabular.Json.dll','Microsoft.PowerBI.AdomdClient.dll')) {
    [void][Reflection.Assembly]::LoadFrom((Join-Path $bin $file))
}
$manifest = [IO.File]::ReadAllText((Join-Path $Project 'export_manifest.json')) | ConvertFrom-Json
if ($manifest.data_class -ne 'synthetic') { throw 'This developer verification is restricted to synthetic demos.' }
$modelPath = Join-Path $Project 'EvidenceBI.SemanticModel\model.bim'
$modelBytes = [IO.File]::ReadAllBytes($modelPath)
$modelFileSha256 = Get-Sha256Hex $modelBytes
$casesBytes = [IO.File]::ReadAllBytes($Cases)
$casesSha256 = Get-Sha256Hex $casesBytes
$expectedModel = [Microsoft.AnalysisServices.Tabular.JsonSerializer]::DeserializeDatabase([Text.Encoding]::UTF8.GetString($modelBytes),$null,[Microsoft.AnalysisServices.CompatibilityMode]::PowerBI)
$server = New-Object Microsoft.AnalysisServices.Tabular.Server
$server.Connect("Data Source=localhost:$Port;Connect Timeout=10")
try {
    $matches = @($server.Databases | Where-Object { $_.Model.Tables.Contains('FactSales') -and $_.Model.Tables.Contains('AnalysisInfo') -and $_.Model.Tables.Contains('Evidence') })
    if ($matches.Count -ne 1) { throw 'Expected one opened Evidence BI model; no existing model was modified.' }
    $actualModel = $matches[0].Model
    if ($actualModel.Tables.Count -ne $expectedModel.Model.Tables.Count -or $actualModel.Relationships.Count -ne $expectedModel.Model.Relationships.Count) { throw 'Model structure changed; rebuild/revalidate.' }
    foreach ($table in $expectedModel.Model.Tables) {
        $actualTable = $actualModel.Tables.Find($table.Name)
        if ($null -eq $actualTable -or @($actualTable.Columns | Where-Object { $_.Type.ToString() -ne 'RowNumber' }).Count -ne $table.Columns.Count) { throw 'Model columns changed.' }
        foreach ($column in $table.Columns) {
            $actualColumn = $actualTable.Columns.Find($column.Name)
            if ($null -eq $actualColumn -or $actualColumn.DataType -ne $column.DataType) { throw 'Model column types changed.' }
        }
        foreach ($measure in $table.Measures) {
            $actualMeasure = $actualTable.Measures.Find($measure.Name)
            if ($null -eq $actualMeasure -or $actualMeasure.Expression.Replace("`r",'').Trim() -ne $measure.Expression.Replace("`r",'').Trim()) { throw 'DAX changed since export.' }
        }
        if ($actualTable.Partitions.Count -ne $table.Partitions.Count) { throw 'Model partitions changed.' }
        foreach ($partition in $table.Partitions) {
            $actualPartition = $actualTable.Partitions.Find($partition.Name)
            if ($null -eq $actualPartition -or $actualPartition.Source.Expression.Replace("`r",'').Trim() -ne $partition.Source.Expression.Replace("`r",'').Trim()) { throw 'Embedded data/M changed since export.' }
        }
    }
    foreach ($relationship in $expectedModel.Model.Relationships) {
        $actual = $actualModel.Relationships.Find($relationship.Name)
        if ($null -eq $actual -or $actual.FromTable.Name -ne $relationship.FromTable.Name -or $actual.ToTable.Name -ne $relationship.ToTable.Name -or $actual.FromColumn.Name -ne $relationship.FromColumn.Name -or $actual.ToColumn.Name -ne $relationship.ToColumn.Name -or $actual.CrossFilteringBehavior -ne $relationship.CrossFilteringBehavior -or $actual.IsActive -ne $relationship.IsActive) { throw 'Relationship context changed.' }
    }
    $connection = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Port;Initial Catalog=$($matches[0].ID);Connect Timeout=10")
    $connection.Open()
    try {
        $definition = [Text.Encoding]::UTF8.GetString($casesBytes) | ConvertFrom-Json
        if (@($definition.cases).Count -eq 0) { throw 'Verification case list must not be empty.' }
        $results = @()
        foreach ($case in $definition.cases) {
            $row = 'ROW("Base", [Revenue], "Previous", [Revenue Previous Period], "Current", [Revenue Current Period], "Change", [Revenue Change], "Growth", [Revenue Growth %])'
            $query = if ([string]::IsNullOrEmpty($case.filter)) { 'EVALUATE ' + $row } else { 'EVALUATE CALCULATETABLE(' + $row + ', ' + $case.filter + ')' }
            $command = $connection.CreateCommand()
            $command.CommandText = $query
            $command.CommandTimeout = 15
            $reader = $command.ExecuteReader()
            try {
                if (-not $reader.Read()) { throw 'DAX returned no result row.' }
                $values = [ordered]@{}
                $passed = $true
                for ($i=0; $i -lt $reader.FieldCount; $i++) {
                    $name = $reader.GetName($i).Trim([char[]]'[]')
                    $value = if ($reader.IsDBNull($i)) { $null } else { $reader.GetValue($i) }
                    $expected = $case.expected.$name
                    $values[$name] = $value
                    if (($null -eq $value) -ne ($null -eq $expected)) { $passed = $false }
                    elseif ($null -ne $value) {
                        $tolerance = if ($name -eq 'Growth') { $definition.growth_ratio_tolerance } else { $definition.metric_tolerance }
                        try {
                            $difference = [decimal]$value - [decimal]$expected
                            $allowedDifference = [decimal]$tolerance
                        } catch {
                            throw "DAX result or expected value for $name is not a supported decimal number."
                        }
                        if ([Math]::Abs($difference) -gt $allowedDifference) { $passed = $false }
                    }
                }
                $results += [ordered]@{id=$case.id;passed=$passed;actual=$values;expected=$case.expected}
            } finally { $reader.Close() }
        }
        $allPassed = @($results | Where-Object { -not $_.passed }).Count -eq 0
        $report = [ordered]@{schema_version='1.0';declared_model_fingerprint=$manifest.model_fingerprint;model_file_sha256=$modelFileSha256;cases_sha256=$casesSha256;executed_at_utc=[DateTime]::UtcNow.ToString('o');execution='completed';reconciliation= $(if($allPassed){'passed'}else{'failed'});rendering='not_checked';cases=$results}
        [IO.File]::WriteAllText($Output, ($report | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
        $report | ConvertTo-Json -Depth 8
        if (-not $allPassed) { exit 2 }
    } finally { $connection.Close() }
} finally { $server.Disconnect() }

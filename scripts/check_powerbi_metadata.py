"""Validate only our synthetic model using installed Windows Power BI TOM libraries.

This developer probe neither opens UI nor modifies an Analysis Services database.
It stages a compressed copy in Windows Temp with small commands to avoid guest CLI limits.
"""

import argparse
import base64
import gzip
import json
import subprocess
import sys
from pathlib import Path


def command(vm_id, script):
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            [
                "/usr/local/bin/prlctl",
                "exec",
                vm_id,
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            timeout=55,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Windows probe timed out; no engine validation was completed.") from None
    if result.returncode:
        # Do not include the encoded input/model in exceptions.
        raise RuntimeError(
            "Windows probe failed: " + result.stderr.decode("utf-8", errors="replace")[:1500]
        )
    return result.stdout.decode("utf-8", errors="replace").strip()


def check(project, vm_id):
    manifest = json.loads((project / "export_manifest.json").read_text())
    if manifest.get("data_class") != "synthetic":
        raise RuntimeError("This developer transfer probe is restricted to synthetic demo exports.")
    model = (project / "EvidenceBI.SemanticModel/model.bim").read_bytes()
    compressed = base64.b64encode(gzip.compress(model)).decode("ascii")
    target = r"C:\Windows\Temp\EvidenceBI-TOM-" + manifest["model_fingerprint"][:16] + ".b64"
    command(vm_id, f"[IO.File]::WriteAllText('{target}', '')")
    for offset in range(0, len(compressed), 1600):
        command(
            vm_id, f"[IO.File]::AppendAllText('{target}', '{compressed[offset : offset + 1600]}')"
        )
    script = r"""
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$bin = Split-Path (Get-Process PBIDesktop | Select-Object -First 1).Path
foreach($file in @('Microsoft.AnalysisServices.Server.Core.dll','Microsoft.AnalysisServices.Server.Tabular.dll','Microsoft.AnalysisServices.Server.Tabular.Json.dll')){[void][Reflection.Assembly]::LoadFrom((Join-Path $bin $file))}
$bytes=[Convert]::FromBase64String([IO.File]::ReadAllText('__TARGET__'))
$stream=New-Object IO.MemoryStream(,$bytes)
$gzip=New-Object IO.Compression.GzipStream($stream,[IO.Compression.CompressionMode]::Decompress)
$reader=New-Object IO.StreamReader($gzip,[Text.Encoding]::UTF8)
$json=$reader.ReadToEnd()
$db=[Microsoft.AnalysisServices.Tabular.JsonSerializer]::DeserializeDatabase($json,$null,[Microsoft.AnalysisServices.CompatibilityMode]::PowerBI)
[ordered]@{status='metadata_deserialized';model_fingerprint='__FP__';tables=@($db.Model.Tables|ForEach-Object{$_.Name});measure_count=($db.Model.Tables|ForEach-Object{$_.Measures.Count}|Measure-Object -Sum).Sum;execution='not_checked';rendering='not_checked'}|ConvertTo-Json -Depth 3 -Compress
""".replace("__TARGET__", target).replace("__FP__", manifest["model_fingerprint"])
    return json.loads(command(vm_id, script))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--vm-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = check(args.project, args.vm_id)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + "\n")
    print(text)

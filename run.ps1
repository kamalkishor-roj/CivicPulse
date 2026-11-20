param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ArgsList
)

$pythonExe = if (Test-Path ".\.venv\Scripts\python.exe") {
    (Resolve-Path ".\.venv\Scripts\python.exe").Path
} elseif (Test-Path "$env:USERPROFILE\anaconda3\python.exe") {
    "$env:USERPROFILE\anaconda3\python.exe"
} else {
    "python"
}

if (-not $ArgsList -or $ArgsList.Count -eq 0) {
    & $pythonExe src/pipeline.py run --mode mock --max-records 400 --engine duckdb
} else {
    & $pythonExe src/pipeline.py @ArgsList
}

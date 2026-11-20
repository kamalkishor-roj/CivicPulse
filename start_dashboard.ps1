$pythonExe = if (Test-Path ".\.venv\Scripts\python.exe") {
    (Resolve-Path ".\.venv\Scripts\python.exe").Path
} elseif (Test-Path "$env:USERPROFILE\anaconda3\python.exe") {
    "$env:USERPROFILE\anaconda3\python.exe"
} else {
    "python"
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   CivicPulse React & Leaflet Intelligence Dashboard      " -ForegroundColor Cyan
Write-Host "   Open in Browser: http://localhost:8000                 " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan

& $pythonExe -m uvicorn app.api:app --host 0.0.0.0 --port 8000

@echo off
REM start.bat - يفتح بيئة العمل جاهزة بنقرة واحدة
REM Opens the project with .venv already activated

cd /d "%~dp0"

if not exist ".venv\Scripts\Activate.ps1" (
    echo ERROR: .venv not found in this folder.
    echo Run:  python -m venv .venv
    pause
    exit /b 1
)

powershell -NoExit -ExecutionPolicy Bypass -Command "& { & '.\.venv\Scripts\Activate.ps1'; Write-Host ''; Write-Host '  NoorTrade Agent - environment ready' -ForegroundColor Green; Write-Host ''; Write-Host '  python agent.py "your question"' -ForegroundColor Gray; Write-Host '  python agent.py --lang both "your question"' -ForegroundColor Gray; Write-Host '  python agent.py                 (interactive)' -ForegroundColor Gray; Write-Host '' }"

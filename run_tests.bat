@echo off
rem ============================================
rem  my_site one-click test runner
rem  Runs the full pytest suite and generates
rem  an HTML report (report.html) in this folder.
rem ============================================
cd /d "%~dp0"

python -m pytest test_site.py -v --html=report.html --self-contained-html

echo.
echo ============================================
if exist report.html (
    echo Done. Report: report.html
) else (
    echo Test run failed - no report generated.
)
echo ============================================
pause

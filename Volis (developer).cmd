@echo off
rem Volis with its developer pages. Customer copies ship without this file.
cd /d "%~dp0"
if exist volis.exe (
    start "Volis (developer)" volis.exe --developer
) else (
    start "Volis (developer)" .venv\Scripts\python.exe -m volis --developer
)

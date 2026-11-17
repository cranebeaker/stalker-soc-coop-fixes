@echo off
rem Run from the opt-in package root. Pass -GamePath "D:\...\game" -Players 5 if desired.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\start_server_1_8.ps1" %*
pause

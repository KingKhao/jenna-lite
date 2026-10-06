@echo off
rem Removes Jenna Lite's shortcuts and stops her. Your Brain notes folder is NOT deleted.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"

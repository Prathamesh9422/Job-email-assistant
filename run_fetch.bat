@echo off
cd /d "%~dp0"
"C:\Program Files\Python314\python.exe" fetch_job.py >> fetch_log.txt 2>&1

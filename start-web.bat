@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo ============================================
echo  novel-ledger Web 工作台
echo  启动后请用浏览器打开 http://127.0.0.1:8801
echo  按 Ctrl+C 停止
echo ============================================
"C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe" web\server.py --port 8801
pause

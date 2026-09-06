@echo off
cd /d "%~dp0"
title novel-ledger Web Workbench
echo ============================================
echo  novel-ledger Web 工作台
echo  数据全在本机 · 关闭本窗口即停止服务
echo ============================================

rem 端口已被占用 = 服务已在跑，直接开浏览器
netstat -ano | findstr ":8801" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo 检测到服务已经在运行，直接为你打开浏览器…
    start "" http://127.0.0.1:8801/ui/
    timeout /t 4 /nobreak >nul
    exit /b 0
)

rem 3 秒后自动打开浏览器（给服务留启动时间；explorer 免引号坑）
start "" /min cmd /c "timeout /t 3 /nobreak >nul & explorer http://127.0.0.1:8801/ui/"

set PYTHONUTF8=1

rem 依次尝试：本机 Python 3.12 → WorkBuddy 托管 → PATH（拉黑商店假别名）
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    echo [启动] 使用本机 Python 3.12…
    "%LocalAppData%\Programs\Python\Python312\python.exe" web\server.py --port 8801
    goto end
)
if exist "C:\Users\lhx\.workbuddy\binaries\python\versions\3.13.12\python.exe" (
    echo [启动] 使用 WorkBuddy 托管 Python…
    "C:\Users\lhx\.workbuddy\binaries\python\versions\3.13.12\python.exe" web\server.py --port 8801
    goto end
)
set "PYEXE="
for /f "delims=" %%p in ('where python 2^>nul') do (
    echo %%p | findstr /i "WindowsApps" >nul 2>&1 || set "PYEXE=%%p"
)
if defined PYEXE (
    echo [启动] 使用 PATH 中的 Python…
    "%PYEXE%" web\server.py --port 8801
    goto end
)
echo 没有找到可用的 Python。请安装 Python 3.9+（勾选 Add to PATH）后重试。
:end
echo.
echo 服务已停止。
pause

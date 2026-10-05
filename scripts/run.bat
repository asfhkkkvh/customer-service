@echo off
chcp 65001 >nul
cd /d "%~dp0.."

echo ============================================
echo   多智能体客服系统 - 一键启动 (FastAPI 进程内运行)
echo ============================================
echo.

echo 启动 Web 服务  http://localhost:5000 ...
start "Web-5000" cmd /k "python -m webapp.app"

echo.
echo 已启动服务窗口。浏览器打开 http://localhost:5000 使用。
echo 注意：图在 Web 服务进程内运行，checkpoint 落盘 data/checkpoints.db，
echo       无需再单独启动 LangGraph 服务。
echo 关闭这个新开的窗口 = 停止服务。
pause

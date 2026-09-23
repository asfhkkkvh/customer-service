@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   多智能体客服系统 - 一键启动 (FastAPI + LangGraph)
echo ============================================
echo.

echo [1/2] 启动 LangGraph 服务  http://127.0.0.1:2024 ... 
start "LangGraph-2024" cmd /k "langgraph dev --no-browser --host 127.0.0.1 --port 2024"

timeout /t 3 /nobreak >nul

echo [2/2] 启动 Web 服务      http://localhost:5000 ...
start "Web-5000" cmd /k "python web_app.py"

echo.
echo 已启动两个服务窗口。浏览器打开 http://localhost:5000 使用。
echo 注意：不要关闭这两个新开的窗口；关闭 = 停止对应服务。
pause
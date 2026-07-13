@echo off
chcp 65001 >nul
title 闸门开闭信息页面服务

echo =====================================================
echo   闸门开闭信息页面服务
echo =====================================================
echo   页面地址: http://localhost:8010/gate_info.html
echo =====================================================
echo.

cd /d "%~dp0"
python page_server.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 启动失败，请检查是否已安装 Python ^>= 3.9
    pause
)

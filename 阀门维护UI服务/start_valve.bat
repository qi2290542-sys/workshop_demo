@echo off
chcp 65001 >nul
title 阀门维护 UI 服务

echo =====================================================
echo   阀门维护 UI 服务
echo =====================================================
echo   页面地址: http://localhost:3401/
echo =====================================================
echo.

cd /d "%~dp0"
node server.js

if %errorlevel% neq 0 (
    echo.
    echo [错误] 启动失败，请检查是否已安装 Node.js
    pause
)

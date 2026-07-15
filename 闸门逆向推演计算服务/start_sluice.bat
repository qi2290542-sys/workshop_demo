@echo off
chcp 65001 >nul
title 闸门逆向推演 API 服务端

echo =====================================================
echo   闸门逆向推演 API 服务端
echo =====================================================
echo   接口文档: http://localhost:9527/docs
echo   优化接口: POST http://localhost:9527/api/sluice/optimize
echo =====================================================
echo.

cd /d "%~dp0"
sluice_server.exe

if %errorlevel% neq 0 (
    echo.
    echo [错误] 启动失败，请确认 sluice_server.exe 与 algorithm\algorithm\sluice\sluice.exe 均存在
    pause
)

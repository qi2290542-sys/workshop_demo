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

python sluice_server.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 启动失败，请检查:
    echo   1. 是否已安装 Python ^>= 3.9
    echo   2. 是否已安装依赖: pip install -r requirements_server.txt
    pause
)

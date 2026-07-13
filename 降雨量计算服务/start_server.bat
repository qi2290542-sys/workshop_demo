@echo off
chcp 65001 >nul
title 淹没水深计算系统 API 服务端

echo =====================================================
echo   淹没水深计算系统 API 服务端 v2.0
echo =====================================================
echo   接口文档: http://localhost:8000/docs
echo   状态查询: http://localhost:8000/status
echo   计算接口: POST http://localhost:8000/calculate
echo =====================================================
echo.

python server.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 启动失败，请检查:
    echo   1. 是否已安装 Python ^>= 3.9
    echo   2. 是否已安装依赖: pip install -r requirements_server.txt
    pause
)

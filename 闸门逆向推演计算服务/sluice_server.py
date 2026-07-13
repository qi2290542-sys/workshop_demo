#!/usr/bin/env python3
"""
闸门逆向推演系统 - HTTP API 服务端
======================================
调用 sluice.exe optimize（反向推演：目标流量 → 开度方案）

核心入参 (POST /api/sluice/optimize):
  target_discharge : 目标泄流量 (m³/s)   —— 必填
  upstream_level   : 上游水位 (m)         —— 必填
  downstream_level : 下游水位 (m)         —— 必填
  num_gates        : 闸孔数               —— 必填
其余几何/水力参数均有默认值

启动: python sluice_server.py
文档: http://localhost:9527/docs
"""

from __future__ import annotations
import json
import re
import subprocess
import traceback
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# 固定路径配置
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
SLUICE_EXE     = str(BASE_DIR / "algorithm" / "algorithm" / "sluice" / "sluice.exe")
SLUICE_EXE_DIR = str(BASE_DIR / "algorithm" / "algorithm" / "sluice")

# ─────────────────────────────────────────────────────────────────────────────
# FastAPI 应用
# ─────────────────────────────────────────────────────────────────────────────
import socket
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn


def _local_ip() -> str:
    """获取本机局域网 IP"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


_HOST_IP = _local_ip()
_PORT    = 9527

app = FastAPI(
    title="闸门逆向推演 API",
    version="1.0",
    description=(
        "调用 sluice.exe 反向推演（目标流量 → 闸门开度方案）。\n\n"
        "**核心入参**: 目标泄流量、上游水位、下游水位、闸孔数\n\n"
        "**返回**: 多个可行开度方案（openings / actual_discharge / error_percent 等）"
    ),
    servers=[
        {"url": f"http://{_HOST_IP}:{_PORT}", "description": "局域网"},
        {"url": f"http://localhost:{_PORT}",   "description": "本机"},
    ],
)

# 允许浏览器跨域调用（WIM 页面 fetch 此服务）
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class OptimizeRequest(BaseModel):
    # 核心必填参数
    target_discharge: float = Field(..., gt=0, description="目标泄流量 (m³/s)")
    upstream_level:   float = Field(..., description="上游水位 (m)")
    downstream_level: float = Field(..., description="下游水位 (m)")
    num_gates:        int   = Field(5, ge=1, description="闸孔数")

    # 几何 / 水力参数（有默认值）
    gate_width:            float = Field(5.0,   gt=0,  description="单孔宽度 (m)")
    gate_bottom_elevation: float = Field(0.0,          description="闸底高程 (m)")
    max_opening:           float = Field(3.0,   gt=0,  description="最大开度 (m)")
    min_opening:           float = Field(0.2,   ge=0,  description="最小开度 (m)")
    flow_coeff_free:       float = Field(0.65,         description="自由出流系数")
    flow_coeff_submerged:  float = Field(0.85,         description="淹没出流系数")
    pier_width:            float = Field(0.5,          description="闸墩宽度 (m)")
    pier_shape:            str   = Field("rounded",    description="闸墩头部形状")
    k_adj:                 float = Field(0.9,          description="邻孔开启修正系数")
    xi_p:                  float = Field(0.5,          description="闸墩收缩系数")
    xi_a:                  float = Field(0.5,          description="岸墩收缩系数")
    use_side_contraction:  bool  = Field(False,        description="启用闸墩侧收缩修正")
    strategy:              str   = Field("uniform",    description="优化策略")


def run_sluice_optimize(req: OptimizeRequest) -> dict:
    """构建命令行调用 sluice.exe optimize，返回解析后的 JSON"""
    cmd = [
        SLUICE_EXE, "optimize",
        "--target-discharge",      str(req.target_discharge),
        "--upstream-level",        str(req.upstream_level),
        "--downstream-level",      str(req.downstream_level),
        "--num-gates",             str(req.num_gates),
        "--gate-width",            str(req.gate_width),
        "--gate-bottom-elevation", str(req.gate_bottom_elevation),
        "--max-opening",           str(req.max_opening),
        "--min-opening",           str(req.min_opening),
        "--flow-coeff-free",       str(req.flow_coeff_free),
        "--flow-coeff-submerged",  str(req.flow_coeff_submerged),
        "--pier-width",            str(req.pier_width),
        "--pier-shape",            req.pier_shape,
        "--k-adj",                 str(req.k_adj),
        "--xi-p",                  str(req.xi_p),
        "--xi-a",                  str(req.xi_a),
        "--strategy",              req.strategy,
        "--json",
    ]
    if req.use_side_contraction:
        cmd.append("--use-side-contraction")

    proc = subprocess.run(
        cmd,
        capture_output=True,
        cwd=SLUICE_EXE_DIR,
        timeout=120,
    )
    stdout_str = proc.stdout.decode("utf-8", errors="replace")
    stderr_str = proc.stderr.decode("gbk",   errors="replace")

    # 解析 stdout 中的 JSON
    stdout_clean = stdout_str.strip()
    try:
        data = json.loads(stdout_clean)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", stdout_clean, re.DOTALL)
        if m:
            data = json.loads(m.group())
        else:
            raise RuntimeError(
                f"无法解析 sluice.exe 输出:\nstdout: {stdout_clean[:500]}\nstderr: {stderr_str[:500]}"
            )

    # sluice.exe 自身返回 success=false 时透传错误
    if data.get("success") is False:
        raise ValueError(data.get("error", "逆向推演失败"))

    return data


# ─────────────────────────────────────────────────────────────────────────────
# API 端点
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/sluice/optimize", summary="闸门逆向推演")
def api_optimize(req: OptimizeRequest):
    """
    反向推演：给定目标泄流量与水位，推算满足目标的多组可行开度方案。

    返回结构与 sluice.exe 一致，含 `solutions[]`：
    - `openings`：各孔开度数组（米）
    - `num_gates_open`：开启孔数
    - `actual_discharge`：实际泄流量
    - `error_percent`：与目标误差
    - `plan_type`：方案类型
    """
    try:
        return run_sluice_optimize(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"推演失败: {e}\n\n{traceback.format_exc()}",
        )


@app.get("/status", summary="服务状态")
def api_status():
    return {
        "service":    "闸门逆向推演 API v1.0",
        "sluice_exe": SLUICE_EXE,
        "exe_exists": Path(SLUICE_EXE).exists(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 启动
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  闸门逆向推演 API 服务端 v1.0")
    print("=" * 60)
    print(f"  接口文档: http://{_HOST_IP}:{_PORT}/docs")
    print(f"  状态查询: http://{_HOST_IP}:{_PORT}/status")
    print(f"  推演接口: POST http://{_HOST_IP}:{_PORT}/api/sluice/optimize")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=_PORT)

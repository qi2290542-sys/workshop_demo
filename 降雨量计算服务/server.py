#!/usr/bin/env python3
"""
淹没水深计算系统 V2.0 - HTTP API 服务端
======================================
固定输入:
  DEM = data/input/shenzhen_dem.tif（深圳预裁地形，EPSG:4326，范围约 113.75~114.01°E / 22.45~22.75°N）

可定制参数 (POST /calculate):
  boundary_file     : data/input/ 下的边界文件名（默认深圳2-大.kml）
                      支持 .shp / .kml / .geojson 格式
  rainfall_mode     : custom | dusuruui | haikui | meranti
  total_rainfall    : 10~500 mm  (custom 模式)
  rainfall_duration : 1~96 小时  (custom 模式)
  rainfall_pattern  : uniform | increasing | decreasing | peak (custom 模式)

输出 JSON 写入: data/output/WimDataFilesCheck/

启动: python server.py
文档: http://localhost:8000/docs  http://10.66.10.134
"""

from __future__ import annotations
import json
import os
import shutil
import tempfile
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal, Optional

import subprocess
import shapefile as pyshp

# ─────────────────────────────────────────────────────────────────────────────
# 固定路径配置
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
DEM_PATH   = str(BASE_DIR / "data" / "input" / "shenzhen_dem.tif")
INPUT_DIR  = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output" / "WimDataFilesCheck"

DEFAULT_BOUNDARY  = "矢量边界测试3-深圳2-大.kml"
GRID_STEP         = 10
SIM_HOURS_CUSTOM  = 48
SIM_HOURS_TYPHOON = 96

# flood.exe 路径
FLOOD_EXE     = str(BASE_DIR / "algorithm" / "algorithm" / "flooding_calculation" / "flood.exe")
FLOOD_EXE_DIR = str(BASE_DIR / "algorithm" / "algorithm" / "flooding_calculation")

# API 参数 → flood.exe 参数映射
MODE_MAP: dict[str, str] = {
    "custom":   "custom",
    "dusuruui": "杜苏芮",
    "haikui":   "海葵",
    "meranti":  "莫兰蒂",
}
PATTERN_MAP: dict[str, str] = {
    "uniform":    "均匀型",
    "increasing": "递增型",
    "decreasing": "递减型",
    "peak":       "中间峰值型",
}

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
_PORT    = 8000

app = FastAPI(
    title="淹没水深计算系统 API",
    version="2.0",
    description=(
        "调用淹没水深概化算法（与 V2.0 exe 相同算法）。\n\n"
        "**固定 DEM**: data/input/shenzhen_dem.tif（深圳预裁地形）\n\n"
        "**可选边界**: data/input/ 下任意 .shp/.kml/.geojson 文件\n\n"
        "**输出**: JSON 时序数据写入 data/output/WimDataFilesCheck/"
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

# 将淹没计算产物目录通过 HTTP 暴露，供 WIM 引擎以 URL 方式加载
# （WIM 引擎/三维页面可能运行在其他机器或浏览器沙箱，无法访问本机磁盘路径）
# 访问示例: http://<host>:8000/output/dem_original.tif
from fastapi.staticfiles import StaticFiles
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")


class CalcRequest(BaseModel):
    boundary_file: str = Field(
        DEFAULT_BOUNDARY,
        description="data/input/ 目录下的边界文件名，支持 .shp/.kml/.geojson。默认: 深圳大范围KML",
    )
    rainfall_mode: Literal["custom", "dusuruui", "haikui", "meranti"] = Field(
        "custom",
        description="降雨模式: custom=自定义 | dusuruui=杜苏芮(55→30m/s) | haikui=海葵(50→25m/s) | meranti=莫兰蒂(60→35m/s)",
    )
    total_rainfall: float = Field(100.0, ge=10, le=500, description="总降雨量mm，仅custom有效")
    rainfall_duration: int = Field(24, ge=1, le=96, description="降雨历时小时，仅custom有效，须≤48h")
    rainfall_pattern: Literal["uniform", "increasing", "decreasing", "peak"] = Field(
        "uniform", description="雨型: uniform均匀 | increasing递增 | decreasing递减 | peak中间峰值"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 边界文件读取（SHP / KML / GeoJSON）
# ─────────────────────────────────────────────────────────────────────────────

def _read_shp(path: str):
    from shapely.geometry import shape
    p = Path(path)
    prj = p.with_suffix(".prj")
    crs_wkt = prj.read_text(encoding="utf-8", errors="ignore").strip() if prj.exists() else None
    features = []
    with pyshp.Reader(path) as sf:
        field_names = [f[0] for f in sf.fields[1:]]
        for sr in sf.shapeRecords():
            geom = shape(sr.shape.__geo_interface__)
            rec  = dict(zip(field_names, sr.record))
            name = str(
                rec.get("name") or rec.get("NAME") or
                next((v for v in rec.values() if isinstance(v, str) and v), None) or "整体"
            )
            features.append((geom, name))
    return features, crs_wkt


def _read_kml(path: str):
    from shapely.geometry import Polygon, MultiPolygon
    NS = "http://www.opengis.net/kml/2.2"

    def _parse_coords(elem):
        pts = []
        for token in (elem.text or "").strip().split():
            parts = token.split(",")
            if len(parts) >= 2:
                try:
                    pts.append((float(parts[0]), float(parts[1])))
                except ValueError:
                    pass
        return pts

    def _poly_from_elem(el):
        outer = el.find(f"{{{NS}}}outerBoundaryIs/{{{NS}}}LinearRing/{{{NS}}}coordinates")
        if outer is None:
            return None
        shell = _parse_coords(outer)
        if len(shell) < 3:
            return None
        holes = [_parse_coords(h) for h in
                 el.findall(f"{{{NS}}}innerBoundaryIs/{{{NS}}}LinearRing/{{{NS}}}coordinates")]
        try:
            return Polygon(shell, [h for h in holes if len(h) >= 3])
        except Exception:
            return None

    tree = ET.parse(path)
    root = tree.getroot()
    features = []
    for pm in root.iter(f"{{{NS}}}Placemark"):
        ne = pm.find(f"{{{NS}}}name")
        name = (ne.text or "整体").strip() if ne is not None else "整体"
        polys = []
        for pe in pm.findall(f"{{{NS}}}Polygon"):
            p = _poly_from_elem(pe)
            if p and p.is_valid:
                polys.append(p)
        for mg in pm.findall(f"{{{NS}}}MultiGeometry"):
            for pe in mg.findall(f"{{{NS}}}Polygon"):
                p = _poly_from_elem(pe)
                if p and p.is_valid:
                    polys.append(p)
        if not polys:
            continue
        geom = polys[0] if len(polys) == 1 else MultiPolygon(polys)
        features.append((geom, name))
    return features, None   # KML 默认 WGS84


def _read_geojson(path: str):
    from shapely.geometry import shape
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    features = []
    items = gj.get("features", [gj]) if gj.get("type") == "FeatureCollection" else [gj]
    for feat in items:
        geom = shape(feat.get("geometry") or feat)
        props = feat.get("properties") or {}
        name = str(
            props.get("name") or props.get("NAME") or
            next((v for v in props.values() if isinstance(v, str) and v), None) or "整体"
        )
        features.append((geom, name))
    return features, None


def read_boundary(filename: str):
    path = str(INPUT_DIR / filename)
    if not os.path.exists(path):
        raise ValueError(f"边界文件不存在: data/input/{filename}")
    ext = Path(filename).suffix.lower()
    if ext == ".shp":
        return _read_shp(path)
    elif ext in (".kml", ".kmz"):
        return _read_kml(path)
    elif ext == ".geojson":
        return _read_geojson(path)
    else:
        raise ValueError(f"不支持的格式: {ext}（支持 .shp / .kml / .geojson）")


# ─────────────────────────────────────────────────────────────────────────────
# 边界格式转换：将任意格式的 features 写成临时 SHP（flood.exe 只接受 SHP）
# ─────────────────────────────────────────────────────────────────────────────

WGS84_WKT = ('GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
             'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
             'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]')


def _to_temp_shp(features, crs_wkt=None) -> tuple[str, str]:
    """
    将 [(geom, name), ...] 写成临时 Shapefile，供 flood.exe 使用。
    返回 (shp_path, tmp_dir)
    """
    tmp_dir = tempfile.mkdtemp(prefix="wim_bnd_")
    shp_path = str(Path(tmp_dir) / "boundary.shp")

    with pyshp.Writer(shp_path, shapeType=5) as w:   # 5 = POLYGON
        w.field("name", "C", 80)
        for geom, name in features:
            w.shape(geom.__geo_interface__)
            w.record(name=name)

    # 写 .prj（坐标系描述）
    prj_path = shp_path.replace(".shp", ".prj")
    Path(prj_path).write_text(crs_wkt or WGS84_WKT, encoding="utf-8")

    return shp_path, tmp_dir


def _clip_dem_by_features(features, crs_wkt=None) -> tuple[str, str]:
    """
    按边界要素（输入 shp/边界）裁剪 DEM，生成小块临时 tif。
    使用 rasterio.mask crop=True：裁到边界范围，多边形外设为 nodata。
    避免把整张大 DEM 交给 flood.exe（否则输出 dem_original.tif 会过大）。
    返回 (clip_tif_path, tmp_dir)
    """
    import rasterio
    from rasterio.mask import mask as rio_mask
    import pyproj
    from shapely.ops import transform as shp_transform

    tmp_dir   = tempfile.mkdtemp(prefix="wim_demclip_")
    clip_path = str(Path(tmp_dir) / "dem_clip.tif")

    with rasterio.open(DEM_PATH) as ds:
        dem_crs_pp = pyproj.CRS.from_wkt(ds.crs.to_wkt())
        wgs84      = pyproj.CRS.from_epsg(4326)
        bnd_crs    = pyproj.CRS.from_wkt(crs_wkt) if crs_wkt else wgs84

        # 将边界几何转到 DEM 的坐标系（rasterio.mask 要求同 CRS）
        transformer = pyproj.Transformer.from_crs(bnd_crs, dem_crs_pp, always_xy=True)
        geoms = [
            shp_transform(transformer.transform, geom).__geo_interface__
            for geom, _ in features
        ]

        # crop=True 裁到边界包围盒；filled 默认 True，多边形外填 nodata
        out_img, out_tf = rio_mask(ds, geoms, crop=True)

        profile = ds.profile.copy()
        profile.update(
            height=out_img.shape[1],
            width=out_img.shape[2],
            transform=out_tf,
        )
        profile.pop("BIGTIFF", None)  # 小文件无需 BigTIFF
        with rasterio.open(clip_path, "w", **profile) as out:
            out.write(out_img)

    return clip_path, tmp_dir


# ─────────────────────────────────────────────────────────────────────────────
# 主计算逻辑（调用 flood.exe）
# ─────────────────────────────────────────────────────────────────────────────

def run_flood_calculation(req: CalcRequest) -> dict:
    is_typhoon = req.rainfall_mode != "custom"
    sim_hours  = SIM_HOURS_TYPHOON if is_typhoon else SIM_HOURS_CUSTOM

    if not is_typhoon and req.rainfall_duration > sim_hours:
        raise ValueError(f"降雨历时 {req.rainfall_duration}h 不能大于模拟时长 {sim_hours}h")

    # ── 1. 读取边界并转为临时 SHP（flood.exe 只接受 SHP）─────────────────────
    features, crs_wkt = read_boundary(req.boundary_file)
    if not features:
        raise ValueError(f"边界文件 {req.boundary_file} 未找到有效要素")

    shp_file, shp_tmp_dir = _to_temp_shp(features, crs_wkt)

    # 按输入边界(shp)裁剪 DEM，得到小块 DEM 作为 flood.exe 的 --dem
    dem_file, dem_tmp_dir = _clip_dem_by_features(features, crs_wkt)

    try:
        # ── 2. 清空旧输出目录 ────────────────────────────────────────────────
        if OUTPUT_DIR.exists():
            shutil.rmtree(OUTPUT_DIR)
        OUTPUT_DIR.mkdir(parents=True)

        # ── 3. 构建 flood.exe 命令 ────────────────────────────────────────────
        cmd = [
            FLOOD_EXE,
            "calc",
            "--mode",     MODE_MAP[req.rainfall_mode],
            "--dem",      dem_file,
            "--boundary", shp_file,
            "--output",   str(OUTPUT_DIR),
            "--hours",    str(sim_hours),
            "--step",     str(GRID_STEP),
            "--json",     # 结果摘要以 JSON 输出到 stdout
        ]
        if req.rainfall_mode == "custom":
            cmd += [
                "--total-rain", str(req.total_rainfall),
                "--duration",   str(req.rainfall_duration),
                "--pattern",    PATTERN_MAP[req.rainfall_pattern],
            ]

        # ── 4. 执行 flood.exe ─────────────────────────────────────────────────
        proc = subprocess.run(
            cmd,
            capture_output=True,
            cwd=FLOOD_EXE_DIR,
            timeout=600,
        )
        stdout_str = proc.stdout.decode("utf-8", errors="replace")
        stderr_str = proc.stderr.decode("gbk",   errors="replace")

        if proc.returncode != 0:
            raise RuntimeError(
                f"flood.exe 返回错误 (exit={proc.returncode})\n"
                f"stderr: {stderr_str[:2000]}"
            )

        # ── 5. 解析 stdout 中的 JSON 摘要 ────────────────────────────────────
        stdout_clean = stdout_str.strip()
        try:
            summary = json.loads(stdout_clean)
        except json.JSONDecodeError:
            import re
            m = re.search(r'\{.*\}', stdout_clean, re.DOTALL)
            if m:
                summary = json.loads(m.group())
            else:
                raise RuntimeError(
                    f"无法解析 flood.exe 输出:\nstdout: {stdout_clean[:500]}\nstderr: {stderr_str[:500]}"
                )

    finally:
        shutil.rmtree(shp_tmp_dir, ignore_errors=True)
        shutil.rmtree(dem_tmp_dir, ignore_errors=True)

    # ── 6. 组装响应 ───────────────────────────────────────────────────────────
    json_count = len(list(OUTPUT_DIR.glob("GridIDArray*.json")))
    return {
        "status":        "success",
        "boundary_file": req.boundary_file,
        "rainfall_mode": req.rainfall_mode,
        "sim_hours":     sim_hours,
        "total_grids":   summary.get("grid_count", 0),
        "flooded_count": summary.get("flooded_count", 0),
        "max_depth_m":   summary.get("max_depth", 0),
        "output_dir":    str(OUTPUT_DIR),
        "json_pairs":    json_count,
        "exe_summary":   summary,
    }


# ─────────────────────────────────────────────────────────────────────────────
# API 端点
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/calculate", summary="执行淹没水深计算")
def api_calculate(req: CalcRequest):
    """触发淹没水深概化计算，结果 JSON 写入本地 output 目录。"""
    try:
        return run_flood_calculation(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算失败: {e}\n\n{traceback.format_exc()}")


# ─────────────────────────────────────────────────────────────────────────────
# 脚本对齐接口（降雨模拟 main.js 使用）
#   POST /api/flood/calc         入参 {total_rain, duration, pattern(中文)}
#   GET  /api/flood/frame-depth  查询某帧某经纬度处水深
# ─────────────────────────────────────────────────────────────────────────────

# 中文雨型 → 英文（PATTERN_MAP 为 英文→中文，此处反转）
_PATTERN_ZH2EN = {v: k for k, v in PATTERN_MAP.items()}

# (lon, lat) → cellid 缓存（播放期间监测坐标固定，只需查一次）
_cellid_cache: dict = {}


class FloodCalcRequest(BaseModel):
    total_rain: float = Field(100.0, description="总降雨量 mm")
    duration:   int   = Field(24,    description="降雨历时 小时")
    pattern:    str   = Field("均匀型", description="雨型（中文）: 均匀型/递增型/递减型/中间峰值型")


@app.post("/api/flood/calc", summary="降雨淹没计算（脚本对齐接口）")
def api_flood_calc(req: FloodCalcRequest):
    """
    降雨模拟脚本使用的接口。接收中文雨型，内部转为 custom 模式调用 flood.exe。
    返回 {success, output_dir, flooded_count, max_depth}。
    """
    pattern_en = _PATTERN_ZH2EN.get(req.pattern, "uniform")
    total = max(10.0, min(float(req.total_rain), 500.0))
    dur   = max(1,   min(int(req.duration),   96))
    calc_req = CalcRequest(
        rainfall_mode="custom",
        total_rainfall=total,
        rainfall_duration=dur,
        rainfall_pattern=pattern_en,
    )
    try:
        result = run_flood_calculation(calc_req)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"计算失败: {e}"}
    return {
        "success":       True,
        "output_dir":    result["output_dir"],
        "output_url":    f"http://{_HOST_IP}:{_PORT}/output",
        "flooded_count": result.get("flooded_count", 0),
        "max_depth":     result.get("max_depth_m", 0),
    }


def _find_cellid_at(lon: float, lat: float):
    """在 flood_depth.shp 中查找包含 (lon, lat) 的网格 cellid（带缓存）"""
    key = (round(lon, 6), round(lat, 6))
    if key in _cellid_cache:
        return _cellid_cache[key]

    shp_path = OUTPUT_DIR / "flood_depth.shp"
    if not shp_path.exists():
        return None

    from shapely.geometry import shape, Point
    pt = Point(lon, lat)
    cellid = None
    with pyshp.Reader(str(shp_path)) as sf:
        field_names = [f[0] for f in sf.fields[1:]]
        cid_idx = field_names.index("cellid") if "cellid" in field_names else 0
        for sr in sf.shapeRecords():
            bbox = sr.shape.bbox  # [minx, miny, maxx, maxy]
            if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                continue
            if shape(sr.shape.__geo_interface__).contains(pt):
                cellid = str(sr.record[cid_idx])
                break

    _cellid_cache[key] = cellid
    return cellid


@app.get("/api/flood/frame-depth", summary="查询某帧某坐标处水深（脚本对齐接口）")
def api_frame_depth(frame: int, lon: float, lat: float):
    """
    返回第 frame 帧、坐标 (lon, lat) 处的淹没水深。
    - 网格未淹没：depth = 0
    - 无对应网格 / 数据缺失：depth = null
    """
    cellid = _find_cellid_at(lon, lat)
    if cellid is None:
        return {"depth": None}

    grid_path = OUTPUT_DIR / f"GridIDArray{frame}.json"
    val_path  = OUTPUT_DIR / f"ValueArray{frame}.json"
    if not grid_path.exists() or not val_path.exists():
        return {"depth": None}

    ids  = json.loads(grid_path.read_text(encoding="utf-8")).get("gridIDArray", [])
    vals = json.loads(val_path.read_text(encoding="utf-8")).get("valueArray", [])
    try:
        idx = ids.index(cellid)
        return {"depth": float(vals[idx])}
    except ValueError:
        return {"depth": 0.0}  # 该网格该帧未淹没


@app.get("/status", summary="服务状态")
def api_status():
    json_count = (
        len(list(OUTPUT_DIR.glob("GridIDArray*.json"))) if OUTPUT_DIR.exists() else 0
    )
    bnd_files = (
        [p.name for p in INPUT_DIR.iterdir()
         if p.suffix.lower() in {".shp", ".kml", ".kmz", ".geojson"}]
        if INPUT_DIR.exists() else []
    )
    return {
        "service":                  "淹没水深计算系统 API v2.0",
        "dem":                      DEM_PATH,
        "default_boundary":         DEFAULT_BOUNDARY,
        "available_boundary_files": bnd_files,
        "output_dir":               str(OUTPUT_DIR),
        "existing_timestep_count":  json_count,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("  淹没水深计算系统 API 服务端 v2.0")
    print("=" * 60)
    print(f"  接口文档: http://{_HOST_IP}:{_PORT}/docs")
    print(f"  状态查询: http://{_HOST_IP}:{_PORT}/status")
    print(f"  计算接口: POST http://{_HOST_IP}:{_PORT}/calculate")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=_PORT)
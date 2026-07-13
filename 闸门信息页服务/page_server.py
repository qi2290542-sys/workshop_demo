#!/usr/bin/env python3
"""
闸门开闭信息页面服务
======================================
在本机 IP 上以 HTTP 静态方式提供 降雨模拟/gate_info.html，
供 WDP 场景的 App.WindowUI 以 iframe 方式嵌入显示。

启动: python page_server.py
页面: http://<本机IP>:8010/gate_info.html
"""
from __future__ import annotations
import http.server
import os
import socket
from functools import partial

# 服务目录 = 本脚本所在目录（降雨模拟/），gate_info.html 就在这里
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
PORT = 8010


def _local_ip() -> str:
    """获取本机局域网 IP"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    """带 CORS 头的静态文件处理器（便于跨源 iframe / fetch）"""

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, fmt, *args):
        # 精简日志
        print("  [page]", fmt % args)


def main():
    ip = _local_ip()
    handler = partial(CORSRequestHandler, directory=DIRECTORY)
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), handler) as httpd:
        print("=" * 60)
        print("  闸门开闭信息页面服务")
        print("=" * 60)
        print(f"  页面地址: http://{ip}:{PORT}/gate_info.html")
        print(f"  本机访问: http://localhost:{PORT}/gate_info.html")
        print("=" * 60)
        httpd.serve_forever()


if __name__ == "__main__":
    main()

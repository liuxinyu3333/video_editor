# -*- coding: utf-8 -*-
"""
img_to_url.py
将“本地图片目录”批量转换为“GPT 可访问的公网 URL（基于本地HTTP+隧道）”。

使用前提：
1) 在 server_root 目录下启动本地静态服务器（举例）：
   PowerShell:
       cd E:\coin_works\project\frames_output
       python -m http.server 8000 --bind 0.0.0.0
2) 打开内网穿透（任选其一）得到一个 HTTPS 公网域名 public_base：
   - cloudflared:
       cloudflared tunnel --url http://localhost:8000
       # 会得到形如 https://<random>.trycloudflare.com
   - ngrok:
       ngrok http 8000
       # 会得到形如 https://xxxx.ngrok.io

调用示例：
   python img_to_url.py ^
     --image-dir "E:\coin_works\project\frames_output\提阿非羅大人TiaBTC\2025-09-05-提阿非羅大人TiaBTC-1" ^
     --server-root "E:\coin_works\project\frames_output" ^
     --public-base "https://abc123.trycloudflare.com" ^
     --out "urls.txt"

输出：
- 标准输出打印前若干条 URL
- 若指定 --out 则把所有 URL 写入该文件（逐行）
"""

from __future__ import annotations
import argparse
from pathlib import Path
from urllib.parse import quote
from typing import Iterable, List

# ------------------------------
# 可选：保留 imgbb 兜底上传（默认不启用）
# ------------------------------
# import requests, base64
# IMGBB_API_KEY = "在需要时填入你的 imgbb key"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
Server_root = Path(r"E:\coin_works\project\frames_output")
PUBLIC_BASE = r"https://felt-diagram-kits-verde.trycloudflare.com"
def is_image(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in IMAGE_EXTS

def build_public_urls(image_folder: Path, recursive: bool = False) -> List[str]:
    """
    将 image_folder 下的图片文件映射为可公网访问的 URL 列表。
    - public_base: 隧道提供的公网基地址（结尾不要斜杠），例如：
        https://abc123.trycloudflare.com  或  https://xxxx.ngrok.io
    - server_root: 你启动 http.server 的目录（HTTP 根），必须是 image_folder 的祖先目录
    - image_folder: 某一组图片所在的子目录
    - recursive: 是否递归遍历子目录（默认否）
    """
    image_folder = image_folder.resolve()
    server_root = Server_root
    public_base = PUBLIC_BASE
    # 校验关系：image_folder 必须在 server_root 之下
    try:
        rel_dir = image_folder.relative_to(server_root)
    except ValueError:
        raise ValueError(f"[错误] image_folder 必须是 server_root 的子目录。\n"
                         f"  server_root = {server_root}\n"
                         f"  image_folder = {image_folder}")

    # 选择遍历方式
    files: Iterable[Path]
    if recursive:
        files = (p for p in image_folder.rglob("*") if is_image(p))
    else:
        files = (p for p in image_folder.glob("*") if is_image(p))

    urls: List[str] = []
    for p in sorted(files):
        rel_path = p.resolve().relative_to(server_root)
        # 对每一级路径做 URL 编码，保证中文/空格/特殊字符可用
        encoded = "/".join(quote(part) for part in rel_path.parts)
        urls.append(f"{public_base}/{encoded}")
    return urls

# ------------------------------
# （可选）imgbb 兜底：在 URL 拉取失败时再走上传
# ------------------------------
# def upload_to_imgbb(image_path: Path, api_key: str = IMGBB_API_KEY) -> str:
#     """
#     把本地图片上传到 imgbb，返回公开 URL。
#     仅在你需要兜底时启用（注意：这会产生额外文本 token 与不稳定性问题）。
#     """
#     url = "https://api.imgbb.com/1/upload"
#     with open(image_path, "rb") as f:
#         b64 = base64.b64encode(f.read())
#     payload = {"key": api_key, "image": b64}
#     resp = requests.post(url, data=payload, timeout=30)
#     resp.raise_for_status()
#     data = resp.json()
#     return data["data"]["url"]

def main():

    image_dir = Path(r"E:\coin_works\project\frames_output\比特币军长\2025-09-16-比特币军长-1")
    urls = build_public_urls(image_dir)

    # 打印部分示例
    print(f"共发现 {len(urls)} 张图片。示例 URL：")
    for u in urls[:5]:
        print("  ", u)
    if len(urls) > 5:
        print("  ...")
    out = "test_out.txt"
    # 写出到文件
    if out:
        out_path = Path(out)
        out_path.write_text("\n".join(urls), encoding="utf-8")
        print(f"已写入：{out_path.resolve()}")

if __name__ == "__main__":
    main()

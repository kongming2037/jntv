#!/usr/bin/env python3
"""国内直播源抓取聚合器.

从 sources.yaml 里配置的上游 M3U 订阅源抓取直播源,合并去重后输出标准 M3U.

用法:
    python3 scraper.py                  # 抓取并输出到 output/iptv.m3u
    python3 scraper.py -o my.m3u        # 指定输出文件
    python3 scraper.py --check          # 抓取后对每个源做连通性抽查(慢)
    python3 scraper.py --sources a.yaml # 指定上游配置文件

输出 M3U 可直接填入 IPTV 播放器(TiviMate / IPTV Pro / VLC / NekoBox 等)的订阅地址.
"""
import argparse
import concurrent.futures
import os
import re
import sys
import time
import urllib.request
from typing import Optional, List, Tuple, Dict, Set

try:
    import yaml
except ImportError:
    print("需要 PyYAML: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

BASE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) live-tv-scraper/1.0"}

# 频道名规范化:去掉常见的清晰度/后缀噪音,便于去重
NOISE_RE = re.compile(r"(高清|超清|标清|HD|FHD|\[.*?\]|\(.*?\))", re.I)


def norm_name(name: str) -> str:
    name = NOISE_RE.sub("", name).strip()
    return re.sub(r"\s+", " ", name)


def fetch_text(url: str, timeout: int = 25) -> Optional[str]:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        # 依次尝试多种编码
        for enc in ("utf-8", "gbk", "gb18030"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  [失败] {url} -> {e}", file=sys.stderr)
        return None


def parse_m3u(text: str) -> List[Tuple[str, str, str]]:
    """解析 M3U 文本,返回 [(频道名, 分组, 播放地址)] 列表."""
    items = []
    name, group = None, ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            m = re.search(r'group-title="([^"]*)"', line)
            group = m.group(1) if m else ""
            # 频道名取最后一个逗号之后
            name = line.rsplit(",", 1)[-1].strip() or "未知频道"
        elif line.startswith("#"):
            continue
        elif name:
            url = line
            # 过滤明显无效的地址
            if url.startswith(("http://", "https://", "rtmp://", "rtsp://")):
                items.append((name, group, url))
            name = None
    return items


def check_url(url: str, timeout: int = 10) -> bool:
    """连通性检查:验证流地址可连接.

    先 HEAD 探活,失败则 GET 读取一小段数据.对 m3u8 播放列表会进一步
    验证内容是否为有效的播放列表(包含 #EXTM3U 或 #EXT-X-).
    注意:本检查反映运行机器所在本地网络的连通情况.
    """
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status >= 400:
                return False
    except Exception:
        pass  # HEAD 失败不直接判死,继续用 GET 验证
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status >= 400:
                return False
            data = r.read(4096)
            # m3u8 地址必须返回播放列表内容
            if ".m3u8" in url.split("?")[0]:
                head = data[:400].decode("utf-8", errors="ignore")
                if "#EXTM3U" not in head and "#EXT-X-" not in head:
                    return False
            return len(data) > 0
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="国内直播源抓取聚合器")
    ap.add_argument("--sources", default=os.path.join(BASE, "sources.yaml"))
    ap.add_argument("-o", "--output", default=os.path.join(BASE, "output", "iptv.m3u"))
    ap.add_argument("--check", "--check-local", action="store_true",
                    help="连通性测试:只保留本地网络可连接的源(较慢)")
    ap.add_argument("--check-unicom", action="store_true",
                    help="同 --check,旧名称,保留兼容")
    ap.add_argument("--workers", type=int, default=20)
    args = ap.parse_args()

    with open(args.sources, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    upstreams = cfg.get("upstreams", [])
    print(f"上游源 {len(upstreams)} 个,开始抓取...")
    all_items: List[Tuple[str, str, str, str]] = []  # (规范名, 原名, 分组, url)

    def grab(u):
        text = fetch_text(u["url"])
        if not text:
            return u["name"], []
        items = parse_m3u(text)
        print(f"  [ok] {u['name']}: {len(items)} 个频道")
        return u["name"], items

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for src_name, items in ex.map(grab, upstreams):
            for name, group, url in items:
                all_items.append((norm_name(name), name, group or src_name, url))

    # 去重:同一规范名保留第一个出现的 URL(上游按优先级排序)
    seen: Dict[str, Tuple[str, str, str]] = {}
    for norm, name, group, url in all_items:
        key = norm
        if key not in seen:
            seen[key] = (name, group, url)
    # 同一规范名下 URL 去重(不同清晰度源)
    uniq_urls: Dict[str, Set[str]] = {}
    final: List[Tuple[str, str, str]] = []
    for norm, (name, group, url) in seen.items():
        s = uniq_urls.setdefault(norm, set())
        if url not in s:
            s.add(url)
            final.append((name, group, url))

    print(f"合并去重后 {len(final)} 个频道")

    if args.check or args.check_unicom:
        print("连通性测试中(只保留可连接的源)...")
        ok = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(lambda t: (t, check_url(t[2])), final))
        before = len(final)
        final = [(n, g, u) for (n, g, u), alive in results if alive]
        ok = len(final)
        print(f"测试 {before} 个,存活 {ok} 个,已剔除 {before - ok} 个死链")

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, group, url in sorted(final, key=lambda t: t[0]):
            safe_group = group.replace('"', "")
            f.write(f'#EXTINF:-1 group-title="{safe_group}",{name}\n{url}\n')
    print(f"已写入 {args.output} ({len(final)} 个频道)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

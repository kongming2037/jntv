/**
 * 国内直播源订阅服务 (Cloudflare Worker)
 *
 * 部署后访问 https://<你的worker>.workers.dev/iptv.m3u 即可得到实时合并的 M3U 播放列表.
 * 每次请求时从上游源实时抓取合并,无需手动更新.
 *
 * 部署: Cloudflare Dashboard → Workers & Pages → Create Worker → 粘贴本文件 → Save and deploy
 */

// 上游 M3U 订阅源(按优先级排序).部署后可直接改这里增删.
// (2026-10-08 更新2:vbskycn 改走 jsDelivr 镜像,raw.githubusercontent.com 在国内手机网络下常被墙)
const UPSTREAMS = [
  { name: "vbskycn-IPv4", url: "https://cdn.jsdelivr.net/gh/vbskycn/iptv@master/tv/iptv4.m3u" },
  { name: "vbskycn-IPv6", url: "https://cdn.jsdelivr.net/gh/vbskycn/iptv@master/tv/iptv6.m3u" },
  { name: "iptv-org-CN", url: "https://iptv-org.github.io/iptv/countries/cn.m3u" },
  { name: "iptv-org-HK", url: "https://iptv-org.github.io/iptv/countries/hk.m3u" },
  { name: "iptv-org-TW", url: "https://iptv-org.github.io/iptv/countries/tw.m3u" },
  { name: "iptv-org-MO", url: "https://iptv-org.github.io/iptv/countries/mo.m3u" },
  { name: "iptv-org-ZHO", url: "https://iptv-org.github.io/iptv/languages/zho.m3u" },
];

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) live-tv-sub/1.0";

function normName(name) {
  return name.replace(/(高清|超清|标清|HD|FHD|\[.*?\]|\(.*?\))/gi, "").trim().replace(/\s+/g, " ");
}

function parseM3U(text, fallbackGroup) {
  const items = [];
  let name = null, group = fallbackGroup;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith("#EXTINF")) {
      const gm = line.match(/group-title="([^"]*)"/);
      if (gm) group = gm[1];
      name = line.split(",").pop().trim() || "未知频道";
    } else if (line.startsWith("#")) {
      continue;
    } else if (name) {
      if (/^(https?|rtmp|rtsp):\/\//i.test(line)) items.push({ name, group, url: line });
      name = null;
    }
  }
  return items;
}

async function fetchUpstream(u) {
  try {
    const r = await fetch(u.url, { headers: { "User-Agent": UA } });
    if (!r.ok) return [];
    const text = await r.text();
    return parseM3U(text, u.name).map((it) => ({ ...it, src: u.name }));
  } catch (e) {
    return [];
  }
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname !== "/iptv.m3u" && url.pathname !== "/") {
      return new Response("Not Found", { status: 404 });
    }
    if (UPSTREAMS.length === 0) {
      return new Response(
        "#EXTM3U\n# 上游源未配置:请编辑 Worker 代码中的 UPSTREAMS 数组\n",
        { headers: { "Content-Type": "application/x-mpegurl; charset=utf-8" } }
      );
    }
    const results = await Promise.all(UPSTREAMS.map(fetchUpstream));
    const seen = new Map();
    for (const items of results) {
      for (const it of items) {
        const key = normName(it.name);
        if (!seen.has(key)) seen.set(key, it);
      }
    }
    const sorted = [...seen.values()].sort((a, b) => a.name.localeCompare(b.name, "zh"));
    let m3u = "#EXTM3U\n";
    for (const it of sorted) {
      const g = (it.group || "").replace(/"/g, "");
      m3u += `#EXTINF:-1 group-title="${g}",${it.name}\n${it.url}\n`;
    }
    return new Response(m3u, {
      headers: {
        "Content-Type": "application/x-mpegurl; charset=utf-8",
        "Cache-Control": "public, max-age=3600",
        "Access-Control-Allow-Origin": "*",
      },
    });
  },
};

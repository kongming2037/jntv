# jntv - 本地网络可用性验证的国内直播源

自动从多个上游 M3U 订阅源抓取国内电视直播源,经连通性测试过滤后生成标准 M3U 播放列表。
只保留验证通过的源,确保在本地网络下可播放。

## 文件说明

| 文件 | 说明 |
|------|------|
| `scraper.py` | 抓取核心:并发抓取上游、解析 M3U、去重、输出 |
| `sources.yaml` | 上游订阅源配置(按优先级排序) |
| `tv-worker.js` | Cloudflare Worker 订阅服务:部署后得到订阅链接 |
| `output/iptv.m3u` | 抓取生成的播放列表(运行后产生) |

## 快速开始

```bash
# 1. 安装依赖
pip install pyyaml

# 2. 编辑 sources.yaml,填入可用的上游 M3U 地址

# 3. 运行抓取(含连通性测试,只保留本地网络可播放的源)
python3 scraper.py --check-local

# 4. 输出 output/iptv.m3u,直接导入播放器
```

> **注意**:连通性测试反映的是运行机器所在本地网络的连通情况,在哪台机器上跑,就代表哪个网络。
> 在其他网络下测试通过的源,在你的网络下大概率可用,但运营商内网源可能例外。

### 进阶用法

```bash
# 不做连通性测试,只抓取合并(快)
python3 scraper.py

# 指定输出文件
python3 scraper.py -o /tmp/my.m3u

# 指定上游配置
python3 scraper.py --sources my-sources.yaml
```

## 订阅链接(推荐)

把 `tv-worker.js` 部署到 Cloudflare Worker 后,得到类似这样的订阅地址:

```
https://你的worker.workers.dev/iptv.m3u
```

播放器(TiviMate / IPTV Pro / VLC / Kodi)里添加"网络 M3U 播放列表",填入该地址即可。
Worker 每次被请求时实时从上游抓取合并,源永远是新的,无需手动更新。

部署步骤(Cloudflare Dashboard):
1. Workers & Pages → Create → Create Worker → 取名如 `live-tv`
2. Edit code → 粘贴 `tv-worker.js` 内容 → Save and deploy
3. (可选)绑定自定义域名,如 `tv.你的域名.com`

## 定时更新(备选方案)

如果不用 Worker,也可以用 cron 每天跑一次抓取,把 M3U 推送到某个静态托管:

```cron
0 6 * * * /usr/bin/python3 /path/to/live-tv-scraper/scraper.py -o /var/www/iptv.m3u
```

## 注意事项

- 上游源可能失效,`sources.yaml` 里多配几个源做冗余
- 部分源有防盗链,抓取时已带浏览器 UA,仍失败可换源
- 仅供个人学习测试使用

# 烟酒商城 Mini App（静态页）

Telegram 机器人「烟酒商城（小程序）」用的静态网页，托管在 GitHub Pages。页面只读取本仓库的 `site/catalog.json`；下单通过 Telegram `sendData` 交给机器人，**机器人按自己的商品目录重新计价**，确认后才生成订单。页面不收款、不显示库存。

## 目录
- `site/` — 网页（index.html / app.js / style.css）和 `catalog.json`（由工作流生成；初始为空目录）。
- `tools/build_catalog.py` — 从 h1hcs.com 公开商城（吉隆坡仓）抓商品，用与机器人**同一份**代码分类、生成商品码，导出 catalog.json（名称、单位、规格、价格、原价、图片地址；无库存）。只有商品数据变化才改写文件；抓取失败或商品数骤减 50% 以上时保留旧文件。
- `tools/catalog_view.py` — （v4）页面显示顺序：香烟 / 酒水（白酒→洋酒→葡萄酒→啤酒→其他）/ 重振雄风 / 槟榔 在前，同品牌放一起、价格从高到低（v4.1 起：香烟保持与华润万家商城完全相同的顺序，`catalog_view.MALL_ORDER`）；「X（整箱）」并进单件「X」的详情里加购（两者商品码不变）。只重排 items 并加 `view`，`build_catalog.py` 的 `VIEW = False` 即回退。
- `tools/vendor/` — 与机器人相同的模块：`shop_cart.py`（逐字节相同）、`shop_miniapp.py`、`catalog_live.py`（唯一差别：`AGENT` 改为运行时从密钥读取）。见 `VENDOR_SHA256.txt`。
- `tools/secret_scan.py` — 密钥/ID 扫描（推送前本地跑一次；工作流每次也跑）。
- `.github/workflows/catalog-pages.yml` — 每小时（UTC 第 23 分）构建；变化时提交 `site/catalog.json` 并部署 Pages；手动运行或推送时也部署。

## 首次设置（账号 h1hcs-shop，仓库名 shop；全程网页操作，不建任何 token）
1. 本地先跑：`python tools/test_build_catalog.py && python tools/secret_scan.py .`（0 finding）。
2. github.com/new：Owner `h1hcs-shop`，Repository name `shop`，**Public**，不勾选 README/.gitignore/license。
3. 空仓库页点「uploading an existing file」：把 `site/`、`tools/` 两个文件夹和 `README.md`、`VENDOR_SHA256.txt`、`REPO_SHA256.txt` 拖进去（保持目录结构；不要拖 `__pycache__`），Commit to `main`。
4. Add file → Create new file：文件名 `.gitignore`，粘贴本目录同名文件内容，Commit。
5. Settings → Secrets and variables → Actions → New repository secret：Name `STOREFRONT_AGENT`，Secret = 商城 storefront 的 agent 参数（由运维在生产机本地读取后直接粘贴到这个框里，不经过聊天、不写进任何文件）。
6. Settings → Pages → Build and deployment → Source 选 **GitHub Actions**。
7. **最后**：Add file → Create new file：文件名输入 `.github/workflows/catalog-pages.yml`（输入 `/` 会自动变成目录），粘贴本目录同名文件内容，Commit to `main` → 自动触发第一次构建+部署。
8. Actions 页确认 catalog-and-pages 两个 job 都绿；打开 `https://h1hcs-shop.github.io/shop/`（**末尾斜杠**）和 `…/shop/catalog.json` 确认有商品。若提交步骤报 403：Settings → Actions → General → Workflow permissions 选 Read and write，再 Re-run。
9. 网址交给机器人运维写入 `config.json` 的 `shop_miniapp_url`（需另行批准）。

## 注意
- 公开仓库 60 天无活动会停用定时任务；价格变化会自动提交，另外 30 天无提交时写一次 `.github/keepalive`。
- 定时任务可能延迟几分钟；价格以机器人确认页为准。
- 不要往仓库里放 token、用户 ID、订单/会员数据、客服私人信息。

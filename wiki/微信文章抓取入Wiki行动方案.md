# 微信公众号文章抓取入Wiki库 — 完整行动方案

> 2026-05-01 整理 | 核心目标：微信公众号文章 → 标准MD → Wiki库

## 一、为什么必须解决微信渠道

| 维度 | 官方网站 (edu.chengdu.gov.cn) | 微信公众号 (mp.weixin.qq.com) |
|------|------|------|
| 更新速度 | 慢1-3天 | 第一时间发布 |
| 内容丰富度 | 通知原文，格式规范 | 通知+解读+图解+问答 |
| 来源覆盖 | 仅教育局 | 教育局+头部大V+自媒体 |
| 典型代表 | 6份官方政策原文 | 成都教育发布(官方)+溜爸(大V)+更多 |
| 反爬难度 | 瑞数JS(已突破) | 需cookie/扫码(已有工具) |

**结论**：微信渠道更新更快、内容更丰富、来源更多元，是必须打通的第二条数据管道。

---

## 二、两个工具深度对比

### aturx/wechat-article-exporter (k12_rag现有)

| 维度 | 评价 |
|------|------|
| GitHub | aturx/wechat-article-exporter |
| 界面 | ❌ CLI无界面，手动填cookie |
| 登录 | 手动抓cookie → 填入wechat_cookies.json |
| 导出格式 | 仅Markdown |
| HTML还原 | ❌ 丢失排版/表格/图片位置 |
| 搜索公众号 | ❌ YAML硬编码account_id |
| API | ❌ 无 |
| Docker | ✅ aturx/wechat-article-exporter:latest |
| 优势 | 与k12_rag watcher代码已对接(18个.py模块) |

### wechat-article/wechat-article-exporter (推荐)

| 维度 | 评价 |
|------|------|
| GitHub | wechat-article/wechat-article-exporter (8.3K Star) |
| 界面 | ✅ Web界面，可视化操作 |
| 登录 | ✅ 微信扫码登录(需有公众号) |
| 在线版 | ✅ down.mptext.top 即用 |
| 导出格式 | ✅ 6种：HTML/MD/JSON/Excel/TXT/DOCX |
| HTML还原 | ✅ 100%还原排版样式 |
| 搜索公众号 | ✅ Web界面关键字搜索 |
| API | ✅ RESTful开放API (4个端点) |
| Docker | ✅ ghcr.io/wechat-article/wechat-article-exporter:latest |
| 评论/阅读量 | ✅ 支持(需额外Credentials) |

**判断：新版全面碾压旧版，尤其在HTML还原和API对接上。**

---

## 三、新版API完整文档

### 基础地址
`https://down.mptext.top`（在线版）或私有部署地址

### 认证
- Header: `X-Auth-Key: <密钥>`
- 密钥获取：扫码登录后自动生成
- 有效期：**4天**，过期需重新扫码

### 端点一览

| 端点 | 方法 | 功能 | 关键参数 |
|------|------|------|----------|
| `/api/public/v1/account` | GET | 搜索公众号 | `keyword=关键词` |
| `/api/public/v1/article` | GET | 获取文章列表(分页) | `fakeid=xxx&begin=0&size=20` |
| `/api/public/v1/download` | GET | 下载文章内容 | `url=文章URL&format=markdown` |
| `/api/public/v1/accountbyurl` | GET | URL反查公众号 | `url=文章URL` |
| `/api/public/v1/authkey` | GET | 验证密钥有效性 | 无 |

### 典型调用流程
```
1. 扫码登录 → 获取 X-Auth-Key
2. GET /api/public/v1/account?keyword=成都教育发布 → 获取fakeid
3. GET /api/public/v1/article?fakeid=xxx&begin=0&size=20 → 文章列表
4. GET /api/public/v1/download?url=文章URL&format=markdown → 下载MD
```

### 导出格式选择
- `html` → 100%还原排版（**推荐用于复杂表格/图解文章**）
- `markdown` → 纯文本（**推荐用于入Wiki库的标准格式**）
- `json` → 结构化数据（**推荐用于数据分析/入库**）

---

## 四、Docker私有部署方案

### docker-compose.yml
```yaml
services:
  wechat-article-exporter:
    image: ghcr.io/wechat-article/wechat-article-exporter:latest
    container_name: wechat-article-exporter
    ports:
      - "3006:3000"
    volumes:
      - ./data:/app/.data    # 持久化：登录状态/缓存/导出文件
    restart: always
```

### HTTPS要求（关键！）
| 访问方式 | 能否扫码 | 原因 |
|---------|---------|------|
| localhost / 127.0.0.1 | ✅ | 本地地址不受secure Cookie限制 |
| http://IP:3006 | ❌ | 微信Cookie有secure属性，HTTP无法携带 |
| https://your-domain | ✅ | HTTPS支持secure Cookie |

**必须配置反向代理+HTTPS**：Nginx/Caddy + Let's Encrypt SSL

### 前置条件
- 需要一个微信公众号（个人订阅号即可，免费注册）
- 需要域名+SSL证书（如部署到服务器）
- 或只在本地localhost使用（无需HTTPS）

---

## 五、三条行动路径

### Path A：在线版快速验证（推荐先做）

```
1. 你有微信公众号 → 去 down.mptext.top 扫码登录
2. 搜索"成都教育发布" "溜爸" → 勾选政策相关文章
3. 导出MD格式 → 下载到本地
4. 用虾处理：frontmatter标准化 + 图片本地化 → 入Wiki
```

- **优点**：零部署，5分钟出结果
- **缺点**：auth-key 4天过期，每次手动操作
- **适用**：快速验证可行性、小批量导出

### Path B：Docker私有部署（中期目标）

```
1. 在8.216.39.30服务器上部署Docker
2. 配置Nginx反向代理 + HTTPS (已有Nginx)
3. 扫码登录 → Web界面操作
4. 对接k12_rag watcher自动处理
```

- **优点**：持久运行、API可编程、自动化
- **缺点**：需配置HTTPS、需域名、需重写watcher对接逻辑
- **适用**：长期运营、大批量、自动化采集

### Path C：混合方案（推荐最终方案）

```
Phase 1（立即可做）：
  在线版批量导出 → 手动/半自动入Wiki

Phase 2（1周内）：
  写Python脚本调用API自动下载
  → 复用k12_rag/src/wechat/processor.py标准化
  → 一键入Wiki + 同步服务器

Phase 3（后续升级）：
  Docker私有部署 → 全自动采集+处理+入库
```

---

## 六、微信文章 → 标准MD → Wiki库 转换规范

### 标准frontmatter模板（微信文章）

```yaml
---
title: "文章标题"
source: "微信公众号"
account: "成都教育发布"          # 公众号名称
url: "https://mp.weixin.qq.com/s/xxx"
publish_date: "2026-04-16"
archive_date: "2026-05-01"
policy_year: 2026
policy_type: "义务教育"          # 义务教育/幼儿园/中考/随迁/其他
city: "成都市"
province: "四川省"
trust_level: "A"                # 微信官方号=A, 大V=B, 其他=C
extraction_method: "wechat-article-exporter"
format: "markdown"              # markdown/html/json
---
```

### 图片处理规则
1. 微信图片CDN: mmbiz.qpic.cn（有防盗链，需带Referer下载）
2. 下载后本地化：`wiki/policies/images/文章标题_01.png`
3. MD中图片引用改为本地路径
4. 已有image_handler.py可复用

### 文章分类入Wiki目录
| 类型 | Wiki目录 | 示例 |
|------|----------|------|
| 官方政策通知 | wiki/policies/ | 2026_成都市_义务教育招生入学通知.md |
| 官方政策解读 | wiki/policies/ | 2026_成都市_幼儿园招生政策解读.md |
| 大V分析文章 | wiki/reference/ | 2026_溜爸_学区分析.md |
| 官方视频精校 | wiki/media/ | EP01_义务教育招生入学政策解读_精校版.md |

---

## 七、k12_rag现有代码资产评估

### 可直接复用
| 模块 | 路径 | 用途 |
|------|------|------|
| processor.py | src/wechat/processor.py | MD标准化+frontmatter+入库 |
| image_handler.py | src/wechat/image_handler.py | 图片下载+本地化路径替换 |
| deduplicator.py | src/wechat/deduplicator.py | 文章去重 |
| watcher.py | src/wechat/watcher.py | 文件监听+自动处理 |

### 需要改造
| 内容 | 原因 |
|------|------|
| exporter_integration.py | 对接aturx → 改为对接wechat-article的API |
| docker-compose.wechat.yml | Docker镜像+配置全换 |
| wechat_cookies.json | 不再需要手动cookie |
| wechat_accounts.yaml | 不再需要硬编码account_id |

### 需要新建
| 内容 | 说明 |
|------|------|
| scripts/fetch_wechat_article.py | 调用API自动下载的CLI脚本（类似fetch_edu_chengdu.py） |
| Wiki入箱脚本 | processor输出 → wiki目录 → index.html更新 → 服务器同步 |

---

## 八、立即行动建议

### 第一步：验证在线版（5分钟）
1. 你用微信公众号管理员微信 → 扫码登录 down.mptext.top
2. 搜索"成都教育发布" → 选几篇政策文章 → 导出MD
3. 丢给我处理 → 验证完整链路：MD → frontmatter标准化 → 图片本地化 → 入Wiki → 同步服务器

### 第二步：写API脚本（1-2小时）
等第一步验证通过后，我写 `scripts/fetch_wechat_article.py`：
- 输入：公众号名称 + auth-key
- 调用API搜索 → 获取文章列表 → 批量下载MD
- 自动标准化frontmatter + 图片本地化
- 一键入Wiki + 同步服务器

### 第三步：Docker部署（可选升级）
等第二步稳定后，部署Docker版到服务器，实现全自动采集。

---

## 九、与官网抓取的协同

| 数据源 | 抓取工具 | 入Wiki流程 |
|--------|----------|------------|
| edu.chengdu.gov.cn | fetch_edu_chengdu.py (DrissionPage) | 抓取 → MD标准化 → Wiki |
| mp.weixin.qq.com (官方号) | wechat-article-exporter API | 下载MD → 标准化 → Wiki |
| mp.weixin.qq.com (大V号) | wechat-article-exporter API | 下载MD → 标准化 → Wiki |
| 其他网页 | WebFetch / web-content-archiver | 下载 → MD标准化 → Wiki |

**所有渠道最终都汇聚到统一的Wiki库，共享同一套frontmatter标准和同步流程。**

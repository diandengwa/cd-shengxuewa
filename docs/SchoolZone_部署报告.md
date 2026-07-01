# SchoolZone 部署报告

## 部署时间
2026-07-01

## 服务器信息
- IP: 162.14.74.251
- OS: Ubuntu (VM-0-11-ubuntu)
- Python: 3.12.3
- Nginx: 1.24.0

## 部署内容

### 1. 文件结构
```
/opt/schoolzone/
  index.html              (17K, 前端页面)
  server.py               (7.4K, Python HTTP服务脚本)
  setup_ssl.sh            (SSL证书申请脚本)
  api/
    _shared.py            (21K, 地址解析+规则匹配引擎)
    index.py              (7K, 原Vercel API, 保留参考)
    all_districts_2026.json (605K, 划片数据)
    schools_meta.json     (259K, 学校元数据)
  data/
    all_districts_2026.json (605K, 数据副本)
    feedbacks.json        (纠错存储)
  static/                 (静态文件目录, 预留)
```

### 2. Python 服务 (端口 8001)
- 服务脚本: /opt/schoolzone/server.py
- 基于 http.server.HTTPServer，替代 Vercel serverless
- 路由:
  - GET  /api/health    - 健康检查
  - GET  /api/stats     - 数据统计
  - GET  /api/match     - 地址匹配查询
  - POST /api/feedback  - 纠错提交
  - GET  /              - 前端页面
  - GET  /static/*      - 静态文件

### 3. Systemd 服务
- 配置文件: /etc/systemd/system/schoolzone.service
- 状态: active (running), enabled (开机自启)
- 自动重启: Restart=always, RestartSec=3

### 4. Nginx 配置
- 配置文件: /etc/nginx/conf.d/xuequ.conf
- HTTP (port 80): 反代到 127.0.0.1:8001
- HTTPS (port 443): 反代到 127.0.0.1:8001 (临时自签名证书)
- 包含 /api/ 和 /static/ 路径反代
- 包含 certbot ACME 验证路径

### 5. SSL 证书
- 当前: 自签名证书 (临时, /etc/nginx/ssl/xuequ.crt)
- 正式证书: 需配置 DNS 后运行 setup_ssl.sh 申请

## 验证结果

| 项目 | 状态 | 说明 |
|------|------|------|
| Systemd 服务 | OK | active, enabled |
| 健康检查 | OK | HTTP 200 |
| 数据统计 | OK | 866所学校, 23个区县 |
| 地址匹配 | OK | 3个测试地址全部匹配成功 |
| 纠错提交 | OK | POST /api/feedback 成功 |
| Nginx HTTP代理 | OK | port 80 |
| Nginx HTTPS代理 | OK | port 443 (自签名) |
| 前端页面 | OK | 正常加载 |

### Match 测试结果
1. 锦江区花园街10号 -> 成都师范附属小学万科分校 (置信度 0.8)
2. 武侯区桐梓林 -> 成都市桐梓林小学 (置信度 0.8)
3. 青羊区青华路10号 -> 成都市实验小学青华分校 (置信度 0.8)

## 待完成事项

### 1. 配置 DNS 记录
在 DNSPod (dnspod.net) 添加 A 记录:
- 记录类型: A
- 主机记录: xuequ
- 记录值: 162.14.74.251

### 2. 申请正式 SSL 证书
DNS 生效后, SSH 到服务器运行:
```bash
ssh -i ~/.ssh/tent.pem root@162.14.74.251
bash /opt/schoolzone/setup_ssl.sh
```

## 常用运维命令
```bash
# 查看服务状态
systemctl status schoolzone

# 重启服务
systemctl restart schoolzone

# 查看日志
journalctl -u schoolzone -f

# 重载 nginx
nginx -t && systemctl reload nginx

# 更新前端页面
scp -i ~/.ssh/tent.pem index.html root@162.14.74.251:/opt/schoolzone/index.html

# 更新数据
scp -i ~/.ssh/tent.pem all_districts_2026.json root@162.14.74.251:/opt/schoolzone/api/all_districts_2026.json
scp -i ~/.ssh/tent.pem all_districts_2026.json root@162.14.74.251:/opt/schoolzone/data/all_districts_2026.json
systemctl restart schoolzone
```

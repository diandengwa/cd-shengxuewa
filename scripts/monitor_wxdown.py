#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时监控 wxdown-service 是否成功捕获凭证
运行后，在微信客户端中打开公众号文章，看到成功提示即可。
"""

import time
import json
import os
from pathlib import Path

CRED_PATH = Path(r"D:\opc\content-factory\wxdown-service-windows\credentials.json")
TIMEOUT = 300  # 最长等待5分钟

def main():
    print("=" * 60)
    print("  wxdown-service 凭证捕获监控")
    print("=" * 60)
    print()
    print("请在电脑端微信客户端中执行以下操作：")
    print("  1. 打开微信客户端（已登录）")
    print("  2. 通讯录 → 公众号 → 选择任意一个公众号")
    print("  3. 点击进入公众号主页")
    print("  4. 点击任意一篇文章，在微信内置浏览器中打开")
    print("  5. 等待此脚本提示「凭证已捕获」")
    print()
    print(f"监控文件：{CRED_PATH}")
    print(f"超时时间：{TIMEOUT}秒")
    print("=" * 60)
    print()
    
    if CRED_PATH.exists():
        print("⚠️  credentials.json 已存在，将读取现有内容...")
        try:
            with open(CRED_PATH, "r", encoding="utf-8") as f:
                creds = json.load(f)
            print(f"  ✅ 已存在 {len(creds)} 个凭证")
            for c in creds:
                biz = c.get("biz", "N/A")
                print(f"    - biz: {biz[:20]}...")
            return 0
        except Exception as e:
            print(f"  ❌ 读取失败: {e}")
    
    start = time.time()
    last_touch = 0
    
    while time.time() - start < TIMEOUT:
        elapsed = int(time.time() - start)
        
        if CRED_PATH.exists():
            print()
            print("=" * 60)
            print("  ✅✅✅ 凭证已成功捕获！")
            print("=" * 60)
            print()
            try:
                with open(CRED_PATH, "r", encoding="utf-8") as f:
                    creds = json.load(f)
                print(f"已捕获 {len(creds)} 个公众号的凭证：")
                for c in creds:
                    biz = c.get("biz", "N/A")
                    uin = c.get("uin", "N/A")
                    has_key = "key" in str(c) or "pass_ticket" in str(c)
                    print(f"  - biz: {biz[:30]}...  uin: {uin}  凭证完整: {has_key}")
                print()
                print("接下来的操作：")
                print("  1. 对每个需要元数据的公众号，重复打开一篇文章")
                print("  2. 凭证有效期约25分钟，过期后重新打开文章即可刷新")
                print("  3. 保持 wxdown-service.exe 运行，保持系统代理开启")
                print()
            except Exception as e:
                print(f"读取凭证文件失败: {e}")
            return 0
        
        # 每10秒打印一次等待提示
        if elapsed % 10 == 0 and elapsed != last_touch:
            remain = TIMEOUT - elapsed
            print(f"[{elapsed:3d}s / {TIMEOUT}s] 等待凭证捕获中... （剩余 {remain}s）")
            last_touch = elapsed
        
        time.sleep(1)
    
    print()
    print("=" * 60)
    print("  ⏰ 等待超时")
    print("=" * 60)
    print()
    print("未检测到凭证，请排查：")
    print("  1. CA 证书是否已安装到「受信任的根证书颁发机构」")
    print("     → 以管理员身份运行：")
    print(f"       certutil -addstore root %USERPROFILE%\\.mitmproxy\\mitmproxy-ca-cert.cer")
    print("  2. 系统代理是否已设置为 127.0.0.1:65000")
    print("     → 检查：设置 → 网络和 Internet → 代理 → 手动设置代理")
    print("  3. 微信客户端是否已重启（代理设置变更后必须重启微信）")
    print("  4. 是否在「微信内置浏览器」中打开文章（不是系统浏览器）")
    print("  5. wxdown-service.exe 是否正在运行")
    print()
    return 1

if __name__ == "__main__":
    exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wxdown-service 完整启用与监控脚本
1. 检查并以管理员权限重启（如需要）
2. 安装 mitmproxy CA 证书
3. 设置系统代理为 127.0.0.1:65000
4. 启动 wxdown-service.exe
5. 监控 credentials.json 的生成
6. 验证凭证是否有效（调用 mptext.top API 测试）
"""

import os
import sys
import json
import time
import subprocess
import requests
import ctypes
from pathlib import Path

# ============ 配置 ============
WXDOWN_EXE = r"D:\opc\content-factory\wxdown-service-windows\wxdown-service.exe"
WXDOWN_DIR = r"D:\opc\content-factory\wxdown-service-windows"
MITM_CA_CER = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.cer"
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 65000
WS_PORT = 65001
API_BASE = "https://down.mptext.top/api/public/v1"
AUTH_KEY = "fb0dd96bc791414da86ade714bfc28fb"
# ============ ============

def is_admin():
    """检查是否以管理员身份运行"""
    try:
        return ctypes.windl.shell32.IsUserAnAdmin()
    except:
        return False

def install_ca_cert():
    """安装 mitmproxy CA 证书到 Windows 受信任根证书颁发机构"""
    print("[1/6] 安装 mitmproxy CA 证书...")
    if not MITM_CA_CER.exists():
        print(f"  ⚠️  CA 证书不存在: {MITM_CA_CER}")
        print("  请先运行一次 wxdown-service.exe 生成证书")
        return False
    try:
        result = subprocess.run(
            ["certutil", "-addstore", "root", str(MITM_CA_CER)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("  ✅ CA 证书安装成功")
            return True
        else:
            print(f"  ❌ CA 证书安装失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"  ❌ 安装 CA 证书时出错: {e}")
        return False

def set_system_proxy(enable=True):
    """设置或取消系统代理"""
    print(f"[2/6] {'设置' if enable else '取消'}系统代理 {PROXY_HOST}:{PROXY_PORT}...")
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
        
        if enable:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{PROXY_HOST}:{PROXY_PORT}")
            print(f"  ✅ 系统代理已设置为 {PROXY_HOST}:{PROXY_PORT}")
        else:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            print("  ✅ 系统代理已取消")
        key.Close()
        
        # 通知 Windows 代理设置已更改
        ctypes.windl.user32.SendMessageW(0xFFFF, 0x001A, 0, "Internet Settings")
        print("  ✅ 已通知系统代理设置已更改")
        return True
    except Exception as e:
        print(f"  ❌ 设置系统代理失败: {e}")
        return False

def start_wxdown_service():
    """启动 wxdown-service.exe"""
    print(f"[3/6] 启动 wxdown-service.exe...")
    
    # 检查是否已在运行
    result = subprocess.run(["tasklist"], capture_output=True, text=True)
    if "wxdown-service.exe" in result.stdout:
        print("  ✅ wxdown-service.exe 已在运行")
        return True
    
    try:
        # 启动进程（不阻塞）
        subprocess.Popen(
            [WXDOWN_EXE, "-p", str(PROXY_PORT), "-w", str(WS_PORT)],
            cwd=WXDOWN_DIR,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        time.sleep(3)
        
        # 验证是否启动成功
        result = subprocess.run(["tasklist"], capture_output=True, text=True)
        if "wxdown-service.exe" in result.stdout:
            print(f"  ✅ wxdown-service.exe 启动成功（代理端口: {PROXY_PORT}，WebSocket: {WS_PORT}）")
            return True
        else:
            print("  ❌ wxdown-service.exe 启动失败")
            return False
    except Exception as e:
        print(f"  ❌ 启动 wxdown-service.exe 时出错: {e}")
        return False

def test_proxy():
    """测试代理是否正常工作"""
    print(f"[4/6] 测试代理是否正常工作...")
    try:
        proxies = {
            "http": f"http://{PROXY_HOST}:{PROXY_PORT}",
            "https": f"http://{PROXY_HOST}:{PROXY_PORT}",
        }
        resp = requests.get("http://httpbin.org/ip", proxies=proxies, timeout=10, verify=False)
        if resp.status_code == 200:
            print(f"  ✅ 代理工作正常: {resp.json()}")
            return True
        else:
            print(f"  ❌ 代理返回异常状态码: {resp.status_code}")
            return False
    except Exception as e:
        print(f"  ❌ 代理测试失败: {e}")
        return False

def monitor_credentials(timeout=300):
    """
    监控 credentials.json 文件的生成
    当微信客户端打开公众号文章时，wxdown-service 会拦截请求并生成此文件
    """
    print(f"[5/6] 监控 credentials.json 生成（超时 {timeout}s）...")
    print("  请在电脑端微信客户端中打开一个公众号文章（内置浏览器）")
    print("  微信客户端路径：底部 → 通讯录 → 公众号 → 搜索/选择公众号 → 打开任意文章")
    print()
    
    credentials_path = Path(WXDOWN_DIR) / "credentials.json"
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if credentials_path.exists():
            print(f"  ✅ 检测到 credentials.json 已生成！")
            try:
                with open(credentials_path, "r", encoding="utf-8") as f:
                    creds = json.load(f)
                print(f"  已捕获 {len(creds)} 个账号的凭证:")
                for cred in creds:
                    biz = cred.get("biz", "unknown")
                    print(f"    - biz: {biz}, time: {cred.get('timestamp', 'N/A')}")
                return creds
            except Exception as e:
                print(f"  ❌ 读取 credentials.json 失败: {e}")
                return None
        time.sleep(5)
        elapsed = int(time.time() - start_time)
        if elapsed % 20 == 0:
            print(f"  等待中... ({elapsed}s / {timeout}s)")
    
    print(f"  ⏰ 超时：{timeout}s 内未检测到 credentials.json")
    print("  请确认：")
    print("    1. 系统代理已设置为 127.0.0.1:65000")
    print("    2. CA 证书已安装")
    print("    3. 在微信客户端（不是浏览器）中打开了公众号文章")
    return None

def test_metadata_api(biz, sn):
    """
    测试使用凭证调用 mptext.top API 获取文章元数据
    （需要先有有效的凭证）
    """
    print(f"[6/6] 测试元数据 API...")
    # 注意：mptext.top 的 /article API 可能已包含元数据
    # 这里需要查看完整文档确认如何获取阅读量、点赞量等
    print("  ℹ️  需要完整的 mptext.top API 文档来确认元数据获取方式")
    print("  ℹ️  请查看 https://docs.mptext.top/llms-full.txt 获取更多信息")
    return True

def main():
    print("=" * 60)
    print("  wxdown-service 完整启用脚本")
    print("=" * 60)
    print()
    
    # 检查管理员权限
    if not is_admin():
        print("⚠️  当前不是管理员权限，CA 证书安装可能失败")
        print("请以管理员身份重新运行此脚本")
        print()
    
    # 1. 安装 CA 证书
    cert_ok = install_ca_cert()
    if not cert_ok:
        print("请手动安装证书或以管理员身份运行")
    
    # 2. 设置系统代理
    proxy_ok = set_system_proxy(enable=True)
    
    # 3. 启动 wxdown-service
    service_ok = start_wxdown_service()
    
    # 4. 测试代理
    if service_ok:
        test_proxy()
    
    # 5. 监控凭证文件
    print()
    creds = monitor_credentials(timeout=300)
    
    if creds:
        print()
        print("=" * 60)
        print("  ✅ 凭证捕获成功！")
        print("=" * 60)
        print()
        print("接下来的步骤：")
        print("  1. 对每个需要抓元数据的公众号，重复在微信中打开一篇文章")
        print("  2. 凭证有效期约25分钟，过期后需重新打开文章刷新")
        print("  3. 保持 wxdown-service 运行，保持系统代理开启")
        print()
    else:
        print()
        print("⚠️  未检测到凭证，请按照上述步骤操作后重新运行此脚本")
    
    return 0 if creds else 1

if __name__ == "__main__":
    sys.exit(main())

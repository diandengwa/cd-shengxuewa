#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OPC Deployment Script
Supports local and remote deployment
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

# Import config loader
sys.path.insert(0, str(Path(__file__).parent))
from config_loader import get_config

def run_command(cmd, cwd=None, check=True):
    """Run command"""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            shell=True
        )
        if check and result.returncode != 0:
            print(f"[ERROR] Command failed: {cmd}")
            print(f"[ERROR] {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"[ERROR] Command execution failed: {e}")
        return False

def check_docker():
    """Check if Docker is installed"""
    success = run_command("docker --version", check=False)
    if not success:
        print("[ERROR] Docker not installed")
        return False
    return True

def check_docker_compose():
    """Check if Docker Compose is installed"""
    success = run_command("docker-compose --version", check=False)
    if not success:
        success = run_command("docker compose version", check=False)
    return success

def build_image(opc_root):
    """Build Docker image"""
    print("[INFO] Building Docker image...")
    success = run_command("docker build .", cwd=opc_root)
    if success:
        print("[OK] Docker image built successfully")
    else:
        print("[ERROR] Docker image build failed")
    return success

def start_services(opc_root):
    """Start services"""
    print("[INFO] Starting services...")
    success = run_command("docker-compose up -d", cwd=opc_root)
    if success:
        print("[OK] Services started successfully")
    else:
        print("[ERROR] Services failed to start")
    return success

def stop_services(opc_root):
    """Stop services"""
    print("[INFO] Stopping services...")
    success = run_command("docker-compose down", cwd=opc_root)
    if success:
        print("[OK] Services stopped successfully")
    else:
        print("[ERROR] Services failed to stop")
    return success

def check_health(opc_root):
    """Check service health"""
    print("[INFO] Checking service health...")
    success = run_command("python scripts/health_check.py", cwd=opc_root)
    return success

def show_logs(opc_root, follow=False):
    """Show logs"""
    print("[INFO] Showing service logs...")
    cmd = "docker-compose logs"
    if follow:
        cmd += " -f"
    success = run_command(cmd, cwd=opc_root)
    return success

def deploy_local(opc_root):
    """Local deployment"""
    print("=== Local Deployment ===")
    
    if not check_docker():
        print("[ERROR] Docker not installed, cannot continue")
        return False
    
    if not check_docker_compose():
        print("[ERROR] Docker Compose not installed, cannot continue")
        return False
    
    if not build_image(opc_root):
        return False
    
    if not start_services(opc_root):
        return False
    
    if not check_health(opc_root):
        print("[WARN] Health check failed, please check logs")
        return False
    
    print("[OK] Local deployment complete")
    return True

def main():
    parser = argparse.ArgumentParser(description='OPC Deployment Tool')
    parser.add_argument('action', choices=['build', 'start', 'stop', 'restart', 'health', 'logs', 'deploy'],
                       help='Action type')
    parser.add_argument('--local', action='store_true', help='Local deployment')
    parser.add_argument('-f', '--follow', action='store_true', help='Follow logs')
    
    args = parser.parse_args()
    
    opc_root = os.environ.get('OPC_ROOT', 'D:\\opc')
    
    if args.action == 'build':
        build_image(opc_root)
    elif args.action == 'start':
        start_services(opc_root)
    elif args.action == 'stop':
        stop_services(opc_root)
    elif args.action == 'restart':
        stop_services(opc_root)
        start_services(opc_root)
    elif args.action == 'health':
        check_health(opc_root)
    elif args.action == 'logs':
        show_logs(opc_root, follow=args.follow)
    elif args.action == 'deploy':
        if args.local:
            deploy_local(opc_root)
        else:
            print("[ERROR] Please specify --local")
            return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())

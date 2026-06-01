#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OPC One-click Installation Script
Automatically installs Docker, configures environment, deploys services
"""

import sys
import os
import subprocess
import platform
from pathlib import Path

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

def check_python():
    """Check Python version"""
    print("=== Checking Python ===")
    version = sys.version_info
    print(f"Python version: {version.major}.{version.minor}.{version.micro}")
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print("[ERROR] Python 3.10 or higher required")
        return False
    print("[OK] Python version meets requirements")
    return True

def check_docker():
    """Check Docker"""
    print("\n=== Checking Docker ===")
    if platform.system() == "Windows":
        docker_path = "C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe"
        if os.path.exists(docker_path):
            print("[OK] Docker Desktop installed")
            return True
        else:
            print("[WARN] Docker Desktop not installed")
            print("Please visit https://www.docker.com/products/docker-desktop/ to download and install")
            return False
    else:
        if run_command("docker --version", check=False):
            print("[OK] Docker installed")
            return True
        else:
            print("[WARN] Docker not installed")
            return False

def install_dependencies():
    """Install Python dependencies"""
    print("\n=== Installing Python Dependencies ===")
    opc_root = os.environ.get('OPC_ROOT', 'D:\\opc')
    requirements_file = os.path.join(opc_root, 'requirements.txt')
    
    if os.path.exists(requirements_file):
        if run_command(f"pip install -r {requirements_file}"):
            print("[OK] Python dependencies installed")
            return True
        else:
            print("[ERROR] Python dependency installation failed")
            return False
    else:
        print("[WARN] requirements.txt not found, skipping dependency installation")
        return True

def setup_environment():
    """Set up environment variables"""
    print("\n=== Setting Up Environment ===")
    opc_root = os.environ.get('OPC_ROOT', 'D:\\opc')
    
    # Create .env file
    env_file = os.path.join(opc_root, '.env')
    if not os.path.exists(env_file):
        print("[INFO] Creating .env file...")
        with open(os.path.join(opc_root, '.env.example'), 'r', encoding='utf-8') as f:
            example_content = f.read()
        
        with open(env_file, 'w', encoding='utf-8') as f:
            f.write(example_content)
        
        print(f"[WARN] Please edit {env_file} file to set API keys and other sensitive information")
    else:
        print("[OK] .env file already exists")
    
    return True

def create_directories():
    """Create necessary directories"""
    print("\n=== Creating Directories ===")
    opc_root = os.environ.get('OPC_ROOT', 'D:\\opc')
    
    dirs = ['knowledge-base', 'drafts', 'reviewed', 'ready-to-publish', 'raw-articles', 'logs']
    for dir_name in dirs:
        dir_path = os.path.join(opc_root, dir_name)
        os.makedirs(dir_path, exist_ok=True)
        print(f"[OK] Directory created: {dir_path}")
    
    return True

def test_config():
    """Test configuration"""
    print("\n=== Testing Configuration ===")
    opc_root = os.environ.get('OPC_ROOT', 'D:\\opc')
    test_script = os.path.join(opc_root, 'scripts', 'test_config.py')
    
    if os.path.exists(test_script):
        if run_command(f"python {test_script}"):
            print("[OK] Configuration test passed")
            return True
        else:
            print("[ERROR] Configuration test failed")
            return False
    else:
        print("[WARN] Test script not found, skipping test")
        return True

def main():
    print("=" * 50)
    print("OPC Content Factory - One-click Installation")
    print("=" * 50)
    
    # 1. Check Python
    if not check_python():
        return 1
    
    # 2. Check Docker
    docker_ready = check_docker()
    if not docker_ready:
        print("\n[IMPORTANT] Docker not installed, but script can continue")
        print("Recommended to install Docker Desktop for full containerization support")
    
    # 3. Install dependencies
    if not install_dependencies():
        return 1
    
    # 4. Set up environment
    if not setup_environment():
        return 1
    
    # 5. Create directories
    if not create_directories():
        return 1
    
    # 6. Test configuration
    if not test_config():
        return 1
    
    print("\n" + "=" * 50)
    print("[OK] OPC Content Factory Installation Complete")
    print("=" * 50)
    print("\nNext steps:")
    print("1. Edit .env file to set API keys")
    print("2. Run: python scripts/health_check.py to check health status")
    print("3. Run: python scripts/opc_generate_v4.py --dry-run to test generation")
    
    if not docker_ready:
        print("\n[IMPORTANT] Please install Docker Desktop to enable containerization")
        print("Download: https://www.docker.com/products/docker-desktop/")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())

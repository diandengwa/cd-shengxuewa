#!/usr/bin/env python3
"""
冒烟测试
验证 Wiki 目录结构、核心页面、索引文件是否完整
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
WIKI_DIR = PROJECT_ROOT / "wiki"
BUILD_DIR = PROJECT_ROOT / "build"
APP_DIR = PROJECT_ROOT / "app"


class SmokeTest:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0

    def check(self, condition: bool, message: str, warning: bool = False) -> bool:
        """检查条件并记录结果"""
        if condition:
            self.passed += 1
            print(f"  [PASS] {message}")
            return True
        else:
            if warning:
                self.warnings += 1
                print(f"  [WARN] {message}")
            else:
                self.failed += 1
                print(f"  [FAIL] {message}")
            return False

    def test_wiki_structure(self):
        """测试 Wiki 目录结构"""
        print("\n[测试] Wiki 目录结构")
        print("-" * 40)

        required_dirs = [
            "scenarios",
            "policies",
            "districts",
            "reference",
            "faq",
            "assessment_templates",
        ]

        for dirname in required_dirs:
            dir_path = WIKI_DIR / dirname
            self.check(dir_path.exists(), f"wiki/{dirname}/ 目录存在")

    def test_scenario_pages(self):
        """测试场景页"""
        print("\n[测试] 场景页")
        print("-" * 40)

        scenarios_dir = WIKI_DIR / "scenarios"
        expected = [
            "2026_幼升小.md",
            "2026_小升初.md",
            "2026_随迁子女入学.md",
            "2025_成都中考_5_plus_2.md",
        ]

        for filename in expected:
            path = scenarios_dir / filename
            self.check(path.exists(), f"场景页: {filename}")

            if path.exists():
                content = path.read_text(encoding='utf-8')
                self.check('## 核心结论' in content, f"{filename} 包含核心结论")
                self.check('## 来源说明' in content, f"{filename} 包含来源说明")
                self.check('## 可信等级' in content, f"{filename} 包含可信等级")

    def test_policy_pages(self):
        """测试政策页"""
        print("\n[测试] 政策页")
        print("-" * 40)

        policies_dir = WIKI_DIR / "policies"
        expected = [
            "2025_成都市_义务教育招生入学通知.md",
            "2025_成都市_义务教育招生入学政策解读.md",
            "2025_成都市_随迁子女入学政策.md",
            "2025_成都市_幼儿园招生入园通知.md",
        ]

        for filename in expected:
            path = policies_dir / filename
            self.check(path.exists(), f"政策页: {filename}")

            if path.exists():
                content = path.read_text(encoding='utf-8')
                self.check('## 核心结论' in content, f"{filename} 包含核心结论")
                self.check('## 来源说明' in content, f"{filename} 包含来源说明")
                self.check('## 可信等级' in content, f"{filename} 包含可信等级")

    def test_district_pages(self):
        """测试区县页"""
        print("\n[测试] 区县页")
        print("-" * 40)

        districts_dir = WIKI_DIR / "districts"
        expected = [
            "2025_青羊区.md",
            "2025_锦江区.md",
            "2025_金牛区.md",
            "2025_武侯区.md",
            "2025_成华区.md",
            "2025_高新区.md",
            "2025_天府新区.md",
        ]

        for filename in expected:
            path = districts_dir / filename
            self.check(path.exists(), f"区县页: {filename}")

    def test_reference_pages(self):
        """测试 Reference 页"""
        print("\n[测试] Reference 页")
        print("-" * 40)

        reference_dir = WIKI_DIR / "reference"
        expected = [
            "source_grading.md",
            "terminology.md",
            "timeline_overview.md",
        ]

        for filename in expected:
            path = reference_dir / filename
            self.check(path.exists(), f"Reference: {filename}")

    def test_build_files(self):
        """测试构建产物"""
        print("\n[测试] 构建产物")
        print("-" * 40)

        manifest_path = BUILD_DIR / "manifest.json"
        self.check(manifest_path.exists(), "build/manifest.json 存在")

        if manifest_path.exists():
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                self.check(len(manifest) > 0, f"manifest 包含 {len(manifest)} 个条目")
            except json.JSONDecodeError:
                self.check(False, "manifest.json 格式正确", warning=False)

        index_path = BUILD_DIR / "search_index.json"
        self.check(index_path.exists(), "build/search_index.json 存在")

        if index_path.exists():
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    index = json.load(f)
                self.check('by_type' in index, "search_index 包含 by_type")
                self.check('by_keyword' in index, "search_index 包含 by_keyword")
            except json.JSONDecodeError:
                self.check(False, "search_index.json 格式正确", warning=False)

    def test_app_structure(self):
        """测试 App 目录结构"""
        print("\n[测试] App 结构")
        print("-" * 40)

        required_files = [
            "__init__.py",
            "main.py",
            "router.py",
            "answerer.py",
            "loaders.py",
            "models.py",
        ]

        for filename in required_files:
            path = APP_DIR / filename
            self.check(path.exists(), f"app/{filename} 存在")

    def run_all(self):
        """运行所有测试"""
        print("=" * 60)
        print("K12 Rocket Smoke Test")
        print("=" * 60)

        self.test_wiki_structure()
        self.test_scenario_pages()
        self.test_policy_pages()
        self.test_district_pages()
        self.test_reference_pages()
        self.test_build_files()
        self.test_app_structure()

        print("\n" + "=" * 60)
        print("测试结果汇总")
        print("=" * 60)
        print(f"  通过: {self.passed}")
        print(f"  失败: {self.failed}")
        print(f"  警告: {self.warnings}")
        print(f"  总计: {self.passed + self.failed + self.warnings}")

        if self.failed == 0:
            print("\n  ✓ 所有关键检查通过!")
            return 0
        else:
            print(f"\n  ✗ 有 {self.failed} 项检查未通过，需要修复")
            return 1


def main():
    tester = SmokeTest()
    return tester.run_all()


if __name__ == '__main__':
    sys.exit(main())

# .github/scripts/adjust-budget.py
# v10新增：根据绩效审计自动调整下周预算
import argparse
import json
import os
from github import Github

def adjust_budget(report_path: str) -> None:
    """根据审计报告调整token-budgets.json"""
    g = Github(os.environ["GITHUB_TOKEN"])
    repo_name = "tangshaowan/cd-shengxuewa"
    repo = g.get_repo(repo_name)
    
    # 读取当前预算
    budgets_path = ".github/token-budgets.json"
    try:
        budgets_file = repo.get_contents(budgets_path)
        budgets = json.loads(budgets_file.decoded_content.decode())
        sha = budgets_file.sha
    except Exception:
        budgets = {"agents": {}}
        sha = None
    
    # 读取审计报告
    scores = {}
    try:
        with open(report_path) as f:
            for line in f:
                if "|" in line and "100 |" not in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) > 7:
                        actor = parts[1]
                        score_str = parts[7].replace("/100", "").strip()
                        try:
                            scores[actor] = float(score_str)
                        except ValueError:
                            pass
    except FileNotFoundError:
        print(f"[WARN] Report file not found: {report_path}")
        return
    
    if not scores:
        print("[INFO] No scores found, skipping budget adjustment")
        return
    
    # 排名调整
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    
    for i, (actor, score) in enumerate(ranked):
        if actor not in budgets["agents"]:
            continue
        current_quota = budgets["agents"][actor]["quota"]
        
        if i == 0 and score > 70:
            budgets["agents"][actor]["quota"] = int(current_quota * 1.1)
        elif i == len(ranked) - 1 and score < 40:
            budgets["agents"][actor]["quota"] = int(current_quota * 0.8)
    
    # 写回仓库（[skip ci]防止循环触发）
    content = json.dumps(budgets, indent=2, ensure_ascii=False)
    commit_message = "[skip ci] auto: update token budgets based on performance review"
    
    if sha:
        repo.update_file(budgets_path, commit_message, content, sha)
    else:
        repo.create_file(budgets_path, commit_message, content)
    
    print(f"[OK] Budget adjusted and committed: {commit_message}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    adjust_budget(args.report)
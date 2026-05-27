# .github/scripts/calculate_usage.py
# v10新增：Token预算用量统计脚本
import argparse
import json
import os
from datetime import datetime, timezone
from github import Github

def calculate_usage(repo_name: str) -> dict:
    """统计当月各Agent的GitHub Actions使用量"""
    g = Github(os.environ["GITHUB_TOKEN"])
    repo = g.get_repo(repo_name)
    
    # 读取配额配置
    budgets_path = ".github/token-budgets.json"
    try:
        budgets_file = repo.get_contents(budgets_path)
        budgets = json.loads(budgets_file.decoded_content.decode())
    except Exception:
        budgets = {"agents": {}}
    
    # 计算当月起止时间
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    
    # 统计每个workflow run的用量（按actor汇总）
    usage_by_actor = {}
    for run in repo.get_workflow_runs():
        if run.created_at < month_start:
            break
        actor = run.actor.login if run.actor else "unknown"
        if actor not in usage_by_actor:
            usage_by_actor[actor] = {"runs": 0, "estimated_tokens": 0}
        usage_by_actor[actor]["runs"] += 1
        usage_by_actor[actor]["estimated_tokens"] += 20000
    
    # 检查告警/熔断
    warning = "false"
    firing = "false"
    report_lines = []
    
    for agent_name, config in budgets.get("agents", {}).items():
        quota = config["quota"]
        used = usage_by_actor.get(agent_name, {}).get("estimated_tokens", 0)
        pct = used / quota if quota > 0 else 0
        
        status = "✅ 正常"
        if pct >= 1.0:
            status = "🚨 熔断"
            firing = "true"
        elif pct >= 0.8:
            status = "⚠️ 告警"
            warning = "true"
        
        report_lines.append(f"| {agent_name} | {used:,} / {quota:,} | {pct:.1%} | {status} |")
    
    report = f"# Token Budget Report\n\n| Agent | Used / Quota | % | Status |\n|-------|-------------|---|--------|\n" + "\n".join(report_lines)
    
    with open("budget_report.md", "w") as f:
        f.write(report)
    
    with open(os.environ["GITHUB_OUTPUT"], "a") as f:
        f.write(f"warning={warning}\n")
        f.write(f"firing={firing}\n")
    
    with open(os.environ["GITHUB_ENV"], "a") as f:
        f.write(f"BUDGET_REPORT<<EOF\n{report}\nEOF\n")
    
    return {"warning": warning, "firing": firing, "usage": usage_by_actor}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    calculate_usage(args.repo)
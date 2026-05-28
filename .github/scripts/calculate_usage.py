# .github/scripts/calculate_usage.py
# Token Budget Guard - usage calculation script
import argparse
import json
import os
from datetime import datetime, timezone
from github import Github

def calculate_usage(repo_name: str) -> dict:
    """Calculate monthly GitHub Actions token usage per agent."""
    g = Github(os.environ["GITHUB_TOKEN"])
    repo = g.get_repo(repo_name)

    # Read budget config
    budgets_path = ".github/token-budgets.json"
    try:
        budgets_file = repo.get_contents(budgets_path)
        budgets = json.loads(budgets_file.decoded_content.decode())
    except Exception:
        budgets = {"agents": {}}

    # Calculate month start time
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    # Calculate usage per workflow actor
    usage_by_actor = {}
    for run in repo.get_workflow_runs():
        if run.created_at < month_start:
            break
        actor = run.actor.login if run.actor else "unknown"
        if actor not in usage_by_actor:
            usage_by_actor[actor] = {"runs": 0, "estimated_tokens": 0}
        usage_by_actor[actor]["runs"] += 1
        usage_by_actor[actor]["estimated_tokens"] += 20000

    # Check warnings / circuit breakers
    warning = "false"
    firing = "false"
    report_lines = []

    for agent_name, config in budgets.get("agents", {}).items():
        # Support both "quota" and "monthly_budget" keys
        quota = config.get("quota", config.get("monthly_budget", 100000))
        used = usage_by_actor.get(agent_name, {}).get("estimated_tokens", 0)
        pct = used / quota if quota > 0 else 0

        status = "OK"
        if pct >= 1.0:
            status = "CIRCUIT BREAK"
            firing = "true"
        elif pct >= 0.8:
            status = "WARNING"
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
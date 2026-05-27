# .github/scripts/performance-review.py
# v10新增：Agent绩效审计脚本
import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from github import Github

def performance_review(repo_name: str, days: int = 7) -> str:
    """审计各Agent过去N天的绩效"""
    g = Github(os.environ["GITHUB_TOKEN"])
    repo = g.get_repo(repo_name)
    
    since = datetime.now(timezone.utc) - timedelta(days=days)
    
    # 统计PR数据
    pr_stats = {}
    for pr in repo.get_pulls(state="all", sort="created", direction="desc"):
        if pr.created_at < since:
            break
        actor = pr.user.login
        if actor not in pr_stats:
            pr_stats[actor] = {"opened": 0, "merged": 0, "comments": 0}
        pr_stats[actor]["opened"] += 1
        if pr.merged:
            pr_stats[actor]["merged"] += 1
        pr_stats[actor]["comments"] += pr.comments
    
    # 统计Issue数据
    issue_stats = {}
    for issue in repo.get_issues(state="all", since=since):
        actor = issue.user.login
        if actor not in issue_stats:
            issue_stats[actor] = {"opened": 0, "closed": 0}
        issue_stats[actor]["opened"] += 1
        if issue.closed_by:
            issue_stats[actor]["closed"] += 1
    
    # 计算综合评分
    report_lines = [f"# Agent Performance Report (last {days} days)\n"]
    report_lines.append("| Agent | PRs Opened | PRs Merged | Adoption Rate | Issues Opened | Issues Closed | Score |")
    report_lines.append("|-------|-----------|-----------|---------------|--------------|--------------|-------|")
    
    all_actors = set(list(pr_stats.keys()) + list(issue_stats.keys()))
    scores = {}
    
    for actor in all_actors:
        pr = pr_stats.get(actor, {"opened": 0, "merged": 0, "comments": 0})
        iss = issue_stats.get(actor, {"opened": 0, "closed": 0})
        
        adoption_rate = pr["merged"] / pr["opened"] if pr["opened"] > 0 else 0
        production_score = min(pr["opened"] / 10, 1.0) * 20
        responsiveness_score = min(pr["comments"] / 20, 1.0) * 20
        adoption_score = adoption_rate * 60
        total_score = adoption_score + production_score + responsiveness_score
        
        scores[actor] = total_score
        report_lines.append(
            f"| {actor} | {pr['opened']} | {pr['merged']} | {adoption_rate:.0%} | "
            f"{iss['opened']} | {iss['closed']} | {total_score:.0f}/100 |"
        )
    
    report = "\n".join(report_lines)
    with open("audit_report.md", "w") as f:
        f.write(report)
    
    return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    performance_review(args.repo, args.days)
# .github/scripts/shadow-review.py
# v10: pr.diff()→requests获取diff, 只审查触发PR而非全量
import anthropic
import json
import os
import sys
import requests as http_requests
from github import Github

def get_pr_diff(repo_name: str, pr_number: int, token: str) -> str:
    """通过GitHub REST API获取PR diff（PyGithub无.diff()方法）"""
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.diff"
    }
    url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}"
    resp = http_requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.text

def shadow_review(pr_diff: str, pr_author: str, memory_md: str) -> dict:
    """影子模型审查PR"""
    client = anthropic.Anthropic()
    
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": f"""你是OPC影子审查员。审查以下PR：

**提交者**: {pr_author}
**MEMORY.md品味标准**:
{memory_md[:2000]}

**PR Diff**:
{pr_diff[:8000]}

请从四个维度评估（返回JSON）：
1. taste: 是否符合MEMORY.md品味标准（pass/warn/fail）
2. architecture: 是否符合架构原则（pass/warn/fail）
3. security: 是否存在安全隐患（pass/warn/fail）
4. logic: 逻辑是否自洽（pass/warn/fail）

返回格式：{{
  "taste": {{\"verdict\": \"pass|warn|fail\", \"reason\": \"...\"}},
  "architecture": {{\"verdict\": \"pass|warn|fail\", \"reason\": \"...\"}},
  "security": {{\"verdict\": \"pass|warn|fail\", \"reason\": \"...\"}},
  "logic": {{\"verdict\": \"pass|warn|fail\", \"reason\": \"...\"}},
  "overall": "approved|alert",
  "confidence": 0.0-1.0
}}"""
        }]
    )
    
    return json.loads(response.content[0].text)

def post_shadow_comment(g: Github, repo_name: str, pr_number: int, result: dict):
    """在PR上发布影子审查结果"""
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    
    if result["overall"] == "alert":
        verdicts = []
        for dim in ["taste", "architecture", "security", "logic"]:
            if result[dim]["verdict"] != "pass":
                verdicts.append(f"- **{dim}**: {result[dim]['verdict']} — {result[dim]['reason']}")
        
        pr.create_issue_comment(f"""### 🔴 [Shadow_Alert]

**置信度**: {result['confidence']:.0%}

**发现的问题**:
{chr(10).join(verdicts)}

> ⚠️ 此审查由影子模型自动生成。创始人确认后，系统将自动扣除该Agent下周20%的Token额度。
""")
    else:
        pr.create_issue_comment(f"""### ✅ [Shadow_Approved]

**置信度**: {result['confidence']:.0%}

所有维度通过初审，等待超级智能体二审。
""")

if __name__ == "__main__":
    token = os.environ["GITHUB_TOKEN"]
    g = Github(token)
    repo_name = "tangshaowan/cd-shengxuewa"
    
    pr_number = int(os.environ.get("PR_NUMBER", 0))
    if not pr_number:
        print("[ERROR] PR_NUMBER not set. This script must be called from shadow-review.yml")
        sys.exit(1)
    
    memory_content = ""
    try:
        repo = g.get_repo(repo_name)
        memory_file = repo.get_contents("MEMORY.md")
        memory_content = memory_file.decoded_content.decode()
    except Exception:
        pass
    
    pr_diff = get_pr_diff(repo_name, pr_number, token)
    pr = repo.get_pull(pr_number)
    
    result = shadow_review(pr_diff, pr.user.login, memory_content)
    post_shadow_comment(g, repo_name, pr_number, result)
    print(f"[OK] Shadow review completed for PR #{pr_number}: {result['overall']}")
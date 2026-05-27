# .github/scripts/shadow-review.py
# v11: DeepSeek V4 影子审查（替代Anthropic，国内可用）
import json
import os
import sys
import requests as http_requests
from openai import OpenAI
from github import Github

def get_pr_diff(repo_name: str, pr_number: int, token: str) -> str:
    """通过GitHub REST API获取PR diff"""
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.diff"
    }
    url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}"
    resp = http_requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.text

def shadow_review(pr_diff: str, pr_author: str, memory_md: str) -> dict:
    """DeepSeek V4 Flash 影子审查PR"""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    
    client = OpenAI(api_key=api_key, base_url=base_url)
    
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
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
  "taste": {{"verdict": "pass|warn|fail", "reason": "..."}},
  "architecture": {{"verdict": "pass|warn|fail", "reason": "..."}},
  "security": {{"verdict": "pass|warn|fail", "reason": "..."}},
  "logic": {{"verdict": "pass|warn|fail", "reason": "..."}},
  "overall": "approved|alert",
  "confidence": 0.0-1.0
}}"""
        }]
    )
    
    text = response.choices[0].message.content
    # 清理可能的markdown代码块包裹
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    return json.loads(text)

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

> ⚠️ 此审查由 DeepSeek V4 Flash 影子模型自动生成。创始人确认后，系统将自动扣除该Agent下周20%的Token额度。
""")
    else:
        pr.create_issue_comment(f"""### ✅ [Shadow_Approved]

**置信度**: {result['confidence']:.0%}

所有维度通过初审，等待超级智能体二审。

> 审查模型: DeepSeek V4 Flash
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
    print(f"[OK] Shadow review completed for PR #{pr_number}: {result['overall']} (model: deepseek-v4-flash)")

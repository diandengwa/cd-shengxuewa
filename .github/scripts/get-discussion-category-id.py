# .github/scripts/get-discussion-category-id.py
# v10新增：动态查询Discussion Category的节点ID
import os
import requests

def get_category_id(repo_owner: str, repo_name: str, category_slug: str) -> str:
    """通过GraphQL查询获取Discussion Category的节点ID"""
    token = os.environ["GITHUB_TOKEN"]
    query = """
    query($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) {
        discussionCategories(first: 20) {
          nodes {
            id
            name
            slug
          }
        }
      }
    }
    """
    resp = requests.post(
        "https://api.github.com/graphql",
        headers={"Authorization": f"bearer {token}"},
        json={"query": query, "variables": {"owner": repo_owner, "name": repo_name}}
    )
    resp.raise_for_status()
    
    categories = resp.json()["data"]["repository"]["discussionCategories"]["nodes"]
    for cat in categories:
        if cat["slug"] == category_slug:
            return cat["id"]
    
    available = ", ".join(f"{c['slug']}={c['id']}" for c in categories)
    raise ValueError(f"Category '{category_slug}' not found. Available: {available}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default="tangshaowan")
    parser.add_argument("--repo", default="cd-shengxuewa")
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()
    cat_id = get_category_id(args.owner, args.repo, args.slug)
    print(cat_id)
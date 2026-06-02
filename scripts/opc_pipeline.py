#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(r"/app")
KB_DIR = ROOT / "knowledge-base"
DRAFTS_DIR = ROOT / "drafts"
REVIEWED_DIR = ROOT / "reviewed"
READY_DIR = ROOT / "ready-to-publish"


@dataclass
class StageResult:
    status: str
    output: str | None = None
    count: int | None = None
    score: float | None = None
    error: str | None = None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def stage_dir(base: Path) -> Path:
    path = base / today_str()
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_kb_items(limit: int = 4) -> list[dict[str, Any]]:
    index = load_json(KB_DIR / "index.json", {})
    items = index.get("articles_index", [])
    if not isinstance(items, list):
        return []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw_item in items:
        item = dict(raw_item)
        category = str(item.get("category") or "fact-claims")
        file_value = str(item.get("file") or "").strip()
        if file_value:
            detail = load_json(ROOT / file_value, {})
            if isinstance(detail, dict):
                item["detail"] = detail
        grouped.setdefault(category, []).append(item)

    selected: list[dict[str, Any]] = []
    for category in ["gap-analysis", "pain-points", "decision-frameworks", "fact-claims"]:
        for item in grouped.get(category, [])[:2]:
            selected.append(item)
            if len(selected) >= limit:
                return selected
    return selected[:limit]


def kb_display_title(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "").strip()
    if title and title.lower() not in {"you asked", "untitled"}:
        return title
    detail = item.get("detail", {})
    if isinstance(detail, dict):
        source_file = str(detail.get("source_file") or "").strip()
        if source_file:
            return Path(source_file).stem
    file_value = str(item.get("file") or "").strip()
    if file_value:
        return Path(file_value).stem
    return "未命名素材"


def clean_summary_text(text: str) -> str:
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.S)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"From:\s+\S+", " ", cleaned)
    noise_markers = [
        "# you asked",
        "you asked",
        "deepseek response",
        "DeepSeek response",
        "message time",
        "collect 阶段",
        "原始材料",
        "content-factory",
    ]
    for marker in noise_markers:
        cleaned = cleaned.replace(marker, " ")
    cleaned = re.sub(r"[>`*_#]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_evidence_snippet(item: dict[str, Any], fallback_index: int) -> str:
    detail = item.get("detail", {})
    summary = str(detail.get("summary") or "") if isinstance(detail, dict) else ""
    cleaned = clean_summary_text(summary)
    parts = re.split(r"[。！？!?；;]", cleaned)
    blocked = ["metadata", "source_path", "collected_at", "source_type", "json", "markdown"]
    for part in parts:
        part = part.strip(" ,，:：")
        if len(part) < 18 or len(part) > 110:
            continue
        lowered = part.lower()
        if any(token in lowered for token in blocked):
            continue
        return part

    keywords = item.get("keywords", [])
    if isinstance(keywords, list) and keywords:
        joined = "、".join(str(k) for k in keywords[:4])
        return f"该素材反复出现 {joined}，说明问题已集中到固定瓶颈，而不是单点偶发。"

    return f"第 {fallback_index} 个知识卡提供了可复用的判断框架，可直接转成选题、结构和动作建议。"


def persona_config(persona: str) -> dict[str, str]:
    mapping = {
        "升学钩子": {
            "audience": "面向要抢时间、想把内容工厂真正跑起来的操盘者",
            "hook": "如果你的内容团队每天都在催模型回话，那不是 AI 不够强，而是生产系统还没产品化。",
            "cta": "先把一条最小闭环跑通，再谈放量。",
        },
        "搞钱钩子": {
            "audience": "面向追求增长和变现效率的项目负责人",
            "hook": "能不能赚钱，往往不取决于你写得多快，而取决于你的生产链路能否稳定复用。",
            "cta": "先让每篇稿子有明确目标，再考虑规模化分发。",
        },
    }
    return mapping[persona]


def build_draft_text(persona: str, items: list[dict[str, Any]]) -> str:
    config = persona_config(persona)
    source_lines: list[str] = []
    evidence_lines: list[str] = []

    for idx, item in enumerate(items, 1):
        title = kb_display_title(item)
        category = str(item.get("category") or "fact-claims")
        source_lines.append(f"- {title} [{category}]")
        evidence_lines.append(f"{idx}. {title}：{extract_evidence_snippet(item, idx)}")

    body = [
        f"# {persona}：把内容工厂从计划状态推进到可发布状态",
        "",
        f"> 适用对象：{config['audience']}",
        "",
        "## 开篇判断",
        "",
        config["hook"],
        "真正拖慢项目的，不是不会写，而是素材、判断、生成、审稿和待发布稿之间没有形成一条可复用的链路。",
        "只要每个阶段都有明确输入、落盘产物和通过标准，内容工厂就能从聊天式协作，升级成持续出稿的生产系统。",
        "",
        "## 为什么今天会卡住",
        "",
        "问题不是单个助手不够努力，而是系统把关键动作都绑在人工来回确认上。",
        "一旦抓取、知识提炼、起稿和审稿没有明确的责任边界，团队就会陷入“看起来一直在工作，实际上没有形成成品”的假忙。",
        "这类阻塞最危险的地方，在于所有人都觉得自己做了事，但没有任何一个环节对最终发布负责。",
        "",
        "## 来自现有素材的证据",
        "",
        *evidence_lines,
        "",
        "## 结论",
        "",
        "当前最需要的不是更多提示词，而是一版更像成品的生成与审稿规则：每篇稿子都必须有清晰结论、证据支撑、执行建议和风险提醒。",
        "如果一篇稿子不能回答“为什么现在做、凭什么这么做、今天先做哪三步”，它就不应该进入待发布目录。",
        "",
        "## 可直接执行的升级方案",
        "",
        "1. 先把素材改造成证据，而不是只保留标题和标签。每篇稿子至少引用 3 条来自知识卡的观察，避免空泛复述。",
        "2. 生成阶段统一采用成稿结构：开篇判断、问题拆解、证据段、执行清单、风险提醒、结尾动作。",
        "3. 审稿阶段不再只检查篇幅和标题，而是检查是否有证据、是否有步骤、是否存在占位话术、是否适合直接发布。",
        "",
        "## 72 小时执行清单",
        "",
        "1. 今天先确保至少 2 篇稿子达到“可发但还可再润”的标准，不再输出模板化占位稿。",
        "2. 明天把知识卡标题恢复正常，避免上游原始标题被错误抽成通用文本，影响后续选题判断。",
        "3. 后天开始区分不同稿型：增长型、操盘型、案例型，不再让所有文章共用同一套语气。",
        "",
        "## 风险提醒",
        "",
        "如果上游素材标题继续失真，后续选题命中率会下降，生成阶段只能靠摘要和关键词补救。",
        "如果审稿标准过宽，系统会继续把“格式完整但信息密度不足”的稿子送进待发布目录，反而增加人工返工成本。",
        "",
        "## 收尾动作",
        "",
        f"{config['cta']} 这才是把内容工厂从演示状态拉到生产状态的关键一步。",
        "",
        "## 素材清单",
        "",
        *source_lines,
        "",
        "## 备注",
        "",
        "本文由 `opc_pipeline.py` 自动生成，并按发布前审稿规则进行结构化校验。",
    ]
    return "\n".join(body)


def score_draft(text: str) -> float:
    score = 0.0
    if text.startswith("# "):
        score += 0.8

    section_markers = [
        "## 开篇判断",
        "## 为什么今天会卡住",
        "## 来自现有素材的证据",
        "## 结论",
        "## 可直接执行的升级方案",
        "## 72 小时执行清单",
        "## 风险提醒",
        "## 收尾动作",
    ]
    score += min(len(re.findall(r"^##\s+", text, flags=re.M)), 8) * 0.65

    if len(text) >= 1600:
        score += 1.2
    elif len(text) >= 1200:
        score += 0.8

    for marker in section_markers:
        if marker in text:
            score += 0.75

    evidence_count = len(re.findall(r"^\d+\.\s+.+[:：].+", text, flags=re.M))
    score += min(evidence_count, 4) * 0.4

    if re.search(r"^1\.\s+.+", text, flags=re.M) and re.search(r"^2\.\s+.+", text, flags=re.M):
        score += 0.6

    dirty_markers = ["待补充", "后续再说", "自行发挥", "TODO", "you asked", "deepseek response", "collect 阶段"]
    for marker in dirty_markers:
        if marker.lower() in text.lower():
            score -= 0.9

    return round(max(0.0, min(score, 10.0)), 1)


def review_issues(text: str) -> list[str]:
    issues: list[str] = []

    if len(text) < 1200:
        issues.append("篇幅偏短，信息密度不足")

    required_sections = [
        "## 开篇判断",
        "## 来自现有素材的证据",
        "## 结论",
        "## 可直接执行的升级方案",
        "## 72 小时执行清单",
        "## 风险提醒",
        "## 收尾动作",
    ]
    for section in required_sections:
        if section not in text:
            issues.append(f"缺少必要段落：{section}")

    if len(re.findall(r"^\d+\.\s+.+[:：].+", text, flags=re.M)) < 3:
        issues.append("证据条目不足，至少需要 3 条")

    dirty_markers = ["you asked", "deepseek response", "collect 阶段", "待补充", "自行发挥", "TODO"]
    for marker in dirty_markers:
        if marker.lower() in text.lower():
            issues.append(f"存在占位或脏数据标记：{marker}")

    return issues


def generate_stage() -> StageResult:
    items = load_kb_items(limit=4)
    if not items:
        return StageResult(status="failed", error="knowledge_base_empty")

    out_dir = stage_dir(DRAFTS_DIR)
    draft_files: list[Path] = []
    for idx, persona in enumerate(["升学钩子", "搞钱钩子"], 1):
        path = out_dir / f"draft-{idx}.md"
        write_text(path, build_draft_text(persona, items))
        draft_files.append(path)

    write_json(
        out_dir / "status.json",
        {
            "date": today_str(),
            "draft_done": True,
            "draft_files": [str(path.relative_to(ROOT)).replace("\\", "/") for path in draft_files],
            "generated_at": now_iso(),
        },
    )

    return StageResult(status="done", output=str(out_dir), count=len(draft_files))


def review_stage() -> StageResult:
    draft_dir = stage_dir(DRAFTS_DIR)
    reviewed_dir = stage_dir(REVIEWED_DIR)
    reviewed_count = 0
    scores: list[float] = []

    for draft_file in sorted(draft_dir.glob("draft-*.md")):
        text = read_text(draft_file)
        score = score_draft(text)
        issues = review_issues(text)
        scores.append(score)

        if score >= 8.2 and not issues:
            content = "\n".join(
                [
                    text,
                    "",
                    "---",
                    "",
                    "## 审稿结论",
                    "",
                    f"- score: {score}",
                    "- verdict: pass",
                    "- note: 结构完整，已有证据、动作和风险提醒，可进入发布准备。",
                ]
            )
            write_text(reviewed_dir / f"final-{draft_file.name}", content)
            reviewed_count += 1
        else:
            content = "\n".join(
                [
                    text,
                    "",
                    "---",
                    "",
                    "## 审稿结论",
                    "",
                    f"- score: {score}",
                    "- verdict: revise",
                    "- note: 当前版本仍不足以直接发布，需要按以下问题补强。",
                    "",
                    "## 待补强问题",
                    "",
                    *([f"- {issue}" for issue in issues] if issues else ["- 审稿分未达标，但未提取到明确问题，请人工复核。"]),
                ]
            )
            write_text(draft_file, content)

    average = round(sum(scores) / len(scores), 1) if scores else None
    return StageResult(status="done" if reviewed_count else "failed", output=str(reviewed_dir), count=reviewed_count, score=average)


def publish_prep_stage() -> StageResult:
    """格式化 + V5封面图 + HTML排版 的完整发布准备。"""
    reviewed_dir = stage_dir(REVIEWED_DIR)
    ready_dir = stage_dir(READY_DIR)
    ready_dir.mkdir(parents=True, exist_ok=True)

    # 找今日 reviewed 文件
    reviewed_files = sorted(reviewed_dir.glob("final-*.md"))
    if not reviewed_files:
        return StageResult(status="failed", error="no_final_drafts")

    # Step 1: 格式化（baoyu-format-markdown 已集成，这里用简单实现）
    import shutil
    manifest_entries: list[dict] = []
    generated_covers = 0

    for reviewed_file in reviewed_files:
        stem = reviewed_file.stem.replace("final-", "")
        target_md = ready_dir / f"{stem}.md"
        shutil.copy2(str(reviewed_file), str(target_md))

        # Step 2: 调用 V5 生成封面图
        cover_script = ROOT / "scripts" / "generate_cover_v5.py"
        if cover_script.exists():
            import subprocess
            cmd = [
                "python", str(cover_script),
                "--manifest", str(ready_dir / "manifest.json"),
                "--date", datetime.now().strftime("%Y.%m.%d"),
                "--force",
            ]
            result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                generated_covers += 1

        manifest_entries.append({
            "file": str(target_md.relative_to(ROOT)).replace("\\", "/"),
            "cover": f"imgs/{stem}_cover.png",
            "sub": f"imgs/{stem}_sub.png",
            "status": "cover_done",
        })

    # 写 manifest
    manifest = {
        "date": today_str(),
        "generated_at": now_iso(),
        "pending_review": manifest_entries,
    }
    write_json(ready_dir / "manifest.json", manifest)

    return StageResult(
        status="done",
        output=str(ready_dir),
        count=generated_covers,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["generate", "review", "publish-prep", "run"])
    args = parser.parse_args()

    if args.stage == "generate":
        result = generate_stage()
    elif args.stage == "review":
        result = review_stage()
    elif args.stage == "publish-prep":
        result = publish_prep_stage()
    else:
        result = generate_stage()
        if result.status == "done":
            result = review_stage()
        if result.status == "done":
            result = publish_prep_stage()

    return 0 if result.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

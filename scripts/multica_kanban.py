#!/usr/bin/env python3
"""
multica_kanban.py - Multica 本地看板操作脚本
Agent 可通过此脚本读写 D:\opc\multica\kanban.json

用法:
  python multica_kanban.py list <list_name>           # 列出某列表所有任务
  python multica_kanban.py get <list_name> <task_id> # 获取单条任务
  python multica_kanban.py add <list_name> <json>    # 添加任务
  python multica_kanban.py update <list_name> <task_id> <json>  # 更新任务
  python multica_kanban.py move <task_id> <from_list> <to_list>  # 移动任务（如 Blocked→Done）
  python multica_kanban.py summary                    # 看板概览
"""

import json
import sys
import os
from datetime import datetime, timezone, timedelta

KANBAN_PATH = r"D:\opc\multica\kanban.json"
CST = timezone(timedelta(hours=8))

def load():
    with open(KANBAN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save(data):
    with open(KANBAN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def now_iso():
    return datetime.now(CST).isoformat(timespec="seconds")

def list_tasks(data, list_name):
    if list_name not in data:
        print(f"[ERROR] 列表不存在: {list_name}")
        print(f"可用列表: {list(data.keys())}")
        return
    records = data[list_name]["records"]
    if not records:
        print(f"[{list_name}] 暂无任务")
        return
    for r in records:
        status = r.get("status", "N/A")
        title = r.get("title", "")[:40]
        tid = r.get("id", "")
        print(f"  {tid} [{status}] {title}")

def get_task(data, list_name, task_id):
    if list_name not in data:
        print(f"[ERROR] 列表不存在: {list_name}")
        return
    for r in data[list_name]["records"]:
        if r.get("id") == task_id:
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return
    print(f"[ERROR] 任务不存在: {task_id} in {list_name}")

def add_task(data, list_name, task_json_str):
    if list_name not in data:
        print(f"[ERROR] 列表不存在: {list_name}")
        return
    task = json.loads(task_json_str)
    # 自动填充时间戳
    if "created_at" not in task:
        task["created_at"] = now_iso()
    data[list_name]["records"].append(task)
    save(data)
    print(f"[OK] 任务已添加至 {list_name}: {task.get('id', 'N/A')}")

def update_task(data, list_name, task_id, task_json_str):
    if list_name not in data:
        print(f"[ERROR] 列表不存在: {list_name}")
        return
    patch = json.loads(task_json_str)
    for i, r in enumerate(data[list_name]["records"]):
        if r.get("id") == task_id:
            data[list_name]["records"][i].update(patch)
            if "finished_at" in patch and patch.get("finished_at") and r.get("status") != "done":
                data[list_name]["records"][i]["status"] = "done"
            save(data)
            print(f"[OK] 任务已更新: {task_id}")
            return
    print(f"[ERROR] 任务不存在: {task_id} in {list_name}")

def move_task(data, task_id, from_list, to_list):
    if from_list not in data or to_list not in data:
        print(f"[ERROR] 列表不存在")
        return
    for i, r in enumerate(data[from_list]["records"]):
        if r.get("id") == task_id:
            task = data[from_list]["records"].pop(i)
            task["status"] = "done" if to_list == "Done" else task.get("status", "open")
            if to_list == "Done" and "finished_at" not in task:
                task["finished_at"] = now_iso()
            data[to_list]["records"].append(task)
            save(data)
            print(f"[OK] 任务 {task_id} 已从 {from_list} 移至 {to_list}")
            return
    print(f"[ERROR] 任务不存在: {task_id} in {from_list}")

def summary(data):
    print("=== Multica 看板概览 ===")
    for list_name in ["Human Task", "AI Agent Task", "Blocked", "Done"]:
        if list_name in data:
            count = len(data[list_name]["records"])
            open_count = sum(1 for r in data[list_name]["records"] if r.get("status") == "open")
            print(f"  {list_name}: {count} 条 (open: {open_count})")
    print(f"  数据文件: {KANBAN_PATH}")

def main():
    if not os.path.exists(KANBAN_PATH):
        print(f"[ERROR] 看板文件不存在: {KANBAN_PATH}")
        sys.exit(1)

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    data = load()

    if cmd == "list" and len(sys.argv) >= 3:
        list_tasks(data, sys.argv[2])
    elif cmd == "get" and len(sys.argv) >= 4:
        get_task(data, sys.argv[2], sys.argv[3])
    elif cmd == "add" and len(sys.argv) >= 4:
        add_task(data, sys.argv[2], sys.argv[3])
    elif cmd == "update" and len(sys.argv) >= 5:
        update_task(data, sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "move" and len(sys.argv) >= 5:
        move_task(data, sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "summary":
        summary(data)
    else:
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()

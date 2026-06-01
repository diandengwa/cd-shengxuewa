import sys

with open(r"D:\opc\scripts\opc_collect.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# 删除包含 signal 关键词的行，以及 signal_handler 函数体
result = []
skip_block = False
brace_depth = 0
i = 0
while i < len(lines):
    line = lines[i]
    
    # 跳过 import signal
    if "import signal" in line and line.strip().startswith("import "):
        i += 1
        continue
    
    # 跳过整个 signal_handler 函数
    if "def signal_handler" in line:
        skip_block = True
        i += 1
        continue
    
    if skip_block:
        # signal handler 函数体，一直跳到函数结束（缩进回到0或下一行非空白）
        if line.strip() == "" or line[0] == " " or line[0] == "\t":
            i += 1
            continue
        else:
            skip_block = False
            # 不 skip 这一行，让它正常处理
            #  fall through
    
    if not skip_block:
        result.append(line)
    i += 1

# 删除 signal.signal() 调用行
filtered = []
i = 0
while i < len(result):
    line = result[i]
    if "signal.signal" in line or ("import signal" in line):
        i += 1
        continue
    # 跳过 try: ... except: 包裹 signal 的代码块
    if "try:" in line and i+1 < len(result) and "signal" in "".join(result[i:i+5]):
        # 跳过这个 try 块
        depth = 1
        i += 1
        while i < len(result) and depth > 0:
            if result[i].strip().startswith("try:"):
                depth += 1
            elif result[i].strip().startswith("except") or result[i].strip() == "except Exception:":
                depth -= 1
            if depth > 0:
                i += 1
        continue
    filtered.append(line)
    i += 1

# 写回文件
with open(r"D:\opc\scripts\opc_collect.py", "w", encoding="utf-8") as f:
    f.writelines(filtered)

print("signal 代码已删除，现在添加异常捕获...")

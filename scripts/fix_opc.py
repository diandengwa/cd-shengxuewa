import re

with open(r"D:\opc\scripts\opc_collect.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# 1. 删除 signal_handler 函数及其注册代码
#    找到 "def signal_handler" 开头，一直删到 "API_BASE   = " 之前
new_lines = []
skip = False
i = 0
while i < len(lines):
    line = lines[i]
    if "def signal_handler" in line:
        skip = True
        i += 1
        continue
    if skip and line.startswith("API_BASE"):
        skip = False
        # 保留这行
        new_lines.append("\n")  # 补一个空行
        new_lines.append(line)
        i += 1
        continue
    if skip:
        i += 1
        continue
    # 同时删除 signal 注册代码块
    if 'signal.signal' in line or (skip and 'try' in line and 'signal' in ''.join(lines[max(0,i-2):i+3]):
        # 删除 try/except signal 块
        # 找到这个 try 块的结束
        if 'signal.signal' in line:
            # 跳过这个 try 块
            depth = 1
            i += 1
            while i < len(lines) and depth > 0:
                if lines[i].strip().startswith('try:'):
                    depth += 1
                elif lines[i].strip().startswith('except') or lines[i].strip() == 'except Exception:':
                    depth -= 1
                i += 1
            continue
    new_lines.append(line)
    i += 1

fixed = ''.join(new_lines)

# 2. 替换 if __name__ == "__main__": main() 加上异常捕获
old_main = 'if __name__ == "__main__":\n    main()'
new_main = '''if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        error_msg = "[" + datetime.now().strftime("%H:%M:%S") + "] FATAL ERROR: " + str(e) + "\\n" + traceback.format_exc()
        print(error_msg, flush=True)
        try:
            with open(r"D:\\opc\\pipeline-logs\\collect-FATAL.log", "w", encoding="utf-8") as logf:
                logf.write(error_msg)
        except Exception:
            pass
        sys.exit(1)'''

if old_main in fixed:
    fixed = fixed.replace(old_main, new_main)
    print("已添加全局异常捕获")
else:
    print("WARNING: 未找到 main() 调用块，手动检查")

with open(r"D:\opc\scripts\opc_collect.py", "w", encoding="utf-8") as f:
    f.write(fixed)

print("修复完成，验证语法...")

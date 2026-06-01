"""Non-interactive SSH helper using paramiko."""
import sys
import paramiko
import time

host = "162.14.74.251"
user = "root"
password = "Ysh780218@"
command = sys.argv[1] if len(sys.argv) > 1 else "echo SSH_OK && uname -a && uptime"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    client.connect(host, port=22, username=user, password=password, timeout=15)
    stdin, stdout, stderr = client.exec_command(command, timeout=30)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if out:
        print(out, end="")
    if err:
        print(err, end="", file=sys.stderr)
    exit_code = stdout.channel.recv_exit_status()
    sys.exit(exit_code)
except Exception as e:
    print(f"SSH_ERROR: {e}", file=sys.stderr)
    sys.exit(1)
finally:
    client.close()

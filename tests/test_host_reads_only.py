"""A host command line in a run that may only read (MVP-2.9.0 N30).

skills/security.classify_shell_command reads how the WHOLE LINE begins, and its read-only list holds words that
write or run other commands when given the right arguments: «cat x && systemctl restart nginx», «ps aux | xargs
kill» and «echo … | sed -n 'w /etc/cron.d/x'» are all «readonly» to it and ran without a question. In a run that may
only read — a diagnosis, a fix-plan run, a change's review, a read-only account — the host tools ask
services/change_steps.host_reads_only instead: the line is read as a shell would split it, and EVERY simple command
in it must be one the rule knows cannot change anything. It is an allow-list: what it does not know is refused.
"""
import os
import pathlib
import shlex
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from agenticops.models import CommandAudit, get_session
from agenticops.run_context import run_context
from agenticops.services import change_steps
from agenticops.services.change_steps import command_tier, host_reads_only, read_only_host_tier
from agenticops.services.command_audit import change_context_refusal, read_only_context
from tests.test_viewer_role import _temp_db

READS = [
    # the lines a diagnosis sends
    "ps aux | grep java", "df -h; free -m", "free -m && df -h && uptime", "uptime; who; w", "id; whoami; groups",
    "cat /etc/os-release", "cat /proc/meminfo | head -n 5", "ls -la /var/log/nginx/", "ls /var/log/*.log",
    "tail -n 100 /var/log/nginx/error.log", "tail -n 200 /var/log/syslog | grep -i 'out of memory'",
    'grep -c "error" /var/log/app.log', "grep -E 'error|fail' /var/log/app.log | tail -20",
    'grep "timeout$" /var/log/app.log', "grep -rn 'listen 443;' /etc/nginx/conf.d/",
    "top -bn1 | head -20", "ps -eo pid,ppid,cmd,%mem,%cpu --sort=-%mem | head", "pgrep -fl nginx",
    "lsof -i :8080", "netstat -tulpn", "stat /etc/passwd", "wc -l /var/log/app.log", "printenv PATH",
    "lsblk; lscpu | head; nproc", "dig +short example.com", "ping -c 3 10.0.0.1",
    "du -sh /var/log/* 2>/dev/null | sort -h | tail", "docker ps -a", "docker logs --tail 100 web",
    "docker inspect web | grep -i restart", "fdisk -l", "sshd -t", "\\ls -la",
    # chains and what changes nothing
    'echo "--- disk ---"; df -h; echo "--- mem ---"; free -m', "cd /var/log && ls -la",
    "ls /nonexistent 2>/dev/null || echo missing", "cat /etc/nginx/nginx.conf 2>&1 | head -50",
    "df -h > /dev/null 2>&1; echo $?", "df -h >/dev/null; echo \"rc=$?\"", "ls >/dev/null 2>&1; echo done",
    "ls 2>/dev/null;", "ls >/dev/null 2>&1\n", "ls 2>/dev/null\n\ndf -h",        # a redirect, then nothing more
    "printf '%s\\n' ok", "df -h\nfree -m", "ls -la \\\n/var/log", "df -h;", "df -h\n\nfree -m\n",
    "ls -la &&\ncat /etc/hosts", "ps aux |\ngrep java",
    # quoted text is data
    "grep ';' /etc/app.conf", 'grep "a|b" /etc/app.conf', "echo 'a > b'", "grep '$HOME' /etc/profile",
    'echo "x#y"', "grep '#include' /srv/main.c", "echo a#b", "grep '`' /etc/app.conf", "grep '(' /etc/app.conf",
    'grep "it\'s" /var/log/app.log', "echo 'a\\'", "ls 'my file'",
    # journalctl
    "journalctl -u nginx -n 200 | grep error", "journalctl -u nginx --no-pager -n 50",
    'journalctl -xeu nginx --since "1 hour ago"', "journalctl -k -b -1",
    "journalctl -p err..alert --since today --no-pager | tail -n 100", "journalctl --disk-usage",
    "journalctl -u nginx -o json --lines=20", "journalctl --list-boots", "journalctl -k | grep -i oom",
    # systemctl's queries
    "systemctl status nginx", "systemctl status nginx --no-pager -l", "systemctl --no-pager status nginx",
    "systemctl is-active nginx; echo $?", "systemctl is-active nginx || true",
    "systemctl is-enabled nginx && echo enabled", "systemctl list-units --type=service --state=failed",
    "systemctl --failed", "systemctl", "systemctl --type=service list-units", "systemctl show nginx -p MainPID",
    "systemctl show nginx --property=ActiveState,SubState", "systemctl cat nginx", "systemctl list-timers --all",
    "systemctl is-failed nginx", "systemctl list-unit-files | grep enabled",
    # the network's state
    "ss -tulpn", "ss -tlnp | grep ':443'", "ss -s", "ss -o state established", "ip addr", "ip -br a",
    "ip -4 addr show dev eth0", "ip route", "ip r", "ip route get 8.8.8.8", "ip -s link show eth0",
    "ip neigh show", "ip -s -s link", "ip rule list", "ip netns list",
    # kernel parameters
    "sysctl -a | grep ipv4", "sysctl net.ipv4.ip_forward", "sysctl -n vm.swappiness", "sysctl -a",
    # what is installed
    "dpkg -l | grep nginx", "dpkg -l 'nginx*'", "dpkg -s nginx", "dpkg -L nginx", "dpkg -S /usr/sbin/nginx",
    "dpkg-query -W -f='${Package} ${Version}\\n' nginx", "dpkg-query -l nginx",
    "rpm -qa | grep nginx", "rpm -q nginx", "rpm -qi nginx", "rpm -ql nginx", "rpm -qf /usr/sbin/nginx",
    "rpm -qa --last | head", "rpm -q --qf '%{NAME}-%{VERSION}\\n' nginx", "rpm -q --changelog nginx | head",
    "apt-cache policy nginx", "apt-cache show nginx", "apt list --installed | grep nginx", "apt list --upgradable",
    # sort and uniq at the end of a pipe
    "cat /var/log/syslog | sort | uniq -c | sort -rn | head", "cut -d: -f1 /etc/passwd | sort -u",
    "cat /tmp/x | sort -t: -k2,2n", "cat /tmp/x | sort -k 2 | uniq -d", "ps aux | sort -nrk 3 | head",
    "cat /tmp/x | uniq -f1 -c", "cat /tmp/x | uniq --count",
]

REFUSED = [
    # what the run-time classifier calls a read because of how the line begins
    "cat /etc/hosts && systemctl restart nginx", "cat x; rm -rf /tmp/y", "ls x\nrm -rf y", "ls a\\\\\nrm -rf y",
    "df -h | tee /tmp/out", "ps aux | xargs kill", "ps aux | awk '{print $2}'",
    "echo 'x' | sed -n 'w /etc/cron.d/x'", "sed -n 'w /etc/cron.d/x' /etc/passwd",
    "awk 'BEGIN{system(\"touch /tmp/x\")}'", "find / -name x -exec rm {} \\;", "find /tmp -delete", "find /var/log",
    "tee /etc/cron.d/x", "strace -f sh -c 'touch /tmp/x'", "env X=1 sh -c 'touch /tmp/x'", "env",
    "curl -s -o /etc/cron.d/x http://example.com/x", "curl -s -X POST http://example.com",
    "curl -s http://example.com", "wget -q -O /tmp/x http://example.com", "sudo cat /etc/shadow",
    "timeout 5 rm -rf x", "nohup sh -c x", "sh -c 'rm x'", "bash -c 'rm x'", "watch ls", "time ls", "command ls",
    "exec ls", "eval ls", "date -s '2020-01-01'", "date", "hostname new-name", "mount -o remount,rw /", "dmesg -C",
    "dmesg", "less /etc/passwd", "tcpdump -w /tmp/x", "nmap 10.0.0.0/8", "ifconfig eth0 down",
    "route add default gw 10.0.0.1", "arp -d 10.0.0.1", "ethtool -s eth0 speed 100",
    "tc qdisc add dev eth0 root netem delay 100ms", "sar -o /tmp/x", "timedatectl set-time 2020-01-01",
    "hostnamectl set-hostname x", "kill -9 1", "systemctl restart nginx", "rm -rf /tmp/x", "touch /tmp/x",
    "chmod 777 /etc/passwd", "service nginx restart", "docker exec web ls", "docker run alpine", "docker rm web",
    "docker -H tcp://10.0.0.1 ps", "docker", "fdisk /dev/sda", "fdisk", "sshd", "pkill nginx",
    # a redirect to anything but nowhere
    "ls > /tmp/out", "ls >> /tmp/out", "echo x > /etc/cron.d/x", "cat /dev/zero >/dev/nullx",
    'ls >/dev/null"x"', "ls > /dev/null/x", "ls >/dev/null\\ x", "ls 2>/tmp/err", "ls &> /tmp/all",
    "ls >& /tmp/all", "cat < /etc/passwd", "cat <<EOF\nx\nEOF", "cat <<< x", "ls 2>&1x", "ls 3>/tmp/x",
    "ls >/dev/nul", "echo x >/dev/sda", "ls 1>&2", "ls 2>&-",
    # `&>` is bash's spelling. To dash — /bin/sh on Debian and Ubuntu — «a &>/dev/null b c» is «a &» and then «b c»
    # with its output thrown away: the second command RUNS (found by the 5,000-line run in real shells)
    "cat x &>/dev/null systemctl restart nginx", "ls &>/dev/null; echo done", "ls &>/dev/null", "ls &> /dev/null",
    "cat\t2&>/dev/null", "printf&>/dev/null -l sysctl,", "cd&>/dev/null ,uniq", "ls &>>/dev/null",
    # substitutions and expansions
    "echo $(touch /tmp/x)", "echo `touch /tmp/x`", "ls $HOME", "echo ${HOME}", "echo $'a\\'' ; systemctl restart nginx #'",
    'echo $"x"', "echo $[1+1]", "echo $((1+1))", 'echo "$(id)"', 'echo "`id`"', 'echo "$HOME"', "ls ~/$USER",
    "cat <(ls)", "echo $_", "echo $", "echo $1", "echo $$", 'grep "a$b" /etc/x', "sort -k$? /tmp/x",
    "systemctl is-active nginx; ls $?",
    # groups, subshells, brace expansion, background jobs, comments
    "(ls)", "{ ls; }", "ls &", "ls &\nrm x", "ls & rm x", "ls |& cat", "sort {-o,/etc/x}", "ls /var/log/{a,b}",
    "ls & df -h", "ping -c 100000 10.0.0.1 & echo started",          # two reads — but one is left running behind
    "ls # then rm -rf /", "ls #", "# ls", "ls;#x", "ls *(e:'id':)", "echo x(y)", "ls )",
    # journalctl: what cleans, rotates or writes
    "journalctl --vacuum-size=1M", "journalctl --vacuum-time 1s", "journalctl --vacuum-files=1", "journalctl --vac=1",
    "journalctl --rotate", "journalctl --rot", "journalctl --flush", "journalctl --sync",
    "journalctl --relinquish-var", "journalctl --smart-relinquish-var", "journalctl --setup-keys",
    "journalctl --update-catalog", "journalctl --cursor-file=/etc/x", "journalctl --cursor-f /etc/x",
    "journalctl -u nginx --rotate", "journalctl -u ngin[x]", "journalctl --image=/x.raw",
    # systemctl: anything but a query, and a query somewhere else
    "systemctl stop nginx", "systemctl start nginx", "systemctl reload nginx", "systemctl enable nginx",
    "systemctl disable nginx", "systemctl daemon-reload", "systemctl kill nginx", "systemctl mask nginx",
    "systemctl set-property nginx CPUQuota=10%", "systemctl edit nginx", "systemctl isolate rescue.target",
    "systemctl set-default multi-user.target", "systemctl -p status restart nginx",
    "systemctl -t status restart nginx", "systemctl -n 5 status nginx", "systemctl -H root@other status nginx",
    "systemctl status nginx -H other", "systemctl --host=other status nginx", "systemctl --ho other status nginx",
    "systemctl -M box status x", "systemctl --machine=box status x", "systemctl status nginx --image=/x",
    "systemctl -lH other status nginx", "systemctl status nginx -lHother", "systemctl show-environment",
    "systemctl list-machines", "systemctl Status nginx",
    # ip: only the shapes that show
    "ip a a 10.0.0.1/24 dev eth0", "ip addr add 10.0.0.1/24 dev eth0", "ip link set eth0 down", "ip l s eth0 down",
    "ip link s eth0 down", "ip a s", "ip route add default via 10.0.0.1", "ip route del default",
    "ip route flush cache", "ip r f cache", "ip netns exec ns sh", "ip -all netns exec sh", "ip vrf exec blue sh",
    "ip -batch -", "ip -b /tmp/x", "ip -force -batch /tmp/x", "echo 'link set dev eth0 down' | ip -batch -",
    "ip -b addr show", "ip -batch addr", "ip -force link show", "ip -n addr show", "ip -f inet addr show",
    "ip -rc 1 addr",                 # an option the rule does not know, straight before an object it does
    "ip -n ns addr show", "ip xfrm state", "ip monitor", "ip addr show -batch x", "ip", "ip -4", "ip link get x",
    "ip addr flush dev eth0", "ip neigh del 10.0.0.1 dev eth0", "ip a*",
    # ss: nothing that closes a socket or dumps to a file
    "ss -K dst 10.0.0.1", "ss -tK", "ss --kill", "ss --ki", "ss -D /tmp/x", "ss --diag=/tmp/x", "ss -tD/tmp/x",
    # sysctl: reads only
    "sysctl -w vm.swappiness=10", "sysctl vm.swappiness=10", "sysctl -p", "sysctl -p /etc/x", "sysctl --system",
    "sysctl --load", "sysctl -f /etc/x", "sysctl -an", "sysctl --write vm.swappiness=10",
    # packages: queries only
    "dpkg -i x.deb", "dpkg -r nginx", "dpkg -P nginx", "dpkg --configure -a", "dpkg --purge nginx", "dpkg",
    "dpkg -l --status-logger='touch /tmp/x'", "dpkg -l --admindir=/x", "dpkg-query --admindir=/x -l",
    "rpm -e nginx", "rpm -i x.rpm", "rpm -Uvh x.rpm", "rpm -qa --pipe 'sh'", "rpm -q --eval '%(touch /tmp/x)'",
    "rpm --eval x", "rpm -q --define '_x 1' nginx", "rpm -q -E x", "rpm -qp http://example.com/y.rpm",
    "rpm -qe nginx", "rpm -q --specfile x.spec", "rpm", "rpm -V nginx", "rpm -q --root /x nginx", "rpm -q ngin*",
    "apt-get install x", "apt install x", "apt remove x", "apt update", "apt", "apt-cache",
    "apt-cache -o Dir::Cache=/x policy", "apt-cache policy -o x=y", "apt list -o APT::X=1", "apt-cache gencaches",
    # sort and uniq: no output file
    "sort -o /etc/cron.d/x", "sort -no out", "sort --output=x", "sort --out x", "sort --o=x", "sort -T /x y",
    "sort --compress-program=sh x", "ps aux | sort -o /etc/cron.d/x", "sort -- -o", "sort *",
    "ps aux | uniq - /etc/cron.d/x", "uniq in out", "uniq -c f", "uniq --group", "uniq -f 2",
    # what was on the «cannot write» list and can, with the right option
    "printf -v X %s y", "printf -vX y", "file -C -m x", "file /etc/passwd", "ssh-keygen -l -R host",
    "ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub", "ssh-add -l", "openssl s_client -connect a:443",
    "echo x | openssl s_client -connect a:443 -quiet",
    # not written as the command is
    "CAT /etc/passwd", "Ls", "/bin/ls", "./ls", "''", '""', "X=1 ls", "LD_PRELOAD=/x ls", "! ls",
    "if true; then ls; fi", "for i in 1; do ls; done", "while true; do ls; done",
    # cannot be read
    "ls 'x", 'ls "x', "ls \\", "ls \x1b[0m", "ls\r\nrm x", "ls\x00", "", "   ", "\n", ";", "| ls", "ls ||",
    "ls &&", "&& ls", "ls | | cat", "ls;;", "; ls", "ls /tmp ;; ls /var", "ls |", "ls ||\n", "ls;\n;",
    # a redirect with no command: nothing to sh, `cat` to zsh (found by running the lines in real shells)
    "2>/dev/null", "ls; >/dev/null", "journalctl\n 2>/dev/null ", ">/dev/null 2>&1", "ls | 2>&1",
]


@pytest.mark.parametrize("line", READS)
def test_a_line_of_reads_is_a_read(line):
    assert host_reads_only(line) is True


@pytest.mark.parametrize("line", REFUSED)
def test_a_line_the_rule_does_not_know_is_refused(line):
    assert host_reads_only(line) is False


def test_the_two_tables_have_no_line_twice():
    assert len(set(READS)) == len(READS) and len(set(REFUSED)) == len(REFUSED) and not set(READS) & set(REFUSED)


def test_the_tier_a_host_tool_takes_in_such_a_run():
    assert read_only_host_tier("ps aux | grep java", "readonly") == "readonly"
    assert read_only_host_tier("systemctl status nginx", "unknown") == "readonly"       # a query: no question any more
    assert read_only_host_tier("apt list --installed", "write") == "readonly"            # «apt» is a write word at run time
    assert read_only_host_tier("cat /etc/hosts && systemctl restart nginx", "readonly") == "unknown"
    assert read_only_host_tier("ps aux | awk '{print $2}'", "readonly") == "unknown"
    assert read_only_host_tier("kill -9 1", "write") == "write"                          # a write stays called one
    assert read_only_host_tier("make install", "unknown") == "unknown"


def test_the_hint_names_no_cloud():
    hint = change_steps.HOST_READS_HINT.lower()
    assert "sudo" in hint and "awk" in hint and "/dev/null" in hint
    for word in ("aws", "amazon", "ssm", "ec2", "azure", "gcloud", "aliyun"):
        assert word not in hint


# ── the shell runs what the rule read ────────────────────────────────────────

# every first word the rule lets through, as a stub that only writes down how it was called
STUBS = sorted({entry.split()[0] for entry in change_steps.HOST_READS} | set(change_steps.HOST_GUARDS))
# the shells a host may hand the line to. `sh` is bash or dash on every common system: it is run only where neither
# is present under its own name
SHELLS = [s for s in ("bash", "zsh", "dash") if shutil.which(s)]
if not {"bash", "dash"} & set(SHELLS) and shutil.which("sh"):
    SHELLS.append("sh")


@pytest.fixture(scope="module")
def stubs(tmp_path_factory):
    """A directory that is the whole PATH: one stub per command the rule knows, each appending the words it was
    called with to a file of its own, $NF_LOG.<its pid> (a NUL after each word, a record separator after each call:
    the stubs of one pipeline run at the same time, and one shared file was written in pieces) — and nothing else, so
    a line that reaches for any other command fails with «not found» instead of running it."""
    bin_dir = tmp_path_factory.mktemp("stub-bin")
    for name in STUBS:
        stub = bin_dir / name
        stub.write_text('#!/bin/sh\n{ for a in "$0" "$@"; do printf \'%s\\0\' "$a"; done; printf \'\\036\\0\'; } >> "$NF_LOG.$$"\n')
        stub.chmod(0o755)
    return bin_dir


def _run_in(shell, line, stubs, tmp_path):
    """Run `line` in a real shell whose PATH holds only the stubs → (the argv of every stub call, the files the
    line left in its directory, the shell's stderr)."""
    import tempfile
    work = pathlib.Path(tempfile.mkdtemp(prefix=f"{shell}-", dir=tmp_path))
    logs = pathlib.Path(tempfile.mkdtemp(prefix=f"{shell}-calls-", dir=tmp_path))
    env = {"PATH": str(stubs), "NF_LOG": str(logs / "call"), "HOME": str(work), "LC_ALL": "C"}
    done = subprocess.run([shutil.which(shell), "-c", line], cwd=work, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=20)
    calls = []
    for record in sorted(logs.iterdir()):
        words = []
        for word in record.read_bytes().decode("utf-8", "replace").split("\0")[:-1]:
            if word == "\x1e":
                calls.append([os.path.basename(words[0])] + words[1:])
                words = []
            else:
                words.append(word)
    return calls, sorted(p.name for p in work.iterdir()), done.stderr


def _read_as(line):
    """The words the rule read for each simple command of `line` — None when the line holds a glob or `$?`: the
    shell then changes the words, and only what was started is checked."""
    commands = change_steps._simple_commands(line)
    if any(globs or status for _text, globs, status in commands):
        return None
    return [shlex.split(text) for text, _globs, _status in commands]


def _diverges(shell, line, stubs, tmp_path):
    """What a real shell did with `line` that the rule did not read — None when nothing. It left a file; it reached
    for a command that is no stub; it started a command the rule would not vouch for; or it handed a command words
    other than the ones the rule read."""
    calls, left, stderr = _run_in(shell, line, stubs, tmp_path)
    if left:
        return f"left {left}"
    if "not found" in stderr:
        return f"reached for something else: {stderr.strip()[:200]}"
    read = _read_as(line)
    for argv in calls:
        if not change_steps.host_command_reads(argv):
            return f"started {argv}"
        if read is not None and argv not in read:
            return f"handed {argv} — the rule read {read}"
    return None


@pytest.mark.parametrize("shell", SHELLS)
def test_a_real_shell_runs_only_what_the_rule_read(shell, stubs, tmp_path):
    """Every line of READS, run by a real shell: each command it starts is one the rule vouches for, called with
    the words the rule read; nothing is left in the directory; nothing the rule does not know was reached for."""
    for line in READS:
        if "cd " in line or "\\ls" in line:
            continue                    # `cd` to a directory that is not there ends the chain; \ls is the same call
        assert _diverges(shell, line, stubs, tmp_path) is None, (shell, line)


def test_the_stubs_see_a_write_the_rule_refuses(stubs, tmp_path):
    # the control for the test above: with a line the rule refuses, the same harness shows what the rule prevents
    shell = SHELLS[0]
    calls, left, _ = _run_in(shell, "ps aux | sort -o out", stubs, tmp_path)
    assert ["sort", "-o", "out"] in calls and not change_steps.host_command_reads(["sort", "-o", "out"])
    assert _diverges(shell, "ps aux | sort -o out", stubs, tmp_path) == "started ['sort', '-o', 'out']"
    assert _diverges(shell, "echo x > out", stubs, tmp_path) == "left ['out']"
    assert _diverges(shell, "ls; rm -rf y", stubs, tmp_path).startswith("reached for something else")
    calls, _, _ = _run_in(shell, "ls 'a b' \"c\nd\" ''", stubs, tmp_path)
    assert calls == [["ls", "a b", "c\nd", ""]]                   # words arrive whole: a space, a line break, an empty one
    with patch.object(change_steps, "_simple_commands", return_value=[("ls x", False, False)]):
        assert _diverges(shell, "ls y", stubs, tmp_path) == "handed ['ls', 'y'] — the rule read [['ls', 'x']]"


# ── where a run may only read ────────────────────────────────────────────────

def test_which_contexts_may_only_read(tmp_path, monkeypatch):
    _temp_db(tmp_path, monkeypatch, "ctx.db")
    assert read_only_context() is False
    for fields in ({"read_only": True}, {"read_only_run": "diagnosis"}, {"read_only_run": "plan"},
                   {"change_request_id": 3}, {"change_request_id": 3, "fix_plan_id": 999}):
        with run_context(**fields):
            assert read_only_context() is True, fields
            assert change_context_refusal(tool="run_on_host", tier="write", command="kill -9 1") is not None
    with run_context(change_request_id=3, fix_plan_id=7), \
            patch("agenticops.services.command_audit.approved_plan_in_context", return_value=7):
        assert read_only_context() is False                       # a change whose plan was approved is being run
        assert change_context_refusal(tool="run_on_host", tier="write", command="kill -9 1") is None
    with run_context(fix_plan_id=7):
        assert read_only_context() is False                       # an executor run


# ── the two host tools ───────────────────────────────────────────────────────

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    settings = _temp_db(tmp_path, monkeypatch, "host.db")
    monkeypatch.setattr(settings, "command_audit_enabled", True)
    monkeypatch.setattr(settings, "change_management_enabled", True)
    s = get_session()
    yield s
    s.close()


def _rows(db):
    db.expire_all()
    return [(r.tool, r.tier, r.outcome, r.reason) for r in db.query(CommandAudit).order_by(CommandAudit.id)]


CONTEXTS = [({"read_only_run": "diagnosis"}, "read_only_run"), ({"read_only_run": "plan"}, "read_only_run"),
            ({"change_request_id": 3}, "change_not_approved"), ({"read_only": True}, "read_only_account")]
HOST = "i-0123456789abcdef0"


def _host(command, **kw):
    from agenticops.skills.execution import run_on_host
    return run_on_host(host_id=HOST, command=command, **kw)


@pytest.mark.parametrize("fields,reason", CONTEXTS)
@pytest.mark.parametrize("command", ["cat /etc/hosts && systemctl restart nginx", "ps aux | xargs kill",
                                     "echo x | sed -n 'w /etc/cron.d/x'", "ls a\\\\\nrm -rf y", "ls > /tmp/out"])
def test_a_line_that_only_begins_like_a_read_is_not_sent(ledger, fields, reason, command):
    with run_context(**fields), patch("agenticops.skills.execution._run_auto_ladder") as ladder:
        for confirmed in (False, True):
            out = _host(command, require_confirmation=confirmed)
            assert change_steps.HOST_READS_HINT in out and out.endswith("Command: " + command)
    assert not ladder.called
    assert _rows(ledger) == [("run_on_host", "unknown", "refused", reason)] * 2


@pytest.mark.parametrize("fields,_reason", CONTEXTS)
@pytest.mark.parametrize("command", ["systemctl status nginx", "ps aux | grep java", "df -h; free -m",
                                     "journalctl -u nginx -n 200 | grep error", "dpkg -l | grep nginx",
                                     "apt list --installed"])
def test_a_line_of_reads_is_sent_without_a_question(ledger, fields, _reason, command):
    with run_context(**fields), patch("agenticops.skills.execution._run_auto_ladder", return_value="out") as ladder:
        assert _host(command) == "out"
    assert ladder.called and _rows(ledger) == []                  # a read: nothing asked, nothing on the ledger


@pytest.mark.parametrize("fields,reason", CONTEXTS)
def test_a_write_stays_called_a_write(ledger, fields, reason):
    with run_context(**fields), patch("agenticops.skills.execution._run_auto_ladder") as ladder:
        assert "Command: kill -9 1" in _host("kill -9 1", require_confirmation=True)
    assert not ladder.called
    assert _rows(ledger) == [("run_on_host", "write", "refused", reason)]


@pytest.mark.parametrize("fields,_reason", CONTEXTS)
def test_what_is_blocked_stays_blocked(ledger, fields, _reason):
    with run_context(**fields), patch("agenticops.skills.execution._run_auto_ladder") as ladder:
        assert "blocked for safety" in _host("ls; shutdown -h now")
    assert not ladder.called
    assert _rows(ledger) == [("run_on_host", "blocked", "blocked", None)]


def test_outside_such_a_run_reads_joined_together_are_still_reads(ledger):
    # chat and the executor: a line of reads only is a read; one that hides a second command that is not a read
    # asks first since «之后» 22 step 1 (tests/test_host_second_command.py)
    with patch("agenticops.skills.execution._run_auto_ladder", return_value="out") as ladder:
        assert _host("cat /etc/hosts && echo done") == "out"            # no question, no ledger row
        asked = _host("systemctl status nginx")                         # … and a query still asks first
    assert ladder.call_count == 1 and "requires confirmation" in asked
    assert _rows(ledger) == [("run_on_host", "unknown", "refused", "confirmation")]


def test_a_change_being_run_under_its_approved_plan_is_as_it_was(ledger):
    with run_context(change_request_id=3, fix_plan_id=7), \
            patch("agenticops.services.command_audit.approved_plan_in_context", return_value=7), \
            patch("agenticops.skills.execution._run_auto_ladder", return_value="out") as ladder:
        assert _host("systemctl reload nginx", require_confirmation=True) == "out"
    assert ladder.called and _rows(ledger) == [("run_on_host", "write", "executed", None)]


def _ssh_tool(monkeypatch):
    from agenticops.providers.ssh import SSHProvider
    creds = {"host": "10.0.0.5", "username": "ops"}
    provider = SSHProvider(SimpleNamespace(id=1, name="idc-1", provider="ssh", credentials=creds, regions=[], labels={}))
    provider._cfg = dict(creds)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="out\n", stderr=""))
    monkeypatch.setattr("agenticops.providers.ssh.subprocess.run", run)
    return provider.cli_tool(), run


@pytest.mark.parametrize("fields,reason", CONTEXTS)
def test_the_account_bound_host_tool_follows_the_same_rule(ledger, monkeypatch, fields, reason):
    tool, run = _ssh_tool(monkeypatch)
    with run_context(**fields):
        refused = tool("cat /etc/hosts && systemctl reload nginx")
        assert change_steps.HOST_READS_HINT in refused and not run.called
        assert tool("systemctl status nginx") == "out\n" and run.call_count == 1
        assert tool("df -h | sort -k5") == "out\n" and run.call_count == 2
    assert _rows(ledger) == [("provider_ssh", "unknown", "refused", reason)]


def test_the_account_bound_host_tool_outside_such_a_run_asks_first(ledger, monkeypatch):
    # it had no confirmation and ran every write it was sent; since «之后» 22 step 1 it asks, as run_on_host does
    tool, run = _ssh_tool(monkeypatch)
    assert tool("cat /etc/hosts && echo done") == "out\n"                # reads only: as before
    assert "requires confirmation" in tool("systemctl status nginx")       # tier unknown: it asks first
    assert tool("systemctl status nginx", require_confirmation=True) == "out\n"
    assert run.call_count == 2 and _rows(ledger) == [("provider_ssh", "unknown", "refused", "confirmation"),
                                                     ("provider_ssh", "unknown", "executed", None)]


def test_a_refusal_of_another_tool_carries_no_host_hint(ledger):
    with run_context(read_only_run="plan"):
        out = change_context_refusal(tool="run_kubectl", tier="write", command="delete pod x")
    assert change_steps.HOST_READS_HINT not in out


# ── a plan step's label: three corrections found on the way ──────────────────

@pytest.mark.parametrize("command", [
    "cat /dev/zero >/dev/nullx", 'ls >/dev/null"x"', "ls > /dev/null/x", "ls 2>/dev/nullx", "ls &>/dev/null.log",
    "ls 2>&1x", "kubectl get pods >/dev/nullx", "aws ec2 describe-instances 2>/dev/null2",
])
def test_a_redirect_that_only_begins_like_dev_null_is_a_redirect(command):
    assert command_tier(command) == "unknown"


@pytest.mark.parametrize("command", ["ls -la 2>/dev/null", "ls >/dev/null 2>&1", "df -h 2>/dev/null",
                                     "kubectl get pods -n web 2>/dev/null", "ls 2>&1", "ls 1>/dev/null"])
def test_a_redirect_to_nowhere_still_changes_nothing(command):
    assert command_tier(command) == "readonly"


@pytest.mark.parametrize("command", ["ls &>/dev/null", "cat /etc/hosts &>/dev/null systemctl restart nginx",
                                     "df -h &> /dev/null", "kubectl get pods &>/dev/null"])
def test_the_bash_spelling_of_both_streams_to_nowhere_is_not_one_command_to_every_shell(command):
    # to dash — /bin/sh on Debian and Ubuntu — «a &>/dev/null b» runs a in the background, then runs b
    assert command_tier(command) == "unknown"


def test_an_escaped_backslash_before_a_line_break_does_not_join_the_lines():
    assert command_tier("ls a\\\\\nrm -rf y") == "unknown"               # ls a\\ ⏎ rm -rf y: two commands
    assert command_tier("ls a\\\\\\\nb") == "readonly"                   # ls a\\\ ⏎ b: a backslash, then a continued line
    assert command_tier("ls -la \\\n  /var/log") == "readonly"           # a continued line is one command, as before


@pytest.mark.parametrize("command", [
    "file -C -m /tmp/magic", "ssh-keygen -l -R old-host -f /root/.ssh/known_hosts",
    "ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub", "ssh-add -l",
    "openssl s_client -connect a:443 -keylogfile /etc/cron.d/x",
])
def test_a_word_that_can_write_with_the_right_option_is_not_on_the_cannot_write_list(command):
    assert command_tier(command) == "unknown"
    entry = change_steps._host_entry(" ".join(command.split()).lower())
    assert entry in change_steps.HOST_CAN_WRITE and entry not in change_steps.HOST_CANNOT_WRITE


# ── the same check on lines nobody wrote ─────────────────────────────────────

_FUZZ_WORDS = ["ls", "cat", "sort", "uniq", "echo", "printf", "true", "cd", "grep", "head", "ip", "ss", "sysctl",
               "systemctl", "journalctl", "rpm", "dpkg", "apt", "x", "out", "status", "show", "list", "addr", "nginx",
               "-o", "-c", "-n", "-K", "-q", "-l", "-v", "-k2", "--rotate", "--output=out", "/dev/null", "a b", "1", "2"]
# punctuation the rule reads (most picks) and punctuation it refuses unless quoted (one pick in ten): a refused mark
# inside quotes is data, and a line that holds one there is exactly what must be read as the shell reads it
_FUZZ_READ = [" ", " ", " ", ";", "|", "||", "&&", "'", "'", '"', '"', "\\", "\\", "\n", "\t", "2>&1", ">/dev/null",
              " 2>/dev/null", " 2>&1", "$?", "*", "-", "--", ","]
_FUZZ_SHARP = ["&", ">", ">>", "<", "2>", "&>", "&>/dev/null", "$", "(", ")", "{", "}", "`", "#", "?", "[", "]", "$(", "${"]


def _fuzz_lines(seed: int, wanted: int, attempts: int = 3_000_000):
    """Lines put together at random from words and shell punctuation → (those the rule lets through, how many were
    made). Deterministic for a seed."""
    import random
    rng = random.Random(seed)
    kept, seen, made = [], set(), 0
    while len(kept) < wanted and made < attempts:
        made += 1
        parts = []
        for _ in range(rng.randint(2, 14)):
            pick = rng.random()
            parts.append(rng.choice(_FUZZ_WORDS if pick < 0.45 else _FUZZ_READ if pick < 0.9 else _FUZZ_SHARP))
        line = "".join(parts)
        if line not in seen and host_reads_only(line):
            seen.add(line)
            kept.append(line)
    return kept, made


@pytest.mark.parametrize("shell", SHELLS)
def test_a_real_shell_runs_only_what_the_rule_read_in_lines_made_at_random(shell, stubs, tmp_path):
    """NF_HOST_FUZZ_LINES=<n> runs more of them (the release's check ran 5,000 per shell)."""
    wanted = int(os.environ.get("NF_HOST_FUZZ_LINES", "60"))
    lines, made = _fuzz_lines(20261122, wanted)
    assert len(lines) == wanted, (len(lines), made)               # the generator still finds lines the rule accepts
    found = [(line, why) for line in lines if (why := _diverges(shell, line, stubs, tmp_path))]
    assert not found, (shell, found[:5])


# ── what «cannot write» leans on: no terminal ────────────────────────────────

def test_neither_ssh_path_asks_for_a_terminal(monkeypatch):
    """`more`, `top` and the pager of journalctl / systemctl only read while there is no terminal: given one, a
    pager takes keys — and a pager's keys run commands. Both paths capture the output and ask ssh for no terminal
    (the third path, a remote shell script through the cloud's agent, has none to give)."""
    from agenticops.skills import execution

    def no_terminal(run):
        argv = run.call_args[0][0]
        assert argv[0] == "ssh" and not {"-t", "-tt"} & set(argv) and not any("RequestTTY" in a for a in argv), argv
        assert run.call_args[1]["capture_output"] is True and run.call_args[1]["shell"] is False

    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="ok\n", stderr=""))
    monkeypatch.setattr("agenticops.skills.execution.subprocess.run", run)
    execution._execute_ssh("10.0.1.5", "journalctl -u nginx -n 20", user="ops", key_path="/k", bastion="jump.example.com")
    no_terminal(run)

    tool, run = _ssh_tool(monkeypatch)
    assert tool("journalctl -u nginx -n 20") == "out\n"
    no_terminal(run)

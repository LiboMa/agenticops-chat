"""A change request's own steps (MVP-2.6.1 spec §3.D.2): their shape, the commands no review can pass, and the
difference between what was asked for and what the SRE planned — computed here, never by an LLM.

Steps have the fix_plans.steps shape: an ordered list of {"action": str, "command": str}.
"""

import json
import re
import shlex
from difflib import SequenceMatcher
from typing import Optional

MAX_STEPS = 50
MAX_COMMAND_CHARS = 2000
MAX_ACTION_CHARS = 500


def normalize_steps(raw) -> Optional[list[dict]]:
    """The requester's steps as stored, or None when none were given. Raises ValueError on a bad shape."""
    if raw is None or raw == []:
        return None
    if not isinstance(raw, list):
        raise ValueError("proposed_steps must be a list of {action, command} steps")
    if len(raw) > MAX_STEPS:
        raise ValueError(f"too many proposed steps (max {MAX_STEPS})")
    steps = []
    for n, step in enumerate(raw, 1):
        if not isinstance(step, dict):
            raise ValueError(f"proposed step {n} must be an object with a command")
        command = str(step.get("command") or "").strip()
        if not command:
            raise ValueError(f"proposed step {n} has no command")
        if len(command) > MAX_COMMAND_CHARS:
            raise ValueError(f"proposed step {n} command too long (max {MAX_COMMAND_CHARS} characters)")
        steps.append({"action": str(step.get("action") or "").strip()[:MAX_ACTION_CHARS], "command": command})
    return steps


def _raw_command(step) -> str:
    return str((step.get("command") or "") if isinstance(step, dict) else (step or ""))


def _command(step) -> str:
    return " ".join(_raw_command(step).split())


# skills/security.SHELL_READONLY_COMMANDS is the run-time gate of run_on_host: it answers «may this run without
# asking». A plan step's label — and the auto-approval floor — ask something narrower: «can this line change
# anything». Only the entries that cannot write whatever their arguments keep 'readonly' here; the others (find
# -delete, tee, xargs rm, journalctl --vacuum-size, sort -o, date -s, curl -s -X DELETE, env VAR=1 cmd …) are
# 'unknown': a person looks. tests/test_plan_step_tiers.py fails when the run-time list gains an entry nobody put
# on one side. N30 moved five entries to the other side — each writes with the right option: `file -C` compiles a
# magic file, `ssh-keygen -l … -R host` / `-H` rewrite known_hosts (those modes are acted on before the listing),
# `ssh-add -l -x` locks the agent, `openssl s_client -keylogfile F` writes F (and sends what its stdin holds).
HOST_CANNOT_WRITE = frozenset({
    "ls", "cat", "head", "tail", "more", "stat", "wc", "locate", "which", "whereis", "readlink",
    "ps", "top", "htop", "pgrep", "pidof", "lsof",
    "uname", "uptime", "who", "w", "whoami", "id", "groups",
    "free", "vmstat", "iostat", "mpstat", "nproc", "lscpu", "df", "du", "lsblk", "fdisk -l",
    "netstat", "ping", "traceroute", "tracepath", "mtr", "dig", "nslookup", "host",
    "last", "lastb",
    "grep", "egrep", "fgrep", "cut", "tr", "diff", "comm",
    "docker ps", "docker logs", "docker inspect", "docker images", "docker stats", "docker top", "docker port",
    "docker diff", "docker history", "docker network ls", "docker network inspect", "docker volume ls",
    "docker volume inspect",
    "ssh-keyscan", "sshd -t",
    "printenv",
})
HOST_CAN_WRITE = frozenset({
    "less", "find", "hostname", "date", "timedatectl", "hostnamectl", "sar", "blkid", "mount",
    "ss", "ip", "ifconfig", "nmap", "arp", "route", "iperf", "iperf3", "ethtool", "tc",
    "journalctl", "dmesg", "lastlog",
    "awk", "sed -n", "sort", "uniq", "tee", "xargs",
    "strace", "ltrace", "tcpdump", "sysctl -a",
    "curl -s", "curl --silent", "wget -q", "env", "set",
    "file", "ssh-add -l", "ssh-keygen -lf", "ssh-keygen -l", "openssl s_client",
})

# A line continued with a backslash: an ODD run of backslashes before the line break. An even run is escaped
# backslashes and the line ends there — until N30 «ls a\\\\ ⏎ rm -rf y» was joined into one `ls` and called read-only.
_CONTINUED = re.compile(r"(?<!\\)((?:\\\\)*)\\\r?\n")
# Sends nothing anywhere that matters — and ends there: until N30 `> /dev/nullx` (a file) was read as `> /dev/null`.
# Bash's `&>/dev/null` is NOT here (it was until N30): to dash — /bin/sh on Debian and Ubuntu — «a &>/dev/null b c»
# is «a &» and then «b c» with its output thrown away, so the second command runs. Found by running 5,000 accepted
# lines in real shells; `>/dev/null 2>&1` says the same thing to every shell.
_HARMLESS_REDIRECT = re.compile(r"(?:[12]?>{1,2}\s*/dev/null|2>&1)(?=$|[\s;&|<>)])")


def _shell_would_split(text: str) -> bool:
    """True when a shell would read more than one simple command in `text`, send its output somewhere, or when the
    line carries a comment: an unquoted ; & | < > ( ), a backtick or $( outside single quotes, a # that begins a
    word. Quoted text is data (a JMESPath `--query` is full of | & > and backticks) and `2>/dev/null` / `2>&1`
    change nothing, so neither counts. A comment changes nothing for a shell, but it is free text beside the
    command — the code cannot classify it, and the agent that runs the step reads it («… # then archive the
    finding»): such a line is not «one command»."""
    text = _HARMLESS_REDIRECT.sub(" ", text)
    quote, i = None, 0
    while i < len(text):
        c = text[i]
        if quote == "'":
            if c == "'":
                quote = None
        elif c == "\\":
            i += 1                                   # the next character is literal
        elif quote == '"':
            if c == '"':
                quote = None
            elif c == "`" or text.startswith("$(", i):
                return True                          # still runs inside double quotes
        elif c in "'\"":
            quote = c
        elif c in ";&|<>()`":
            return True
        elif c == "#" and (i == 0 or text[i - 1].isspace()):
            return True                              # a comment (a # inside a word is not one)
        i += 1
    return False


def _host_entry(lowered: str) -> str:
    """The run-time list's entry `lowered` begins with (the longest, as classify_shell_command picks it)."""
    from agenticops.skills.security import SHELL_READONLY_COMMANDS

    best = ""
    for entry in SHELL_READONLY_COMMANDS:
        if (lowered == entry or lowered.startswith(entry + " ")) and len(entry) > len(best):
            best = entry
    return best


# ── a host command line in a run that may only read (MVP-2.9.0 N30) ──────────────────────────────────────────
#
# skills/security.classify_shell_command reads how the WHOLE LINE begins, and its read-only list holds words that
# write or run other commands with the right arguments: «cat x && systemctl restart nginx», «ps aux | xargs kill»
# and «echo … | sed -n 'w /etc/cron.d/x'» are «readonly» to it. In a run that may only read — a diagnosis, a fix-plan
# run, a change's review, a read-only account (services/command_audit.read_only_context) — run_on_host and the SSH
# account tool ask host_reads_only() instead: the line is read as a shell would split it, and EVERY simple command in
# it must be one this rule knows cannot change anything. It is an allow-list: what it does not know is refused, and
# a refusal costs the agent one sentence (HOST_READS_HINT). Chat and the executor are not asked this rule.

# What cannot write whatever its arguments (the list a plan step's label already uses), and four shell builtins.
HOST_READS = frozenset(HOST_CANNOT_WRITE | {"echo", "printf", "cd", "true"})
_HOST_READ_WORDS = frozenset(tuple(entry.split()) for entry in HOST_READS)

HOST_READS_HINT = (
    " On a host this run takes read commands only, alone or joined by | ; && || — ls, cat, head, tail, grep, ps, df, "
    "free, netstat, ss, ip … show, journalctl (journalctl -k for the kernel log), systemctl status / is-active / show "
    "/ list-units, dpkg -l, rpm -q, sort, uniq, echo. A redirect only to /dev/null, written >/dev/null or 2>/dev/null "
    "(not &>); no $(…), backticks or $VAR; no sudo, awk, sed, find, xargs, tee, curl.")


def _long_option_is(word: str, names) -> bool:
    """`word` is one of these long options — or a shorter spelling getopt takes for one (--rot is --rotate)."""
    name = word.split("=", 1)[0]
    return len(name) > 2 and any(full.startswith(name) for full in names)


# journalctl: every option that cleans, rotates or writes is a long one
_JOURNAL_WRITES = ("--vacuum-size", "--vacuum-time", "--vacuum-files", "--rotate", "--flush", "--sync",
                   "--relinquish-var", "--smart-relinquish-var", "--setup-keys", "--update-catalog", "--cursor-file",
                   "--image")


def _journalctl(args) -> bool:
    return not any(a.startswith("--") and _long_option_is(a, _JOURNAL_WRITES) for a in args)


# systemctl: a query, named before anything that could take the next word as its argument («-p status restart x»
# restarts x), and never on another host, a container or an image
_SYSTEMCTL_FLAGS = frozenset({"--no-pager", "--no-legend", "--plain", "--full", "-l", "--all", "-a", "--failed",
                              "--user", "--system", "-q", "--quiet"})
_SYSTEMCTL_QUERIES = frozenset({"status", "show", "cat", "is-active", "is-enabled", "is-failed", "is-system-running",
                                "get-default", "list-units", "list-unit-files", "list-timers", "list-sockets",
                                "list-dependencies", "list-jobs"})
_SYSTEMCTL_ELSEWHERE = ("--host", "--machine", "--image")


def _systemctl(args) -> bool:
    i = 0
    while i < len(args) and (args[i] in _SYSTEMCTL_FLAGS or (args[i].startswith("--") and "=" in args[i])):
        i += 1
    if i < len(args) and args[i] not in _SYSTEMCTL_QUERIES:
        return False                                     # no word at all lists the units
    for a in args:
        if a.startswith("--"):
            if _long_option_is(a, _SYSTEMCTL_ELSEWHERE):
                return False
        elif a.startswith("-") and ("H" in a or "M" in a):
            return False
    return True


# ip: its objects and commands are matched by prefix («ip a a» adds an address, «ip link s» sets a link) — only
# the exact shapes that show
_IP_FLAGS = frozenset({"-4", "-6", "-s", "-stats", "-statistics", "-d", "-details", "-o", "-oneline", "-br", "-brief",
                       "-j", "-json", "-p", "-pretty", "-c", "-color", "-h", "-human", "-r", "-resolve", "-iec", "-N",
                       "-Numeric"})
_IP_OBJECTS = frozenset({"a", "addr", "address", "l", "link", "r", "route", "n", "neigh", "neighbor", "neighbour",
                         "ru", "rule", "maddr", "maddress", "netconf", "ntable", "tunnel", "tuntap", "vrf", "netns",
                         "mroute", "nexthop"})
_IP_SHOWS = frozenset({"show", "list", "lst", "ls"})


def _ip(args) -> bool:
    i = 0
    while i < len(args) and args[i] in _IP_FLAGS:
        i += 1
    rest = args[i:]
    if not rest or rest[0] not in _IP_OBJECTS:
        return False
    if len(rest) == 1:
        return True                                      # the object alone lists it
    if rest[1] in _IP_SHOWS or (rest[1] == "get" and rest[0] in ("r", "route")):
        return not any(word.startswith("-") for word in rest[2:])
    return False


def _ss(args) -> bool:                                   # -K closes sockets, -D dumps to a file
    for a in args:
        if a.startswith("--"):
            if _long_option_is(a, ("--kill", "--diag")):
                return False
        elif a.startswith("-") and ("K" in a or "D" in a):
            return False
    return True


_SYSCTL_FLAGS = frozenset({"-a", "-A", "-X", "-n", "-N", "-e", "-b", "--all", "--values", "--names", "--ignore",
                           "--binary"})


def _sysctl(args) -> bool:                               # name=value writes, with -w or without
    return all(a in _SYSCTL_FLAGS if a.startswith("-") else "=" not in a for a in args)


_DPKG_QUERIES = frozenset({"-l", "--list", "-s", "--status", "-L", "--listfiles", "-S", "--search"})
_DPKG_QUERY_WORDS = _DPKG_QUERIES | {"-W", "--show", "-f", "--showformat", "-p", "--print-avail"}


def _dpkg(args) -> bool:                                 # one query; no other option (--status-logger runs a command)
    return bool(args) and args[0] in _DPKG_QUERIES and not any(a.startswith("-") for a in args[1:])


def _dpkg_query(args) -> bool:
    return all(a in _DPKG_QUERY_WORDS or a.startswith(("--showformat=", "-f=")) for a in args if a.startswith("-"))


# rpm: query mode over what is installed (-p reads a package file or a URL), and only options that list —
# --pipe, --eval, --define and --specfile run commands
_RPM_QUERY = re.compile(r"-q[ailfcdRsv]*")
_RPM_WORDS = frozenset({"--last", "--changelog", "--qf", "--queryformat", "--requires", "--provides", "--whatprovides",
                        "--whatrequires", "--scripts", "--all", "--info", "--list", "--file", "--configfiles",
                        "--docfiles", "--state"})


def _rpm(args) -> bool:
    return (bool(args) and bool(_RPM_QUERY.fullmatch(args[0]))
            and all(a in _RPM_WORDS or a.startswith(("--qf=", "--queryformat=")) for a in args[1:] if a.startswith("-")))


def _apt_cache(args) -> bool:                            # -o / -c set any configuration value
    return bool(args) and args[0] in ("policy", "show", "search") and not any(a.startswith("-") for a in args)


_APT_LIST_FLAGS = frozenset({"--installed", "--upgradable", "--upgradeable", "--all-versions", "-a"})


def _apt(args) -> bool:
    return bool(args) and args[0] == "list" and all(a in _APT_LIST_FLAGS for a in args[1:] if a.startswith("-"))


# sort: flags that order (a key may end the cluster: -nrk 3), a separator — never -o / --output (a file),
# --compress-program (a command), -T
_SORT_FLAG = re.compile(r"-(?:[bdfghiMmnRrsuVzc]+|[bdfghiMmnRrsuVzc]*k[0-9.,bdfghiMnRrVz]*|t.?)")


def _sort(args) -> bool:
    return all(_SORT_FLAG.fullmatch(a) for a in args if a.startswith("-"))


# uniq: its second operand is an output file — at the end of a pipe only, no operand at all
_UNIQ_FLAG = re.compile(r"-(?:[cdDiuz]+|[fsw][0-9]+)|--count|--repeated|--unique|--ignore-case")


def _uniq(args) -> bool:
    return all(_UNIQ_FLAG.fullmatch(a) for a in args)


# A word whose arguments decide: each guard is handed the words after it and answers «this only reads».
HOST_GUARDS = {"journalctl": _journalctl, "systemctl": _systemctl, "ip": _ip, "ss": _ss, "sysctl": _sysctl,
               "dpkg": _dpkg, "dpkg-query": _dpkg_query, "rpm": _rpm, "apt-cache": _apt_cache, "apt": _apt,
               "sort": _sort, "uniq": _uniq}


def host_command_reads(words, *, globs: bool = False, status: bool = False) -> bool:
    """One simple command, as the words a shell hands it: True when this rule knows it cannot change anything.
    `globs`: the command was written with an unquoted * ? [ — a file name could then arrive as an option, which
    matters only where an option can write (the guarded words). `status`: it was written with `$?`."""
    if not words:
        return False
    head = words[0]
    if status and head not in ("echo", "printf"):
        return False                                     # `$?` is digits — let through only where it is printed
    if head == "printf" and words[1:2] and words[1].startswith("-v"):
        return False                                     # a shell's printf -v assigns a variable
    if any(tuple(words[:k]) in _HOST_READ_WORDS for k in (1, 2, 3)):
        return True
    guard = HOST_GUARDS.get(head)
    return guard is not None and not globs and guard(list(words[1:]))


_TO_NOWHERE = re.compile(r">>?[ \t]*/dev/null(?=$|[\s;&|<>])")     # never bash's `&>` — see _HARMLESS_REDIRECT
_FD_TO_NOWHERE = re.compile(r"(?:[12]>>?[ \t]*/dev/null|2>&1)(?=$|[\s;&|<>])")
_WORD_BREAK = " \t\n;&|"
_NEEDS_A_COMMAND = ("|", "&&", "||")


def _simple_commands(text: str) -> Optional[list]:
    """The simple commands a shell would run for `text`, in order, as [(text, globs, status)] — or None when the
    line holds anything this rule does not read: an expansion or a substitution ($VAR, ${…}, $(…), a backtick — only
    `$?` is let through, and flagged), a redirect to anything but /dev/null, a redirect with no command (zsh runs
    `cat` for one), a subshell, a group or a brace expansion, a background job, a comment, an operator with no
    command beside it, a quote or a backslash left open, a control character. Quoted text is data."""
    if any((ord(c) < 32 and c not in "\n\t") or c == "\x7f" for c in text):
        return None
    out, cur, quote, i, n = [], [], None, 0, len(text)
    flags = {"globs": False, "status": False, "needs": False, "redirect": False}

    def end(separator) -> bool:
        piece = "".join(cur).strip()
        del cur[:]
        redirect_alone = flags["redirect"] and not piece
        flags["redirect"] = False
        if piece:
            out.append((piece, flags["globs"], flags["status"]))
            flags.update(globs=False, status=False, needs=separator in _NEEDS_A_COMMAND)
            return True
        # nothing between two separators: fine before a line break and at the end, unless a command is still owed —
        # and unless a redirect stood there alone
        return not redirect_alone and (separator == "\n" or (separator is None and not flags["needs"]))

    while i < n:
        c = text[i]
        if quote == "'":
            cur.append(c)
            if c == "'":
                quote = None
        elif c == "\\":
            if i + 1 >= n:
                return None                              # the shell would wait for the rest
            if text[i + 1] != "\n":                      # a backslash and a line break: the line goes on
                cur += (c, text[i + 1])
            i += 1
        elif c == "$":
            following = text[i + 1:i + 2]
            if following == "?":
                cur += "$?"
                flags["status"] = True
                i += 1
            elif quote == '"' and following == '"':
                cur.append(c)                            # "…$": a dollar that ends a quoted string is a dollar
            else:
                return None
        elif c == "`":
            return None
        elif quote == '"':
            cur.append(c)
            if c == '"':
                quote = None
        elif c in "'\"":
            quote = c
            cur.append(c)
        elif c in "(){}":
            return None
        elif c == "#" and (i == 0 or text[i - 1] in _WORD_BREAK):
            return None                                  # a comment (a # inside a word is not one)
        else:
            nowhere = _TO_NOWHERE.match(text, i) or (
                (i == 0 or text[i - 1] in _WORD_BREAK) and _FD_TO_NOWHERE.match(text, i))
            if nowhere:
                cur.append(" ")
                flags["redirect"] = True
                i = nowhere.end()
                continue
            if c in "<>":
                return None
            if c == "&":
                if text[i + 1:i + 2] != "&" or not end("&&"):
                    return None
                i += 1
            elif c == "|":                               # `|&` ends here too: its `&` is refused where it stands
                double = text[i + 1:i + 2] == "|"
                if not end("||" if double else "|"):
                    return None
                i += double
            elif c in ";\n":
                if not end(c):
                    return None
            else:
                if c in "*?[":
                    flags["globs"] = True
                cur.append(c)
        i += 1
    if quote or not end(None):
        return None
    return out


def host_reads_only(command: str) -> bool:
    """True when a shell given `command` would run only commands this rule knows cannot change anything (above).
    False for everything else — a line that does change something, and a line the rule cannot read."""
    commands = _simple_commands(command or "")
    if not commands:
        return False
    for text, globs, status in commands:
        try:
            words = shlex.split(text)
        except ValueError:
            return False
        if not host_command_reads(words, globs=globs, status=status):
            return False
    return True


def _runs_more_than_one(text: str) -> bool:
    """True when a shell would run more than one command for `text`: an unquoted ; & | or line break, a subshell,
    or a substitution (a backtick or $( — inside double quotes too). Quoted text is data and `2>&1` / `>/dev/null`
    change nothing; a redirect or a comment alone is still one command. Bash's `&>` counts: to dash it is `&` and
    then the next command (N30)."""
    text = _CONTINUED.sub(" ", _HARMLESS_REDIRECT.sub(" ", text or ""))
    quote, i = None, 0
    while i < len(text):
        c = text[i]
        if quote == "'":
            if c == "'":
                quote = None
        elif c == "\\":
            i += 1                                   # the next character is literal
        elif quote == '"':
            if c == '"':
                quote = None
            elif c == "`" or text.startswith("$(", i):
                return True
        elif c in "'\"":
            quote = c
        elif c in ";&|\n()`" or text.startswith("$(", i):
            return True
        i += 1
    return False


def hides_second_command(command: str) -> bool:
    """A host line that runs more than one command and that the N30 rule does not accept as reads only («之后» 22,
    step 1): outside a read-only run it was judged by how it begins (gap 27) — `cat x && systemctl restart nginx`
    ran as a read. Reads joined by a pipe or `&&` (`ps aux | grep java`) are not this."""
    return _runs_more_than_one(command) and not host_reads_only(command)


def host_line_tier(command: str, tier: str) -> tuple[str, str]:
    """A host line's tier outside a read-only run, and why it was raised: a line read as `readonly` by how it begins
    that hides a second command becomes `unknown`, reason `second_command` — the confirmation, the «needs a change»
    check and a ledger row, as a write gets. Any other tier is left as it is (this never lowers one)."""
    if tier == "readonly" and hides_second_command(command):
        return "unknown", "second_command"
    return tier, ""


def read_only_host_tier(command: str, tier: str) -> str:
    """The tier a host tool takes for `command` while its run may only read, given the run-time classifier's `tier`
    (never called for 'blocked'): 'readonly' only for a line host_reads_only vouches for — a query it knows needs no
    confirmation there —, 'write' stays 'write', and what merely began like a read becomes 'unknown'."""
    if host_reads_only(command):
        return "readonly"
    return "write" if tier == "write" else "unknown"


def command_tier(command: str) -> str:
    """The execution tier ('blocked' | 'write' | 'readonly' | 'unknown') of the tool that would run `command`.

    The tools' classifiers read how the line begins, in lower case. 'readonly' is therefore kept only for a line
    that is ONE command a shell would not split, redirect, substitute into or comment, on one line, written as the
    command is — in its own case: «Free up disk by deleting old logs» and «Kubectl get pods and delete the stuck
    ones» are sentences, not `free` and `kubectl get` — and, on a host, one whose first words cannot write whatever
    follows (HOST_CANNOT_WRITE). Anything else that began like a read is 'unknown'. A write or a blocked command
    stays what it is: the checks only move a step toward «a person looks»."""
    from agenticops.skills.security import classify_kubectl_command, classify_shell_command
    from agenticops.tools.aws_cli_tool import _classify_command

    text = _CONTINUED.sub(r"\1 ", command or "")
    flat = " ".join(text.split())
    written = flat.split(None, 1)[0] if flat else ""
    head = written.lower()
    if head == "aws":
        tier, as_written = _classify_command(flat), written == head
    elif head == "kubectl":
        tier, as_written = classify_kubectl_command(flat), written == head
    else:
        tier = classify_shell_command(flat)
        entry = _host_entry(flat.lower())
        as_written = bool(entry) and flat.startswith(entry)
        if tier == "readonly" and entry not in HOST_CANNOT_WRITE:
            tier = "unknown"
    if tier == "readonly" and (not as_written or len([line for line in text.splitlines() if line.strip()]) > 1
                               or _shell_would_split(text)):
        tier = "unknown"
    # A value the database scrub removed (security/redaction: every text column is scrubbed when it is written):
    # «… --access-key-id [REDACTED-SECRET] …» is what is stored, shown, hashed and handed to the executor, and it
    # does not say which key. The code cannot read that as a command (round-2 review C-I1).
    from agenticops.security.redaction import PLACEHOLDER
    if tier in ("readonly", "write") and PLACEHOLDER in text:
        tier = "unknown"
    return tier


def step_tier(step) -> str:
    """One plan step's tier as a page shows it beside the step: its command's tier, and 'unknown' for a step with
    no command — the executor would decide what to run. The auto-approval floor (unclassified_commands) reads
    this same answer."""
    raw = _raw_command(step)
    return command_tier(raw) if raw.strip() else "unknown"


def step_tiers(steps) -> list[str]:
    """One tier per step of a plan's steps column, in order (MVP-2.9.0: FixPlanResponse.step_tiers)."""
    return [step_tier(s) for s in plan_steps(steps)]


def blocked_commands(*step_lists) -> list[str]:
    """Every command, across the given step lists, that its execution tool refuses outright."""
    seen: list[str] = []
    for steps in step_lists:
        for step in steps or []:
            command = _command(step)
            if command and command not in seen and command_tier(command) == "blocked":
                seen.append(command)
    return seen


def plan_steps(steps) -> list:
    """A plan's steps column as a list (legacy rows hold a JSON string)."""
    from agenticops.services.verification import decode_legacy_json
    return decode_legacy_json(steps, list)


def rollback_steps(rollback_plan) -> list:
    """The steps a rollback plan carries. Its shape is free-form: {"steps": [...]}, {"commands": [...]}, a bare
    list, or prose ({"description": "..."}) — prose carries no step, so it adds nothing."""
    value = rollback_plan
    for _ in range(3):  # legacy rows hold a JSON string, sometimes encoded more than once
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    out: list = []
    for key in ("steps", "commands"):
        if isinstance(value.get(key), list):
            out += value[key]
    return out


def exact_text(command: str) -> str:
    """A command as it is compared word for word (the run guard's rollback allow-list): a backslash-continued line
    joined, spaces and tabs collapsed, blank lines dropped — but a line break KEPT. Two lines are two commands, and
    the same words on one line are another command: «systemctl stop app» / «systemctl start app-old», flattened,
    stops units named `systemctl`, `start` and `app-old` (round-2 review A-M2)."""
    text = _CONTINUED.sub(r"\1 ", command or "")
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def tool_command(tool_name: str, command: str) -> str:
    """The command a tool call would run, as a plan writes it (exact_text). run_kubectl takes the subcommand
    without the word («get pods -n web») where a plan writes «kubectl get pods -n web»: it is judged — its tier,
    its place in the plan, whether it is the plan's rollback — as the command it is (round-2 review A-I2)."""
    text = exact_text(command)
    if tool_name == "run_kubectl" and text and not (text == "kubectl" or text.startswith("kubectl ")):
        text = f"kubectl {text}"
    return text


def check_commands(pre_checks, post_checks) -> frozenset[str]:
    """The commands of a plan's declared pre- and post-checks, each as exact_text (MVP-2.9.0 N27). A run that ran
    nothing but these has not tried the plan — whatever tier the classifier gives them: most real checks
    (`systemctl is-active …`, `curl -s …/health`) are on no read list."""
    return frozenset(c for checks in (pre_checks, post_checks) for c in
                     (exact_text(_raw_command(s)) for s in plan_steps(checks)) if c)


def rollback_commands(rollback_plan) -> frozenset[str]:
    """The commands of a plan's rollback steps, each as exact_text — what a stopped run may still run
    (agents/run_guard, MVP-2.9.0 N9). Prose carries no command and adds nothing."""
    return frozenset(c for c in (exact_text(_raw_command(s)) for s in rollback_steps(rollback_plan)) if c)


# `<AMI_ID>`, `<team-name>`: one name between angle brackets, wherever it stands — inside a quoted argument too,
# where a shell sees nothing to split. A comparison in a --query (`Size < \`100\` && Iops > \`3000\``) is not one.
_PLACEHOLDER = re.compile(r"<[A-Za-z_][A-Za-z0-9_.\-]*>")


def rollback_outlook(rollback_plan) -> dict:
    """What a stop could roll back, as the plan is written (MVP-2.9.0 N10): how many rollback steps there are, how
    many carry a line of text (`commands`), and how many of those are ONE command a tool can run exactly as it is
    written (`as_written`): a line a shell would not split — no chain, pipe, substitution, placeholder (`<AMI_ID>`)
    or comment — AND one the code recognises as a command that may run (its tier is read-only or write). After a
    stop the run's guard lets through only the plan's own rollback text, so a step the executor would have to
    rewrite before running it cannot be rolled back that way.

    The second condition is N14's: a sentence («Start instance and verify status checks») or a label before a
    command («Re-enable key: aws iam update-access-key …») is no command, though a shell would not split it — and a
    command the tools refuse outright cannot run; nor does a line that still holds a placeholder inside a quoted
    argument (`--ip-permissions '…CidrIp=<OWNER_APPROVED_IP>/32…'`). The round-2 review added two more: a line
    whose value the database scrub removed, and an `aws` line holding a character the AWS CLI tools refuse wherever
    it stands (_a_tool_can_run). The numbers measured on a copy of the local database are in
    docs/MVP-2.9.0-RELEASE.md (N10, corrected at N14 and after the review)."""
    steps = rollback_steps(rollback_plan)
    commands = [c for c in (_command(s) for s in steps) if c]
    return {"steps": len(steps), "commands": len(commands), "as_written": sum(1 for c in commands if _a_tool_can_run(c))}


# What the AWS CLI tools refuse wherever it stands in the command — inside a quoted --query too
# (tools/aws_cli_tool.run_aws_cli / run_aws_cli_readonly, providers/aws). tests/test_run_stop.py asks the tool.
AWS_TOOLS_REFUSE = ("|", ";", "&&", "$(", "`", ">", "<")


def _a_tool_can_run(command: str) -> bool:
    """ONE command a tool can run exactly as it is written (rollback_outlook): a shell would not split it, it holds
    no placeholder, the code recognises it as a command that may run (a line whose value was scrubbed is not one:
    command_tier), and — for the AWS CLI — it holds none of the characters those tools refuse anywhere."""
    if _shell_would_split(command) or _PLACEHOLDER.search(command) or command_tier(command) not in ("readonly", "write"):
        return False
    return not (command.split(None, 1)[0] == "aws" and any(token in command for token in AWS_TOOLS_REFUSE))


def unclassified_commands(*step_lists) -> list[str]:
    """Every step, across the given step lists, that no execution tool can classify: its command's tier is
    'unknown', or it has no command, so the executor would decide what to run (2.7.0 E2E observation 3).
    Auto-approval sends a plan holding one to a person. A blocked command is not listed — blocked_commands()
    refuses it outright."""
    seen: list[str] = []
    for steps in step_lists:
        for step in steps or []:
            command = _command(step)
            if command:
                label = command if step_tier(step) == "unknown" else ""
            else:
                action = " ".join(str(step.get("action") or "").split()) if isinstance(step, dict) else ""
                label = f"(no command) {action}".strip()
            if label and label not in seen:
                seen.append(label)
    return seen


# Commands that take a service down (2.7.0 E2E observation 2: «restore failed half-way» was rolled back by
# scaling both Deployments to 0 — the outage the issue was about). Matched on the lowered, space-collapsed
# command; `0(?!\d)` so `--replicas=10` is not a zero.
_ZERO = r"(?:=|\s+)0(?!\d)"
_OUTAGE_PATTERNS = tuple(re.compile(p) for p in (
    rf"\bscale\b.*--replicas{_ZERO}",                                               # kubectl scale … --replicas=0
    r"\bdelete\s+(?:deployments?|deploy|statefulsets?|sts|daemonsets?|ds|services?|svc)(?:[/.\s]|$)",
    rf"\becs\s+update-service\b.*--desired-count{_ZERO}",
    rf"\bautoscaling\s+(?:set-desired-capacity|update-auto-scaling-group)\b.*--(?:desired-capacity|max-size){_ZERO}",
    r"\beks\s+update-nodegroup-config\b.*desiredsize=0(?!\d)",
    r"\bec2\s+stop-instances\b",
    r"\brds\s+stop-db-(?:instance|cluster)\b",
    rf"\blambda\s+put-function-concurrency\b.*--reserved-concurrent-executions{_ZERO}",
    r"^(?:sudo\s+)?systemctl\s+stop\b",
    r"^(?:sudo\s+)?service\s+\S+\s+stop\b",
))


def outage_commands(*step_lists) -> list[str]:
    """Every command, across the given step lists, that takes a service down: a workload scaled to 0 or deleted,
    an instance / database / service stopped. save_fix_plan refuses a fix plan whose ROLLBACK holds one — undoing
    a fix must never recreate the fault (2.7.0 E2E observation 2)."""
    seen: list[str] = []
    for steps in step_lists:
        for step in steps or []:
            command = _command(step)
            if command and command not in seen and any(p.search(command.lower()) for p in _OUTAGE_PATTERNS):
                seen.append(command)
    return seen


def _line_changes(a: list[str], b: list[str]):
    """Two lists of lines, in order → (added [(j, line)], removed [(i, line)], modified [(i, j, old, new)],
    unchanged). A replaced run pairs its lines one-to-one as modified; the rest of it is added / removed.
    Indexes are 0-based."""
    added, removed, modified, unchanged = [], [], [], 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            unchanged += i2 - i1
            continue
        pairs = min(i2 - i1, j2 - j1) if tag == "replace" else 0
        modified += [(i1 + k, j1 + k, a[i1 + k], b[j1 + k]) for k in range(pairs)]
        removed += [(i, a[i]) for i in range(i1 + pairs, i2)]
        added += [(j, b[j]) for j in range(j1 + pairs, j2)]
    return added, removed, modified, unchanged


def diff_steps(proposed, planned) -> dict:
    """What the plan changed relative to the request, by command and in order. A replaced run pairs its steps
    one-to-one as modified; the rest of it is added / removed. Step numbers are 1-based."""
    added, removed, modified, unchanged = _line_changes([_command(s) for s in proposed or []],
                                                        [_command(s) for s in planned or []])
    return {"added": [{"plan_step": j + 1, "command": line} for j, line in added],
            "removed": [{"proposed_step": i + 1, "command": line} for i, line in removed],
            "modified": [{"proposed_step": i + 1, "plan_step": j + 1, "proposed": old, "plan": new}
                         for i, j, old, new in modified],
            "unchanged": unchanged}


def step_line(step) -> str:
    """One step as ONE comparable line — what would run: its command; for a step without one, what it says it does
    (the keys the plan views read: action, description, step); a step written with other keys, as it is (keys
    sorted, so the same step is the same line). Whitespace collapsed."""
    if step is None:
        return ""
    if not isinstance(step, dict):
        return " ".join(str(step).split())
    text = _raw_command(step)
    if not text.strip():
        text = next((v for v in (step.get(k) for k in ("action", "description", "step")) if isinstance(v, str) and v.strip()), "")
    if not text.strip():
        return json.dumps(step, sort_keys=True, ensure_ascii=False, default=str) if step else ""
    return " ".join(text.split())


def plan_diff(previous, current) -> dict:
    """What a plan changed relative to the plan before it (MVP-2.9.0 N14), step by step and in order, by
    `step_line` — so a step without a command is compared by its words (diff_steps compares commands only: there
    two command-less steps are «the same» whatever they say), and reworded text around an unchanged command is
    not a change to what runs. Step numbers are 1-based, each in its own plan."""
    added, removed, modified, unchanged = _line_changes(
        [step_line(s) for s in previous] if isinstance(previous, list) else [],
        [step_line(s) for s in current] if isinstance(current, list) else [])
    return {"added": [{"step": j + 1, "text": line} for j, line in added],
            "removed": [{"previous_step": i + 1, "text": line} for i, line in removed],
            "modified": [{"previous_step": i + 1, "step": j + 1, "previous": old, "now": new} for i, j, old, new in modified],
            "unchanged": unchanged}

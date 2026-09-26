"""Governed-autonomy policy engine — declarative approval rules for fix plans.

Replaces the hardcoded ``risk_level in (L0, L1)`` auto-approve check with
rules loaded from ``config/policies.yaml``. Every decision carries the rule
that produced it and human-readable reasons, and is logged to the pipeline
event timeline — the policy file plus the decision log together form the
auditable "autonomy contract" (SOC 2 CC8.1: every automated change traces
to a pre-authorized rule).

Actions:
    auto_approve        — approve without a human (still creates audit events)
    require_human       — wait for in-app/IM human approval (legacy default)
    require_itsm_change — gate on an external ITSM change request approval
    block               — never execute (e.g., inside a change freeze)
    escalate            — re-evaluate as one risk tier higher

Fail-closed: a missing/invalid policy file falls back to built-in defaults
that replicate the historical behavior exactly; an unmatchable input falls
through to the configured default action (require_human).
"""

from __future__ import annotations

import logging
import re
import shlex
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

RISK_ORDER = ["L0", "L1", "L2", "L3", "L4"]

VALID_ACTIONS = {"auto_approve", "require_human", "require_itsm_change", "block", "escalate"}

# Change Management (MVP-2.6.0): what a rule's `match` may name for `plan_kind` / `action_type`. A fix plan
# evaluates as plan_kind="fix" (the default), so rules carrying `plan_kind: [change]` never touch the fix flow.
PLAN_KINDS = ("fix", "change")
CHANGE_ACTION_TYPES = ("tag", "scale", "config", "network", "iam", "delete", "other")

# Replicates pre-2.0 hardcoded behavior: L0/L1 auto, everything else human.
DEFAULT_POLICY: dict = {
    "version": 1,
    "defaults": {"action": "require_human"},
    "rules": [
        {
            "name": "auto-approve-low-risk",
            "match": {"risk_level": ["L0", "L1"]},
            "action": "auto_approve",
            "itsm_change_type": "standard",
        },
    ],
}


@dataclass
class PolicyDecision:
    """Outcome of a policy evaluation — attached to the audit timeline."""

    action: str
    rule_name: str
    reasons: list[str] = field(default_factory=list)
    itsm_change_type: Optional[str] = None
    effective_risk_level: Optional[str] = None
    escalated_from: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "rule": self.rule_name,
            "reasons": self.reasons,
            "itsm_change_type": self.itsm_change_type,
            "effective_risk_level": self.effective_risk_level,
            "escalated_from": self.escalated_from,
        }


def _bump_risk(risk_level: str) -> str:
    try:
        idx = RISK_ORDER.index(risk_level)
    except ValueError:
        return risk_level
    return RISK_ORDER[min(idx + 1, len(RISK_ORDER) - 1)]


# change_required matching (MVP-2.6.0): ORDERED TOKEN-SUBSEQUENCE match. The command is tokenised (wrappers and every
# `-`/`--` option dropped, option VALUES kept, lower-cased) and a pattern hits when its whitespace-split tokens appear
# in that order — not necessarily adjacent. A BARE pattern word (`delete`, `restart`, `reboot`) must equal the whole
# command token; a HYPHENATED one (`modify-`, `modify-security-group`) matches as a prefix. So `aws --profile p ec2
# modify-security-group-rules`, `kubectl -v 6 delete pod x` and `sudo -n systemctl restart nginx` all hit, while
# `kubectl label pod delete-me`, `systemctl restart-all-the-things`, `kubectl scale deployment/shutdown-handler` and
# `--tags Key=x,Value=reboot-test` do not.
# COMMAND POSITION (fix wave): the first word after the wrappers and the first word of every re-split payload is the
# program; when it contains `/` it is reduced to its basename (`/bin/systemctl` → `systemctl`, `/usr/sbin/reboot` →
# `reboot`). A path ANYWHERE ELSE is left alone (`kubectl apply -f /tmp/delete-me.yaml`, `aws s3 cp
# /tmp/reboot-notes.txt s3://b/` are not refused). The basename is taken BEFORE the wrapper check (follow-up 3), so
# `/usr/bin/sudo -n /usr/bin/systemctl` and `/usr/bin/env -i …` are wrappers like the bare words.
# WRAPPERS (_POLICY_WRAPPERS: sudo, env, nohup, time, nice, setsid, command, exec, doas, stdbuf, unshare, nsenter,
# ionice, busybox) are DROPPED — their word, their options and their `K=V` assignments precede the program — and a
# wrapper word in command position after another wrapper (`sudo -n nice -n 10 /usr/bin/…`, `sudo -E sudo …`) is itself
# a wrapper. CARRIERS (_POLICY_CARRIERS: `timeout [opts] DURATION`, `chroot [opts] DIR`, `runuser [-u USER | USER |
# --]`, `ssh [opts] HOST`, `docker [opts] exec [opts] CONTAINER`) are KEPT with their positionals, and what follows the
# positionals is a NESTED command with a command position of its own (`ssh host sudo /usr/sbin/reboot`, `timeout 30
# /sbin/reboot`, `docker exec -it web /sbin/reboot` all hit `reboot`); what follows kubectl's `--` (`kubectl exec pod
# -- /sbin/reboot`) is the nested case that predates the carriers, and under any other command `--` is just the POSIX
# marker (`ls -- /sbin/reboot` is untouched).
# OPTION REGIONS: between a wrapper/carrier word and its command, ITS OWN table (_OPTION_TABLES) decides how each option
# behaves, consulted before anything generic — the generic boolean list (`--user`, `-f`, `-q`) never applies there. A
# VALUE-TAKING option (`sudo -u root`, `sudo --user root`, `time -f %e`, `nice -n 10`, `ssh -p 2222`) consumes the
# next token, which is then an option value: never the command word, ineligible for hyphenated patterns. A GLUED
# value (`sudo -uroot`, `sudo -nuroot`, `nice -n5`, `time -o/tmp/t`, any `--opt=value`) is self-contained and
# consumes nothing. A BOOLEAN switch — exact (`sudo -n`, `sudo --login`, `env -i`, `time -p`) or an all-boolean
# short CLUSTER (`sudo -En`, `env -i0`, `time -pq`, `docker exec -it`, `ssh -46`) — consumes nothing either. An
# option in neither list is value-taking where the table is complete (sudo, env, time, …: only an invalid option
# gets there) and boolean where the tool's option surface is open-ended (`others_boolean`: ssh, unshare, nsenter).
# A purely NUMERIC token (`nice -n -5`, `nice -5`, the obsolete `nice --5` / `nice -+5`, `10`) is never an option:
# kept, never value-taking, never the command word — unless the region's boolean letters spell it (`env -0`,
# `ssh -46`) — but it does count as a carrier positional (`timeout 30 …`).
# A QUOTED PAYLOAD is any post-shlex token that still contains whitespace (`bash -c "systemctl restart nginx"`,
# `ssh host '…'`, `--parameters commands="systemctl restart nginx"`, `--parameters '{"commands":["…"]}'`) — and so
# is the value of a `--opt=value` that holds whitespace (`env --split-string='/usr/bin/systemctl restart nginx'`,
# `--parameters=commands="…"`); it is re-split the same way (depth-bounded) so its words face the gate like any other
# tokens, with their own command position. `name="cmd …"` contributes only its VALUE part and JSON structure
# (`{}[]:,`) inside a payload separates words. Edge punctuation `[{("'` / `]})"',` is stripped from a token before
# comparison (never from the normalised output).
# OPTION VALUES are not operations: a token consumed by a value-taking option is ineligible for HYPHENATED pattern
# tokens, so `--function-name update-inventory` does not hit `aws lambda update-`; bare pattern words keep no
# adjacency rule (`kubectl --as admin delete pod x`). Tokens produced from an option's VALUE payload keep that flag
# (all ineligible) — EXCEPT a QUOTED `-c`-family payload (`bash -c "…"`, `sh -lc '…'`, `su -c '…'` — after ANY command
# word, `python -c '…'` included: the round-4 deviation, kept because a false refusal beats a lost one), `env -S`/
# `--split-string` and su's/runuser's `--command`, and a positional payload, which are commands in their own right
# and keep their own flags (taking `-c` payloads as ineligible would re-open the hole for every AWS-style pattern).
# A ONE-WORD `-c` value is a command only when the level's command word or carrier IS a shell (_SHELL_COMMANDS):
# `sh -c /sbin/reboot` and `kubectl exec pod -- sh -c '/sbin/reboot'` hit `reboot` (command position, basename), while
# kubectl's `-c side` and ssh's `-c aes` stay plain option values.
# A KNOWN BOOLEAN flag outside any region (_POLICY_BOOLEAN_FLAGS) takes no value, so the token after it stays
# eligible: `aws ec2 --no-cli-pager modify-security-group-rules` is still gated. The allowlists only ever ADD
# refusals (an eligible token is a superset), never remove one; an unknown flag directly before the operation still
# reads as value-taking.
_POLICY_RESPLIT_MAX_DEPTH = 3
# Boolean flags that never consume the next token (exact, case-sensitive: `-a` is not `-A`, `-qy` is not listed).
# AWS CLI globals first, then the systemctl/kubectl/az/apt-style switches an operator puts before the verb.
# GENERIC: consulted only outside a wrapper's option region (inside one, the region's table decides).
_POLICY_BOOLEAN_FLAGS = frozenset({
    "--debug", "--no-cli-pager", "--no-paginate", "--no-verify-ssl", "--no-sign-request",
    "--no-cli-auto-prompt", "--cli-auto-prompt", "--dry-run", "--quiet", "-q", "--yes", "-y", "--force", "-f",
    "--user", "--now", "--all", "-A",
})


@dataclass(frozen=True)
class _OptionTable:
    """How the options of one OPTION REGION behave — a wrapper's (`sudo …`), a carrier's (`ssh … HOST`) or the
    `docker exec … CONTAINER` sub-command's. Consulted before anything generic while the region is open."""

    value: frozenset[str] = frozenset()    # exact options that take the NEXT token as their value: `-u`, `--user`
    value_letters: str = ""                # short letters that take a value — glued (`-uroot`) or as the next token (`-u root`)
    boolean: frozenset[str] = frozenset()  # exact boolean options (the long forms): `--non-interactive`
    bool_letters: str = ""                 # short letters that take no value, alone or clustered: `-n`, `-En`
    others_boolean: bool = False           # an option in neither list: boolean (ssh, unshare, nsenter) or value-taking
    positionals: int = 0                   # carrier positionals kept before the nested command: `timeout DURATION`, `ssh HOST`


def _table(value: str = "", value_letters: str = "", boolean: str = "", bool_letters: str = "", *,
           others_boolean: bool = False, positionals: int = 0) -> _OptionTable:
    return _OptionTable(frozenset(value.split()), value_letters, frozenset(boolean.split()), bool_letters,
                        others_boolean, positionals)


# Wrappers are DROPPED (word, options and K=V assignments precede the program); carriers are KEPT with their positionals
# and hand what follows to a nested command. Both are matched on the BASENAME of the command-position word.
_POLICY_WRAPPERS = ("sudo", "env", "nohup", "time", "nice", "setsid", "command", "exec", "doas", "stdbuf", "unshare",
                    "nsenter", "ionice", "busybox")
_POLICY_CARRIERS = ("timeout", "chroot", "runuser", "ssh", "docker")
# Per region: value-taking options FIRST (sudo's `--user` is a value here although the generic list has it as
# systemctl's boolean), then the booleans; letters drive the short clusters and glued values. `-w` is a value for
# unshare (`--wd dir`, required) but boolean for nsenter (`--wd[=dir]`, optional: as a separate token it takes
# nothing) — the tables follow each tool's own getopt string, not a shared shape.
_OPTION_TABLES: dict[str, _OptionTable] = {
    "sudo": _table(
        value="-u --user -g --group -C --close-from -D --chdir -p --prompt -r --role -t --type -T --command-timeout "
              "-U --other-user -R --chroot -h --host",
        value_letters="ugCDprtTURh",
        # `-l`/`--list` (list permissions) and `-e`/`--edit` (edit a file) are booleans: what follows them is a
        # positional of sudo's own, not an option value, so `sudo -l /sbin/reboot` keeps its command word.
        boolean="--non-interactive --preserve-env --login --set-home --background --reset-timestamp --remove-timestamp "
                "--shell --stdin --validate --askpass --bell --no-update --list --edit",
        bool_letters="nEiHbkKsSvABNPle",
    ),
    "env": _table(
        value="-u --unset -C --chdir -S --split-string -a --argv0", value_letters="uCSa",
        boolean="--ignore-environment --null --debug --default-signal --ignore-signal --block-signal "
                "--list-signal-handling",
        bool_letters="iv0",
    ),
    "time": _table(value="-o --output -f --format", value_letters="of",
                   boolean="--portability --verbose --append --quiet", bool_letters="pvaq"),
    "nice": _table(value="-n --adjustment", value_letters="n"),
    "nohup": _table(),
    "setsid": _table(boolean="--ctty --fork --wait", bool_letters="cfw"),
    "command": _table(bool_letters="pvV"),
    "exec": _table(value="-a", value_letters="a", bool_letters="cl"),
    "doas": _table(value="-u -C", value_letters="uC", bool_letters="Lns"),
    "stdbuf": _table(value="-i -o -e --input --output --error", value_letters="ioe"),
    "ionice": _table(value="-c --class -n --classdata -p --pid -P --pgid -u --uid", value_letters="cnpPu",
                     boolean="--ignore", bool_letters="t"),
    "unshare": _table(
        value="-S --setuid -G --setgid -R --root -w --wd -l --load-interp --map-user --map-users --map-group "
              "--map-groups --propagation --setgroups --monotonic --boottime",
        value_letters="SGRwl", bool_letters="muinpUCTfrc", others_boolean=True,
    ),
    "nsenter": _table(value="-t --target -S --setuid -G --setgid", value_letters="tSG",
                      bool_letters="amuinpUCTrwWeFckZ", others_boolean=True),
    "busybox": _table(),
    "timeout": _table(value="-k --kill-after -s --signal", value_letters="ks",
                      boolean="--preserve-status --foreground --verbose", bool_letters="v", positionals=1),
    "chroot": _table(value="--userspec --groups", boolean="--skip-chdir", positionals=1),
    "runuser": _table(value="-u --user -g --group -G --supp-group -c --command -s --shell -w --whitelist-environment",
                      value_letters="ugGcsw", boolean="--login --preserve-environment --pty --fast",
                      bool_letters="lmpPf", positionals=1),
    "ssh": _table(value="-p -l -i -o -F -J -L -R -D -W -b -c -m -e -E -B -Q -S -w -I -O -P",
                  value_letters="plioFJLRDWbcmeEBQSwIOP", bool_letters="46AaCfGgKkMNnqsTtVvXxYy",
                  others_boolean=True, positionals=1),
    "docker": _table(value="-H --host -l --log-level -c --context --config --tlscacert --tlscert --tlskey",
                     value_letters="Hlc", boolean="--debug --tls --tlsverify", bool_letters="D", positionals=1),
    "docker exec": _table(value="-u --user -w --workdir -e --env --env-file --detach-keys", value_letters="uwe",
                          boolean="--interactive --tty --detach --privileged", bool_letters="itd", positionals=1),
}
# A purely numeric token (`-5`, `+5`, `10`, nice's obsolete `--5` / `-+5`) is never an option: `nice -n -5 …`,
# `nice -5 …` and `nice --5 …` keep the program path.
_NUMERIC_TOKEN = re.compile(r"^-?[+-]?\d+$")
# env-style `NAME=value` assignments precede the program (`env FOO=1 aws …`, `FOO=1 aws …`): never the command word.
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# `name="cmd …"` payload: only the VALUE part is re-split (`commands="systemctl restart nginx"`).
_NAMED_PAYLOAD = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*=(.*)$", re.S)
# A shell's `-c` family (`bash -c`, `sh -lc`, `su -c`, `zsh -ic`): the option VALUE is a command in its own right. A
# QUOTED value counts after any command word (round 4, kept); a ONE-WORD value only when the level's command word (or
# carrier) IS a shell (_SHELL_COMMANDS) — kubectl's `-c side` is a container, ssh's `-c aes` a cipher.
_SHELL_PAYLOAD_FLAG = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")
_SHELL_COMMANDS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "su", "runuser"})
# Other options whose VALUE is a command: `env -S '…'` / `--split-string='…'` runs the split string; `--command` is
# the long form of su's / runuser's `-c`.
_COMMAND_PAYLOAD_FLAGS: dict[str, frozenset[str]] = {
    "env": frozenset({"-S", "--split-string"}), "su": frozenset({"--command"}), "runuser": frozenset({"--command"}),
}
# JSON structure inside a payload separates words: '{"commands":["systemctl restart nginx"]}' → commands, systemctl, …
# (quotes are left to shlex, which removes them as quoting; `,` so that '["reboot","now"]' cannot glue into one word).
_PAYLOAD_JSON_PUNCT = re.compile(r"[{}\[\]:,]")
# Edge punctuation stripped from a token before comparison (never from the normalised output).
_EDGE_LEAD, _EDGE_TRAIL = "[{(\"'", "]})\"',"


def _is_value_taking_option(token: str) -> bool:
    """An option that MAY consume the next token as its value: `-n`, `--profile`; not `-`/`--` (POSIX markers,
    positionals follow them), not `--opt=value` (self-contained) and not a known boolean flag
    (_POLICY_BOOLEAN_FLAGS: `--no-cli-pager`, `--dry-run`, `-q`, …), not a purely numeric token (`-5` is a value,
    _NUMERIC_TOKEN). Whether any OTHER flag really takes a value is CLI-specific, so its next token is treated as
    a value — the direction the lead ruled for hyphenated patterns. This is the GENERIC rule, i.e. the rule outside
    any wrapper's option region; inside one, _option_consumes_next reads the region's table instead."""
    return (token.startswith("-") and token not in ("-", "--") and "=" not in token
            and token not in _POLICY_BOOLEAN_FLAGS and not _NUMERIC_TOKEN.match(token))


def _option_consumes_next(region: Optional[str], token: str) -> bool:
    """True when the option `token` takes the NEXT token as its value — that token is then an option value: never
    the command word, ineligible for hyphenated patterns. Outside a region this is _is_value_taking_option. Inside
    one the region's table decides, value-taking entries first: `sudo -u`/`--user`, `time -f`, `nice -n` consume;
    `sudo -n`, `sudo -En`, `env -i0`, `ssh -46` are boolean; a glued value (`sudo -uroot`, `sudo -nuroot`, `nice -n5`,
    `time -o/tmp/t`) is self-contained; a cluster ENDING in a value letter (`sudo -nu root`) consumes. An option in
    neither list follows the region's default (value-taking, or boolean where `others_boolean`)."""
    if not token.startswith("-") or token in ("-", "--") or "=" in token or _NUMERIC_TOKEN.match(token):
        return False
    table = _OPTION_TABLES.get(region) if region else None
    if table is None:
        return _is_value_taking_option(token)   # no region (or no table for it): the ONE generic rule, stated there
    if token in table.value:
        return True
    if token in table.boolean:
        return False
    if token.startswith("--"):
        return not table.others_boolean                      # an unlisted long option
    letters = token[1:]
    for idx, letter in enumerate(letters):
        if letter in table.value_letters:
            return idx == len(letters) - 1                   # `-u`, `-nu`: the next token is the value; `-uroot`: glued
        if letter not in table.bool_letters:
            return len(letters) == 1 and not table.others_boolean   # unknown letter: the default alone, self-contained in a cluster
    return False                                             # all boolean: `-n`, `-En`, `-it`, `-46`


def _is_numeric_value(region: Optional[str], token: str) -> bool:
    """A purely numeric `-`-token is a VALUE to keep (`nice -5`, `nice --5`, `nice -+5`) unless the region's boolean
    letters spell it (`env -0`, `ssh -46`), in which case it is an option like any other."""
    if not _NUMERIC_TOKEN.match(token):
        return False
    table = _OPTION_TABLES.get(region) if region else None
    letters = token[1:]
    return not (table and letters and all(letter in table.bool_letters for letter in letters))


def _is_command_payload_flag(context: Optional[str], flag: Optional[str], quoted: bool) -> bool:
    """True when `flag` — the option right before a payload — makes that payload a COMMAND of its own. A `-c`-family
    flag (`bash -c`, `sh -lc`, `su -c`, `runuser -c`) does so for a QUOTED payload after any command word (the round-4
    deviation, kept: `python -c 'aws ec2 modify-…'` stays a refusal) and for a ONE-WORD payload only when `context`
    — the level's command word or carrier — is a shell (`sh -c /sbin/reboot`; kubectl's `-c side` and ssh's `-c aes`
    are plain values). `env -S`/`--split-string` and su's/runuser's `--command` do so either way. A positional
    payload never comes through here (it is a command anyway)."""
    if flag is None:
        return False
    if _SHELL_PAYLOAD_FLAG.match(flag):
        return quoted or context in _SHELL_COMMANDS
    return context is not None and flag in _COMMAND_PAYLOAD_FLAGS.get(context, frozenset())


def _normalize_for_policy(command: str, _depth: int = 0) -> list[tuple[str, bool]]:
    """Lower-cased `(token, eligible_for_prefix)` pairs with wrappers and option tokens removed.

    shlex tokens (str.split when the quoting is unbalanced). One LEVEL is one command: a WRAPPER at its head
    (_POLICY_WRAPPERS — sudo/env/nohup/time/nice/setsid/command/exec/doas/stdbuf/unshare/nsenter/ionice/busybox, by
    bare name or by path) is dropped with its options, and its command is a level of its own — so chained wrappers
    (`sudo -n nice -n 10 …`, `sudo -E sudo …`) each bring their own option table; a CARRIER (_POLICY_CARRIERS —
    `timeout DURATION`, `chroot DIR`, `runuser [-u USER | USER | --]`, `ssh [opts] HOST`, `docker [opts] exec [opts]
    CONTAINER`) is kept with its positionals and what follows them is a nested command. Every non-numeric token
    starting with '-' is dropped; inside a wrapper's/carrier's option region ITS table (_OPTION_TABLES) says which
    options consume the next token (`sudo -u root`, `sudo --user root`, `time -f %e`, `nice -n 10`), which are
    boolean (`sudo -n`, `sudo -En`, `env -i0`, `ssh -46`) and which carry a glued value (`sudo -uroot`, `nice -n5`);
    a purely numeric `-5`/`--5`/`-+5` is kept and is never an option. Option VALUES are kept as ordinary tokens — a
    kept value can only add a token the ordered match must skip over — but they are flagged: `eligible_for_prefix`
    is False when the ORIGINAL predecessor consumed the token as its value (_option_consumes_next; outside a region
    the generic _is_value_taking_option, where a known boolean flag such as `--no-cli-pager` is not one), and only
    hyphenated pattern tokens consult the flag.

    The COMMAND POSITION — the first kept token of a level that is neither an option value nor an env-style `K=V`
    assignment nor a number — is reduced to its basename when it contains `/` (`/bin/systemctl` → `systemctl`,
    `/usr/bin/sudo` → `sudo`, which is then the wrapper); paths elsewhere stay as they are (`kubectl apply -f
    /tmp/delete-me.yaml`, `chroot /mnt …`'s DIR).

    A kept token that still contains whitespace was a quoted payload (`bash -c "systemctl restart nginx"`,
    `ssh host "sudo …"`, `--parameters commands="…"`), and so is the value of a `--opt=value` holding whitespace
    (`env --split-string='…'`); see _payload_tokens — it is normalised recursively with the same rules and spliced in
    place, so the words inside face the gate too, with their own command position. A SHELL's `-c` value is a command
    of its own even when it is one word (`sh -c /sbin/reboot`; a quoted `-c` value is one after any command word, as
    before); the wrapper's own `-c`/`-lc` went with the option drop. Recursion is bounded at _POLICY_RESPLIT_MAX_DEPTH (deeper payloads get a flat str.split), and nothing here
    raises on odd input.

    NESTED COMMANDS are tokenised the same way in place: everything after kubectl's `--` (`kubectl exec pod --
    /sbin/reboot`), after a carrier's positionals (`ssh host …`, `timeout 30 …`, `docker exec … CONTAINER …`) and
    after `runuser … --` has its own command position, so `/sbin/reboot` there is `reboot`; under any other command
    `--` is just the POSIX marker (`ls -- /sbin/reboot` is untouched).
    """
    try:
        tokens = shlex.split(command or "")
    except ValueError:
        tokens = (command or "").split()
    return _policy_tokens(tokens, _depth)


def _basename(token: str) -> str:
    base = token.rsplit("/", 1)[-1]
    return base or token


def _policy_tokens(tokens: list[str], depth: int) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    # One LEVEL = one command: [wrapper | carrier | program] [options…] … A wrapper or carrier at the head opens its
    # option REGION (`region`: the _OPTION_TABLES key that decides how options behave); the region ends at the
    # wrapper's command, which is a level of its own (recursion), so chained wrappers (`sudo -n nice -n 10 …`) and a
    # carrier's payload (`ssh host sudo …`) each get a fresh command position. `positionals` counts a carrier's kept
    # positionals still to come (timeout DURATION, ssh HOST, docker's sub-command, docker exec's CONTAINER);
    # `command_word` is this level's program once seen (None inside a region: the program is still ahead).
    region: Optional[str] = None
    positionals = 0
    head_done = False
    command_word: Optional[str] = None
    for i, token in enumerate(tokens):
        prev = tokens[i - 1] if i > 0 else None
        eligible = prev is None or not _option_consumes_next(region, prev)
        if token == "--":
            if command_word == "kubectl" or (region is not None and positionals == 0):
                # `kubectl exec|run|debug … -- COMMAND`, `runuser -u root -- COMMAND`, `sudo -- COMMAND`: the remainder
                # is a NESTED command with its own command position.
                out.extend(_policy_tokens(tokens[i + 1:], depth))
                break
            continue  # POSIX end-of-options marker (`ls -- /sbin/reboot`, `ssh -- host …`): nothing to keep
        if token.startswith("-") and not _is_numeric_value(region, token):
            name, _, value = token.partition("=")
            if any(ch.isspace() for ch in value):
                # `--split-string='/usr/bin/systemctl restart nginx'`, `--parameters=commands="…"`: the value is a payload
                out.extend(_payload_tokens(value, depth, _is_command_payload_flag(region or command_word, name, True)))
            if region == "runuser" and (name == "--user" or (not name.startswith("--") and "u" in name)):
                positionals = 0  # `runuser -u USER COMMAND`: the user is an option value, no positional precedes the command
            continue
        word = token.lower()
        quoted = any(ch.isspace() for ch in token)
        if not eligible:
            # an option's VALUE: never the head, a positional or the command — kept, ineligible for hyphenated patterns;
            # a SHELL's `-c` value (`sh -c "…"`, one-word `sh -c /sbin/reboot`) or `env -S '…'` is a command of its own
            if _is_command_payload_flag(region or command_word, prev, quoted):
                out.extend(_payload_tokens(token, depth, True))
            elif quoted:
                out.extend(_payload_tokens(token, depth, False))  # `--parameters commands="…"`, `-e "A B"`
            else:
                out.append((word, False))
            continue
        if region is not None and positionals > 0:
            # a carrier positional (DURATION, DIR, USER, HOST, sub-command, CONTAINER): kept as it is — a path here is not a program
            positionals -= 1
            if quoted:
                out.extend(_payload_tokens(token, depth, True))
                continue
            out.append((word, True))
            if region == "docker":  # the sub-command: only `exec` carries a command (after its CONTAINER)
                region, positionals = ("docker exec", 1) if word == "exec" else (None, 0)
            continue
        if region is not None or not head_done:
            # a HEAD position: the wrapper's/carrier's command, or this level's own head
            if _ENV_ASSIGNMENT.match(token):
                out.extend(_payload_tokens(token, depth, True) if quoted else [(word, True)])  # `env FOO=1 …`, `FOO=1 aws …`
                continue
            if not quoted and _NUMERIC_TOKEN.match(token):
                out.append((word, True))  # `nice -5 …`, `nice --5 …`: a number precedes the program
                continue
            if region is not None:
                out.extend(_policy_tokens(tokens[i:], depth))  # the wrapper's / carrier's command: a level of its own
                break
            head_done = True
            if quoted:
                out.extend(_payload_tokens(token, depth, True))  # this level IS a quoted payload (`ssh host '…'`)
                continue
            if "/" in word:
                word = _basename(word)  # command position only: /usr/sbin/reboot → reboot, /usr/bin/sudo → sudo
            if word in _POLICY_WRAPPERS:
                region = word  # dropped; its option region follows, the command is still ahead
                continue
            out.append((word, True))
            if word in _POLICY_CARRIERS:
                region, positionals = word, _OPTION_TABLES[word].positionals
            else:
                command_word = word
            continue
        if quoted:
            out.extend(_payload_tokens(token, depth, True))  # a positional payload after the command word (`echo "…"`)
        else:
            out.append((word, True))
    return out


def _payload_tokens(payload: str, depth: int, as_command: bool) -> list[tuple[str, bool]]:
    """Tokens of a quoted payload — a post-shlex token that still contains whitespace, the whitespace-holding value
    of a `--opt=value`, or a shell's one-word `-c` value.

    `name="cmd …"` contributes only its value part; JSON structure (`{}[]:,`) inside the body separates words
    (quotes are left to shlex). The body is normalised recursively (depth-bounded; a flat str.split past the bound),
    so its words face the gate like any other tokens and its first word is a command position (basename applies).
    Eligibility for HYPHENATED patterns: `as_command` — a positional payload (`ssh host '…'`), a `-c`-family value
    (`bash -c '…'`, `su -c '…'`; one-word only for a shell, see _is_command_payload_flag) or `env -S '…'` is a command
    in its own right and keeps its own flags; the value
    of any OTHER option (`--parameters`, `--description`, `--tags`) keeps the option-value flag — every token it yields
    is ineligible (bare pattern words still match, so `--description "reboot test"` stays a deliberate refusal).
    """
    m = _NAMED_PAYLOAD.match(payload)
    body = _PAYLOAD_JSON_PUNCT.sub(" ", m.group(1) if m else payload)
    if depth < _POLICY_RESPLIT_MAX_DEPTH:
        sub = _normalize_for_policy(body, depth + 1)
    else:
        sub = _policy_tokens(body.split(), depth)  # str.split yields no whitespace tokens: no recursion
    return sub if as_command else [(token, False) for token, _ in sub]


def _strip_edges(token: str) -> str:
    stripped = token.lstrip(_EDGE_LEAD).rstrip(_EDGE_TRAIL)
    return stripped or token


def _tokens_match_in_order(pattern_tokens: list[str], command_tokens: list[tuple[str, bool]]) -> bool:
    """True when every pattern token is matched, in order, by a command token.

    A bare pattern word matches only an identical token; a hyphenated pattern token matches as a prefix (the
    hyphen marks the AWS-style `service verb-…` forms) and only against a token that is eligible — i.e. not an
    option value (`--function-name update-inventory` is a resource name, not an operation). Edge punctuation
    (`(reboot)`, `'reboot',`, a quote layer left by a flat split) is stripped before the comparison. Bare-word
    prefixing was a false positive on legitimate L1 writes such as `kubectl label pod delete-me`.
    """
    if not pattern_tokens:
        return False
    i = 0
    for raw, eligible in command_tokens:
        token = _strip_edges(raw)
        wanted = pattern_tokens[i]
        if (eligible and token.startswith(wanted)) if "-" in wanted else token == wanted:
            i += 1
            if i == len(pattern_tokens):
                return True
    return False


def pattern_token_match(command: str, patterns) -> Optional[str]:
    """The first pattern that matches `command` by TOKENS (no raw substring), else None.

    A pattern's non-dash WORDS must appear in order in the normalised command (_tokens_match_in_order:
    bare word = whole token, hyphenated word = prefix, option values ineligible) AND its dash FLAGS must
    each be present among the raw tokens — exactly, or as an argparse ABBREVIATION: a raw token's name (the
    part before `=`) is a >=3-char prefix of the flag, so `--with-decrypt` matches the pattern flag
    `--with-decryption`. A word-only pattern ignores flags; a flag-only pattern ignores word order. This is
    the shared token half of both change_required matching (word-only patterns) and the aws-CLI blocked list
    (which adds a raw-substring pre-pass of its own), so an interleaved global option
    (`aws ec2 --region x terminate-instances`) or an abbreviated flag no longer defeats a match.
    """
    normalized = _normalize_for_policy(command)
    try:
        raw = shlex.split(command or "")
    except ValueError:
        raw = (command or "").split()
    raw_names = [t.split("=", 1)[0].lower() for t in raw]
    for pattern in patterns:
        toks = pattern.lower().split()
        words = [t for t in toks if not t.startswith("-")]
        flags = [t for t in toks if t.startswith("-")]
        if not words and not flags:
            continue
        if words and not _tokens_match_in_order(words, normalized):
            continue
        if not all(any(n == f or (len(n) >= 3 and f.startswith(n)) for n in raw_names) for f in flags):
            continue
        return pattern
    return None


class PolicyEngine:
    """Evaluates fix-plan approval policy rules in declaration order."""

    def __init__(self, policy: dict):
        self.policy = policy or DEFAULT_POLICY
        self.rules = self.policy.get("rules") or []
        defaults = self.policy.get("defaults") or {}
        self.default_action = defaults.get("action", "require_human")
        if self.default_action not in VALID_ACTIONS:
            logger.warning(
                "policy defaults.action %r invalid — using require_human",
                self.default_action,
            )
            self.default_action = "require_human"
        # Change Management (MVP-2.6.0): write commands matching one of these patterns (ordered token
        # match, prefix per token — see _tokens_match_in_order) are refused outside an approved plan.
        # A non-list would iterate characters and match everything, so it is ignored (from_yaml
        # already rejects it via validate_policy).
        raw = self.policy.get("change_required") or []
        if not isinstance(raw, (list, tuple)):
            logger.warning("policy change_required must be a list — ignoring %r", raw)
            raw = []
        self.change_required: list[str] = [str(p).lower() for p in raw if str(p).strip()]

    # ── Loading ──────────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str | Path | None = None) -> "PolicyEngine":
        """Load policies.yaml; fall back to built-in defaults on any error."""
        import yaml

        if path is None:
            from agenticops.config import settings
            path = settings.policy_file
        p = Path(path)
        if not p.is_absolute():
            from agenticops.config import PROJECT_ROOT
            p = PROJECT_ROOT / p
        if not p.exists():
            logger.info("policy file %s not found — using built-in defaults", p)
            return cls(DEFAULT_POLICY)
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
                raise ValueError("policy file must be a mapping with a 'rules' list")
            errors = validate_policy(data)
            if errors:
                raise ValueError("; ".join(errors))
            return cls(data)
        except Exception as e:
            logger.error("Failed to load policy file %s (%s) — using built-in defaults", p, e)
            return cls(DEFAULT_POLICY)

    # ── Evaluation ───────────────────────────────────────────────────

    def evaluate(
        self,
        *,
        risk_level: str,
        severity: Optional[str] = None,
        provider: Optional[str] = None,
        resource_id: Optional[str] = None,
        blast_radius: Optional[int] = None,
        impact_severity: Optional[str] = None,
        now: Optional[datetime] = None,
        plan_kind: str = "fix",
        emergency: bool = False,
        action_type: Optional[str] = None,
    ) -> PolicyDecision:
        """Evaluate rules in order; first match wins. 'escalate' re-runs one tier up.

        `plan_kind` / `action_type` / `emergency` (MVP-2.6.0 change requests) are matched like the other fields;
        an emergency CHANGE never matches `in_change_freeze`, so it crosses a freeze window (other rules still gate
        it). `emergency` is only meaningful for `plan_kind="change"`: a fix plan inside a freeze stays blocked.
        """
        now = now or datetime.now(timezone.utc)
        original_risk = risk_level
        seen_levels: set[str] = set()
        fired_escalations: set[int] = set()  # each escalate rule bumps at most once

        while True:
            seen_levels.add(risk_level)
            for rule_idx, rule in enumerate(self.rules):
                if rule_idx in fired_escalations:
                    continue
                matched, reasons = self._matches(
                    rule.get("match") or {},
                    risk_level=risk_level,
                    severity=severity,
                    provider=provider,
                    resource_id=resource_id,
                    blast_radius=blast_radius,
                    impact_severity=impact_severity,
                    now=now,
                    plan_kind=plan_kind,
                    emergency=emergency,
                    action_type=action_type,
                )
                if not matched:
                    continue
                action = rule.get("action", self.default_action)
                name = rule.get("name", "unnamed")
                if action == "escalate":
                    fired_escalations.add(rule_idx)
                    bumped = _bump_risk(risk_level)
                    if bumped in seen_levels:
                        # Already at top tier (or cycle) — escalate degrades to human gate
                        return PolicyDecision(
                            action="require_human",
                            rule_name=name,
                            reasons=reasons + [f"escalation from {risk_level} capped"],
                            effective_risk_level=risk_level,
                            escalated_from=original_risk if original_risk != risk_level else None,
                        )
                    risk_level = bumped
                    break  # restart rule scan at the higher tier
                return PolicyDecision(
                    action=action if action in VALID_ACTIONS else self.default_action,
                    rule_name=name,
                    reasons=reasons,
                    itsm_change_type=rule.get("itsm_change_type"),
                    effective_risk_level=risk_level,
                    escalated_from=original_risk if original_risk != risk_level else None,
                )
            else:
                # No rule matched at this tier — default action
                return PolicyDecision(
                    action=self.default_action,
                    rule_name="(default)",
                    reasons=[f"no rule matched risk_level={risk_level}"],
                    effective_risk_level=risk_level,
                    escalated_from=original_risk if original_risk != risk_level else None,
                )

    def _matches(
        self,
        match: dict,
        *,
        risk_level: str,
        severity: Optional[str],
        provider: Optional[str],
        resource_id: Optional[str],
        blast_radius: Optional[int],
        impact_severity: Optional[str] = None,
        now: datetime,
        plan_kind: str = "fix",
        emergency: bool = False,
        action_type: Optional[str] = None,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []

        levels = match.get("risk_level")
        if levels is not None:
            if risk_level not in levels:
                return False, []
            reasons.append(f"risk_level={risk_level}")

        severities = match.get("severity")
        if severities is not None:
            if severity not in severities:
                return False, []
            reasons.append(f"severity={severity}")

        providers = match.get("provider")
        if providers is not None:
            if provider not in providers:
                return False, []
            reasons.append(f"provider={provider}")

        pattern = match.get("resource_pattern")
        if pattern is not None:
            if not resource_id or not re.search(pattern, resource_id):
                return False, []
            reasons.append(f"resource matches {pattern!r}")

        br_gte = match.get("blast_radius_gte")
        if br_gte is not None:
            if blast_radius is None or blast_radius < br_gte:
                return False, []
            reasons.append(f"blast_radius={blast_radius} >= {br_gte}")

        impact_severities = match.get("impact_severity")
        if impact_severities is not None:
            if impact_severity not in impact_severities:
                return False, []
            reasons.append(f"simulated impact_severity={impact_severity}")

        kinds = match.get("plan_kind")
        if kinds is not None:
            if plan_kind not in kinds:
                return False, []
            reasons.append(f"plan_kind={plan_kind}")

        action_types = match.get("action_type")
        if action_types is not None:
            if action_type not in action_types:
                return False, []
            reasons.append(f"action_type={action_type}")

        want_emergency = match.get("emergency")
        if want_emergency is not None:
            if bool(want_emergency) != bool(emergency):
                return False, []
            reasons.append(f"emergency={bool(emergency)}")

        if match.get("in_change_freeze"):
            if emergency and plan_kind == "change":
                return False, []  # `emergency` is only meaningful for change plans: they cross the freeze (still human-gated)
            window = self._active_freeze_window(now)
            if window is None:
                return False, []
            reasons.append(f"inside change freeze '{window}'")

        if not match:
            reasons.append("match-all rule")

        return True, reasons

    def _active_freeze_window(self, now: datetime) -> Optional[str]:
        """Return the name of the freeze window containing `now`, if any."""
        for window in self.policy.get("freeze_windows") or []:
            try:
                start = datetime.fromisoformat(str(window["start"]).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(window["end"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                logger.warning("Skipping malformed freeze window: %r", window)
                continue
            if start <= now <= end:
                return window.get("name", f"{start.isoformat()}..{end.isoformat()}")
        return None

    def change_required_match(self, command: str) -> Optional[str]:
        """Return the change_required pattern the command matches, or None.

        Ordered token-subsequence match: the pattern's whitespace-split tokens must appear in order (not
        necessarily adjacent) in _normalize_for_policy(command); a bare pattern word must equal the command
        token, a hyphenated one matches as a prefix (_tokens_match_in_order). There is no raw-substring
        fallback — a pattern word inside a token (`deployment/shutdown-handler`, `Value=reboot-test`,
        `delete-me`) is not a match. Quoted payloads are re-split first, so `bash -c "systemctl restart nginx"`
        and `ssh host "sudo systemctl restart nginx"` match `systemctl restart` (and so does a pattern word
        inside quoted prose — a deliberate false refusal, tunable in the yaml, never a false pass). A hyphenated
        pattern token never matches an option VALUE: `aws lambda invoke --function-name update-inventory` is None.

        Delegates to the module-level pattern_token_match (the shared token half): every change_required pattern
        is word-only, so the flag machinery is inert here and the behaviour is exactly the ordered-subsequence
        match documented above.
        """
        return pattern_token_match(command, self.change_required)


def validate_policy(data: dict) -> list[str]:
    """Static validation of a policy document. Returns a list of error strings."""
    errors: list[str] = []
    for i, rule in enumerate(data.get("rules") or []):
        label = rule.get("name") or f"rules[{i}]"
        action = rule.get("action")
        if action not in VALID_ACTIONS:
            errors.append(f"{label}: invalid action {action!r}")
        match = rule.get("match")
        if match is not None and not isinstance(match, dict):
            errors.append(f"{label}: 'match' must be a mapping")
        pattern = (match or {}).get("resource_pattern")
        if pattern:
            try:
                re.compile(pattern)
            except re.error as e:
                errors.append(f"{label}: bad resource_pattern: {e}")
        m = match or {}
        if "plan_kind" in m and (not isinstance(m["plan_kind"], list) or any(k not in PLAN_KINDS for k in m["plan_kind"])):
            errors.append(f"{label}: plan_kind must be a list from {list(PLAN_KINDS)}")
        if "action_type" in m and (not isinstance(m["action_type"], list) or any(a not in CHANGE_ACTION_TYPES for a in m["action_type"])):
            errors.append(f"{label}: action_type must be a list from {list(CHANGE_ACTION_TYPES)}")
        if "emergency" in m and not isinstance(m["emergency"], bool):
            errors.append(f"{label}: emergency must be true/false")
    defaults = data.get("defaults") or {}
    if defaults.get("action") and defaults["action"] not in VALID_ACTIONS:
        errors.append(f"defaults.action invalid: {defaults['action']!r}")
    cr = data.get("change_required")
    if cr is not None and not isinstance(cr, list):
        errors.append("'change_required' must be a list of strings")
    return errors


# ── Singleton accessor (reloadable) ─────────────────────────────────

_engine: Optional[PolicyEngine] = None
_engine_lock = threading.Lock()


def get_policy_engine(reload: bool = False) -> PolicyEngine:
    global _engine
    with _engine_lock:
        if _engine is None or reload:
            _engine = PolicyEngine.from_yaml()
        return _engine


# ── Blast-radius helper (graph engine, fail-soft) ───────────────────


def _find_graph_node(resource_id: str, account_id: Optional[str] = None) -> Optional[str]:
    """Find the graph node ID for a resource, optionally scoped to one account.

    Account scoping prevents cross-account resource-ID collisions from feeding
    the wrong topology into policy decisions (graph_nodes.account_id stores the
    cloud-native account number, e.g. the AWS 12-digit ID).
    """
    from agenticops.graph.store import GraphStore

    hits = GraphStore().search_nodes(query=resource_id, limit=10)
    if account_id:
        hits = [h for h in hits if not h.get("account_id") or h["account_id"] == account_id]
    if not hits:
        return None
    # Prefer exact ID match over substring match
    for h in hits:
        if h["id"] == resource_id:
            return h["id"]
    return hits[0]["id"]


def estimate_blast_radius(
    resource_id: Optional[str], account_id: Optional[str] = None
) -> Optional[int]:
    """Count downstream-affected nodes for a resource via the infra graph.

    Returns None when the graph is unavailable or the resource isn't in it —
    policy rules using blast_radius_gte simply don't match in that case.
    """
    if not resource_id:
        return None
    try:
        from agenticops.graph.store import GraphStore
        from agenticops.graph.algorithms import impact_analysis

        node_id = _find_graph_node(resource_id, account_id)
        if not node_id:
            return None
        neighborhood = GraphStore().get_node_neighborhood(node_id, depth=3)
        result = impact_analysis(neighborhood, node_id)
        return len(result.affected_nodes)
    except Exception:
        logger.debug("blast-radius estimation unavailable for %s", resource_id, exc_info=True)
        return None


def simulate_fix_impact(
    resource_id: Optional[str], account_id: Optional[str] = None
) -> Optional[dict]:
    """Pre-execution simulation: what breaks if this resource is disrupted?

    Runs impact_analysis on the persisted graph (zero AWS calls) and returns
    {severity, affected_nodes, isolated_subnets, lost_connections} or None
    when the graph is unavailable — policy rules using impact_severity simply
    don't match in that case (fail-soft, behavior identical to no simulation).
    """
    if not resource_id:
        return None
    try:
        from agenticops.graph.store import GraphStore
        from agenticops.graph.algorithms import impact_analysis

        node_id = _find_graph_node(resource_id, account_id)
        if not node_id:
            return None
        neighborhood = GraphStore().get_node_neighborhood(node_id, depth=3)
        result = impact_analysis(neighborhood, node_id)
        return {
            "severity": result.severity,
            "affected_nodes": len(result.affected_nodes),
            "isolated_subnets": len(result.isolated_subnets),
            "lost_connections": len(result.lost_connections),
        }
    except Exception:
        logger.debug("fix-impact simulation unavailable for %s", resource_id, exc_info=True)
        return None

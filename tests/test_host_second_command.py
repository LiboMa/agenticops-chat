"""A host line that begins like a read but hides a second command is a write («之后» 22, step 1, 2026-11-26).

Outside a read-only run a host line was judged by how it begins (gap 27): `cat x && systemctl restart nginx` ran with
no confirmation and left no ledger row. Step 1 (owner): such a line — more than one command, not all of them reads
the N30 rule knows — gets what a write gets: the confirmation round trip, the «needs a change» check, a ledger row,
with its own reason `second_command`, so the ledger can be counted before anything stricter. A single command
keeps its behaviour. And the SSH account tool `run_ssh_<account>`, which had no confirmation at all, asks for one
for every write / unknown line, as `run_on_host` does (owner)."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from agenticops.run_context import run_context
from tests.test_read_only_runs import _rows, ledger  # noqa: F401  (the fixture)

HIDES = ["cat x && systemctl restart nginx", "ls; rm -rf /tmp/x", "echo $(rm x)", "echo `id`",
         "a &>/dev/null b", "cat /etc/hosts | xargs rm", "df -h\nkill -9 1", "uptime & curl http://x",
         "(cd /tmp && rm y)", 'echo "$(touch /tmp/z)"']
ONE = ["ps aux | grep java", "grep 'a;b' f", "ls 2>&1", "cat x > /tmp/y", "rm x", "df -h", "ls -la /var/log",
       "cat /etc/hosts && echo done", "echo 'a $(b) `c`'", "ls >/dev/null 2>&1", "tail -n 50 /var/log/syslog # why"]


@pytest.mark.parametrize("command", HIDES)
def test_a_hidden_second_command(command):
    from agenticops.services.change_steps import hides_second_command
    assert hides_second_command(command) is True


@pytest.mark.parametrize("command", ONE)
def test_one_command_or_only_reads(command):
    from agenticops.services.change_steps import hides_second_command
    assert hides_second_command(command) is False


@pytest.mark.parametrize("command,tier", [("cat x && systemctl restart nginx", "readonly"), ("rm x", "write"),
                                          ("systemctl status x", "unknown"), ("ps aux | grep java", "readonly")])
def test_the_lift_only_ever_raises_a_read(command, tier):
    from agenticops.services.change_steps import host_line_tier
    lifted, reason = host_line_tier(command, tier)
    if tier == "readonly" and command.startswith("cat"):
        assert (lifted, reason) == ("unknown", "second_command")
    else:
        assert (lifted, reason) == (tier, "")


def _host(command, **kw):
    from agenticops.skills.execution import run_on_host
    return run_on_host(host_id="i-0123456789abcdef0", command=command, **kw)


def test_run_on_host_asks_first_and_records_the_line(ledger):
    with patch("agenticops.skills.execution._run_auto_ladder", return_value="out") as ladder:
        asked = _host("cat /etc/hosts && touch /tmp/marker")
        assert "requires confirmation" in asked and "second command" in asked and not ladder.called
        assert _host("cat /etc/hosts && touch /tmp/marker", require_confirmation=True) == "out"
        assert _host("cat /etc/hosts | grep localhost") == "out"          # reads only: as before, no row
    assert ladder.call_count == 2
    assert _rows(ledger) == [("run_on_host", "unknown", "refused", "second_command"),
                             ("run_on_host", "unknown", "executed", "second_command")]


def test_a_hidden_change_still_needs_its_approved_plan(ledger):
    with patch("agenticops.skills.execution._run_auto_ladder") as ladder:
        out = _host("cat /etc/hosts && systemctl restart nginx", require_confirmation=True)
    assert "approved plan" in out and not ladder.called
    assert _rows(ledger) == [("run_on_host", "unknown", "refused", "change_required")]


def test_a_single_read_keeps_its_behaviour(ledger):
    with patch("agenticops.skills.execution._run_auto_ladder", return_value="out"):
        assert _host("cat /etc/hosts") == "out"
        assert _host("cat x > /tmp/y") == "out"                              # one command: step 1 leaves it
    assert _rows(ledger) == []


# ── the SSH account tool ─────────────────────────────────────────────────────

def _ssh_tool(monkeypatch):
    from agenticops.providers.ssh import SSHProvider
    creds = {"host": "10.0.0.5", "username": "ops"}
    provider = SSHProvider(SimpleNamespace(id=1, name="idc-1", provider="ssh", credentials=creds, regions=[], labels={}))
    provider._cfg = dict(creds)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="out\n", stderr=""))
    monkeypatch.setattr("agenticops.providers.ssh.subprocess.run", run)
    return provider.cli_tool(), run


def test_the_ssh_tool_asks_for_confirmation_of_a_write(ledger, monkeypatch):
    tool, run = _ssh_tool(monkeypatch)
    asked = tool("touch /tmp/marker")
    assert "requires confirmation" in asked and "require_confirmation=True" in asked and not run.called
    assert tool("touch /tmp/marker", require_confirmation=True) == "out\n" and run.call_count == 1
    assert tool("df -h") == "out\n" and run.call_count == 2                  # a read: as before
    assert _rows(ledger) == [("provider_ssh", "write", "refused", "confirmation"),
                             ("provider_ssh", "write", "executed", None)]


def test_the_ssh_tool_lifts_a_hidden_second_command_too(ledger, monkeypatch):
    tool, run = _ssh_tool(monkeypatch)
    assert "second command" in tool("cat /etc/hosts && touch /tmp/marker") and not run.called
    assert tool("cat /etc/hosts && touch /tmp/marker", require_confirmation=True) == "out\n"
    assert _rows(ledger) == [("provider_ssh", "unknown", "refused", "second_command"),
                             ("provider_ssh", "unknown", "executed", "second_command")]


def test_the_ssh_tool_in_a_read_only_run_keeps_its_rule(ledger, monkeypatch):
    tool, run = _ssh_tool(monkeypatch)
    with run_context(read_only_run="diagnosis"):
        out = tool("touch /tmp/marker", require_confirmation=True)
    assert "only reads" in out and not run.called
    assert _rows(ledger) == [("provider_ssh", "write", "refused", "read_only_run")]


def test_the_executor_is_told_its_plan_is_the_confirmation_for_the_account_bound_shell_tool_too():
    import importlib
    src = open(importlib.import_module("agenticops.agents.executor_agent").__file__).read()
    assert "account-bound shell tool" in src


# ── at random ────────────────────────────────────────────────────────────────

def test_at_random_the_lift_never_lowers_a_tier_and_leaves_one_command_alone():
    import random
    from agenticops.services.change_steps import _runs_more_than_one, host_line_tier
    from tests.test_host_reads_only import _FUZZ_READ, _FUZZ_SHARP, _FUZZ_WORDS
    rng = random.Random(20261126)
    for _ in range(5000):
        line = "".join(rng.choice(_FUZZ_WORDS if p < 0.45 else _FUZZ_READ if p < 0.9 else _FUZZ_SHARP)
                       for p in (rng.random() for _ in range(rng.randint(1, 12))))
        for tier in ("readonly", "write", "unknown"):
            lifted, reason = host_line_tier(line, tier)
            assert lifted in (tier, "unknown") and (lifted == tier or tier == "readonly"), line
            if not _runs_more_than_one(line):
                assert (lifted, reason) == (tier, ""), line


def test_what_the_n30_rule_lets_through_is_never_lifted():
    from agenticops.services.change_steps import hides_second_command
    from tests.test_host_reads_only import _fuzz_lines
    kept, _made = _fuzz_lines(20261126, 300)
    assert kept and not [line for line in kept if hides_second_command(line)]

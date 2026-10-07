"""A run bound to one account (a bound chat turn, a change run) never builds a provider — and so never gets a CLI tool
or credentials — for any other account, whichever path builds it: the resolver, get_all_cli_tools (sre_query, the
scan agent), get_cli_tool_for_issue (RCA / SRE / executor), the scanner engine. And the binding crosses the
thread + new event loop that the parallel health check runs in (MVP-2.7.0 S5 review C1)."""
import asyncio
from types import SimpleNamespace

import pytest

from agenticops.run_context import RunContext, reset_run_context, set_run_context


@pytest.fixture
def bound():
    def _bind(account_id):
        return set_run_context(RunContext(actor="user:t", bound_account_id=account_id))
    tokens = []
    yield lambda a: tokens.append(_bind(a))
    for t in reversed(tokens):
        reset_run_context(t)


def _acct(i, provider="aws"):
    return SimpleNamespace(id=i, name=f"a{i}", provider=provider, credentials={}, regions=[], labels={})


def test_get_provider_refuses_another_account_in_a_bound_run(bound):
    from agenticops.credentials.resolver import AccountResolutionError
    from agenticops.providers.base import get_provider
    bound(1)
    assert get_provider(_acct(1)) is not None
    with pytest.raises(AccountResolutionError):
        get_provider(_acct(2))


def test_unbound_runs_are_unchanged():
    from agenticops.providers.base import get_provider
    assert get_provider(_acct(2)) is not None


@pytest.fixture
def two_accounts(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.models import Base, CloudAccount, get_session
    from agenticops.providers.aws import AWSProvider
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/bind.db")
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([CloudAccount(id=1, name="prod", provider="aws", is_enabled=True, credentials={}),
               CloudAccount(id=2, name="lab", provider="aws", is_enabled=True, credentials={})])
    s.commit(); s.close()
    monkeypatch.setattr(AWSProvider, "resolve_credentials", lambda self: True)
    monkeypatch.setattr(AWSProvider, "cli_tool", lambda self: f"cli:{self.account.id}")


def test_get_all_cli_tools_gives_only_the_bound_account(two_accounts, bound):
    from agenticops.providers.base import get_all_cli_tools
    assert sorted(get_all_cli_tools()) == ["cli:1", "cli:2"]   # unbound: every enabled account
    bound(2)
    assert get_all_cli_tools() == ["cli:2"]


def test_get_cli_tool_for_issue_refuses_another_account(two_accounts, bound):
    from agenticops.credentials.resolver import AccountResolutionError
    from agenticops.providers.base import get_cli_tool_for_issue
    bound(1)
    assert get_cli_tool_for_issue(1) == "cli:1"
    with pytest.raises(AccountResolutionError):
        get_cli_tool_for_issue(2)


def test_scanner_engine_skips_another_account(two_accounts, bound):
    from agenticops.scanner.engine import _get_provider_and_tool
    bound(1)
    assert _get_provider_and_tool(_acct(2)) is None
    assert _get_provider_and_tool(_acct(1))[1] == "cli:1"


def test_parallel_health_check_keeps_the_binding_across_its_thread(monkeypatch, bound):
    """check_health runs check_accounts_parallel in a worker thread with asyncio.run: the run context must go too."""
    import agenticops.checker as checker
    import importlib
    scan_agent = importlib.import_module("agenticops.agents.scan_agent")  # the package exports a tool of that name
    from agenticops.run_context import get_run_context
    seen = {}

    async def _fake(account_ids=None, scope="all", deep=False):
        seen["bound"] = get_run_context().bound_account_id
        return SimpleNamespace(duration_s=0, total_issues=0, total_input_tokens=0, total_output_tokens=0,
                               total_cache_read_tokens=0, total_cache_write_tokens=0, accounts=[])
    monkeypatch.setattr(checker, "check_accounts_parallel", _fake)
    bound(2)

    async def _inside_a_loop():
        return scan_agent.check_health(account_ids="", scope="all", deep="false")
    asyncio.run(_inside_a_loop())
    assert seen["bound"] == 2

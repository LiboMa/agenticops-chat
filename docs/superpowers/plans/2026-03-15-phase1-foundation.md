# Phase 1: Foundation — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Connector framework, Service Model, Prompt Optimization Engine v1, and Evidence-weighted confidence system — the foundation for agent-first RCA.

**Architecture:** Connectors provide credential-based read-only access to external systems (Datadog, Prometheus, etc.) while wrapping existing AWS/K8s tools. Prompt Optimization Engine classifies alerts, retrieves relevant strategies and past cases, and assembles token-budgeted system prompts. Evidence system tracks data source weights for confidence scoring.

**Tech Stack:** Python 3.12, Strands Agent SDK, SQLAlchemy, FastAPI, AWS Bedrock (Titan V2 embeddings), httpx (async HTTP), tiktoken (token counting)

**Spec:** `docs/superpowers/specs/2026-03-15-next-gen-aiops-design.md` (Sections 3, 5, 6, 9, 11)

---

## File Structure

### New Files

```
src/agenticops/connectors/
  __init__.py                   - Package exports
  base.py                       - ConnectorBase ABC, ConnectorConfig dataclass, ConnectorError
  registry.py                   - Load connectors.yaml, instantiate connectors, manage lifecycle
  aws.py                        - AWS connector (wraps existing assume_role + aws_cli_readonly)
  kubernetes.py                 - K8s connector (wraps existing run_kubectl)
  datadog.py                    - Datadog API connector (metrics, logs, events)
  prometheus.py                 - Prometheus PromQL connector (metrics, alerts)

src/agenticops/prompt_engine/
  __init__.py                   - Package exports
  classifier.py                 - Alert classification (LLM + embedding similarity)
  strategy.py                   - Strategy selector (Wisdom Roadmap lookup from KB)
  retriever.py                  - Few-shot case retriever (KB vector search)
  assembler.py                  - Token-budgeted system prompt composition
  evidence.py                   - EvidenceItem model, source weights, confidence calculation

config/
  connectors.yaml.example       - Example connector configuration

tests/
  test_connector_base.py        - Connector base + registry tests
  test_connector_aws.py         - AWS connector tests
  test_connector_datadog.py     - Datadog connector tests
  test_connector_prometheus.py  - Prometheus connector tests
  test_service_model.py         - Service model DB + CRUD tests
  test_alert_classifier.py      - Alert classification tests
  test_prompt_assembler.py      - Prompt assembly + token budget tests
  test_evidence.py              - Evidence weighting + confidence tests
```

### Modified Files

```
src/agenticops/models.py              - Add Service, ServiceResource, ServiceDependency, EvidenceItem tables
src/agenticops/config.py              - Add connectors_config path setting
src/agenticops/tools/metadata_tools.py - Add service CRUD + evidence tools
src/agenticops/tools/connector_tools.py - New: agent-facing connector query tools
src/agenticops/agents/rca_agent.py    - Integrate prompt engine + evidence collection
src/agenticops/agents/preamble.py     - Dynamic system prompt composition with token budget
src/agenticops/web/app.py             - Add connector + service API endpoints
```

---

## Chunk 1: Connector Framework

### Task 1: Connector Base Class + Config

**Files:**
- Create: `src/agenticops/connectors/__init__.py`
- Create: `src/agenticops/connectors/base.py`
- Test: `tests/test_connector_base.py`

- [ ] **Step 1: Write failing test for ConnectorBase**

```python
# tests/test_connector_base.py
import pytest
from agenticops.connectors.base import ConnectorBase, ConnectorConfig, ConnectorError


def test_connector_config_from_dict():
    cfg = ConnectorConfig(
        name="datadog",
        connector_type="datadog",
        credentials={"api_key": "test-key", "app_key": "test-app"},
        endpoints={"site": "datadoghq.com"},
        rate_limit=30,
    )
    assert cfg.name == "datadog"
    assert cfg.rate_limit == 30
    assert cfg.read_only is True  # default


def test_connector_base_is_abstract():
    with pytest.raises(TypeError):
        ConnectorBase(ConnectorConfig(name="x", connector_type="x"))


class DummyConnector(ConnectorBase):
    async def query(self, operation: str, params: dict) -> dict:
        return {"result": operation}

    async def test_connection(self) -> bool:
        return True

    def supported_operations(self) -> list[str]:
        return ["test_op"]


def test_dummy_connector_query():
    import asyncio
    cfg = ConnectorConfig(name="dummy", connector_type="dummy")
    conn = DummyConnector(cfg)
    result = asyncio.run(conn.query("test_op", {}))
    assert result == {"result": "test_op"}


def test_connector_rejects_unsupported_operation():
    import asyncio
    cfg = ConnectorConfig(name="dummy", connector_type="dummy")
    conn = DummyConnector(cfg)
    with pytest.raises(ConnectorError, match="unsupported"):
        asyncio.run(conn.validate_operation("unknown_op"))
```

- [ ] **Step 2: Run test — expect FAIL (module not found)**

Run: `python -m pytest tests/test_connector_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agenticops.connectors'`

- [ ] **Step 3: Implement ConnectorBase**

```python
# src/agenticops/connectors/__init__.py
from .base import ConnectorBase, ConnectorConfig, ConnectorError

# src/agenticops/connectors/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ConnectorError(Exception):
    """Raised when a connector operation fails."""


@dataclass
class ConnectorConfig:
    name: str
    connector_type: str
    credentials: dict = field(default_factory=dict)
    endpoints: dict = field(default_factory=dict)
    rate_limit: int = 0  # requests/min, 0 = unlimited
    read_only: bool = True


class ConnectorBase(ABC):
    def __init__(self, config: ConnectorConfig):
        self.config = config
        self.name = config.name

    @abstractmethod
    async def query(self, operation: str, params: dict) -> dict:
        """Execute a read-only query. Returns structured result."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test connectivity. Returns True if reachable."""

    @abstractmethod
    def supported_operations(self) -> list[str]:
        """List supported operation names."""

    def validate_operation(self, operation: str) -> None:
        if operation not in self.supported_operations():
            raise ConnectorError(
                f"unsupported operation '{operation}' for connector '{self.name}'. "
                f"Supported: {self.supported_operations()}"
            )
```

- [ ] **Step 4: Run test — expect PASS**

Run: `python -m pytest tests/test_connector_base.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/connectors/__init__.py src/agenticops/connectors/base.py tests/test_connector_base.py
git commit -m "feat(connectors): add ConnectorBase ABC and ConnectorConfig"
```

---

### Task 2: Connector Registry + YAML Config Loading

**Files:**
- Create: `src/agenticops/connectors/registry.py`
- Create: `config/connectors.yaml.example`
- Modify: `src/agenticops/config.py` (~line 85, add `connectors_config` field)
- Test: `tests/test_connector_base.py` (extend)

- [ ] **Step 1: Write failing test for registry**

```python
# append to tests/test_connector_base.py
import tempfile, yaml
from agenticops.connectors.registry import ConnectorRegistry


def test_registry_load_from_yaml(tmp_path):
    config_file = tmp_path / "connectors.yaml"
    config_file.write_text(yaml.dump({
        "connectors": {
            "dummy": {
                "type": "dummy",
                "credentials": {"key": "val"},
                "rate_limit": 10,
            }
        }
    }))
    registry = ConnectorRegistry()
    configs = registry.load_config(str(config_file))
    assert "dummy" in configs
    assert configs["dummy"].rate_limit == 10


def test_registry_get_connector_not_found():
    registry = ConnectorRegistry()
    with pytest.raises(ConnectorError, match="not configured"):
        registry.get("nonexistent")


def test_registry_list_connectors(tmp_path):
    config_file = tmp_path / "connectors.yaml"
    config_file.write_text(yaml.dump({
        "connectors": {
            "aws": {"type": "aws", "credentials": {"role_arn": "arn:aws:iam::123:role/test"}},
            "datadog": {"type": "datadog", "credentials": {"api_key": "k"}},
        }
    }))
    registry = ConnectorRegistry()
    registry.load_config(str(config_file))
    names = registry.list_names()
    assert set(names) == {"aws", "datadog"}
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `python -m pytest tests/test_connector_base.py::test_registry_load_from_yaml -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ConnectorRegistry**

```python
# src/agenticops/connectors/registry.py
from __future__ import annotations
import yaml
from pathlib import Path
from .base import ConnectorBase, ConnectorConfig, ConnectorError


class ConnectorRegistry:
    def __init__(self):
        self._configs: dict[str, ConnectorConfig] = {}
        self._instances: dict[str, ConnectorBase] = {}

    def load_config(self, config_path: str) -> dict[str, ConnectorConfig]:
        path = Path(config_path)
        if not path.exists():
            return self._configs
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        for name, spec in raw.get("connectors", {}).items():
            self._configs[name] = ConnectorConfig(
                name=name,
                connector_type=spec.get("type", name),
                credentials=spec.get("credentials", {}),
                endpoints=spec.get("endpoints", {}),
                rate_limit=spec.get("rate_limit", 0),
                read_only=spec.get("read_only", True),
            )
        return self._configs

    def get(self, name: str) -> ConnectorBase:
        if name not in self._instances:
            if name not in self._configs:
                raise ConnectorError(f"Connector '{name}' not configured")
            self._instances[name] = self._create(self._configs[name])
        return self._instances[name]

    def list_names(self) -> list[str]:
        return list(self._configs.keys())

    def list_configs(self) -> list[ConnectorConfig]:
        return list(self._configs.values())

    def _create(self, config: ConnectorConfig) -> ConnectorBase:
        from .aws import AWSConnector
        from .kubernetes import KubernetesConnector
        from .datadog import DatadogConnector
        from .prometheus import PrometheusConnector

        factory = {
            "aws": AWSConnector,
            "kubernetes": KubernetesConnector,
            "datadog": DatadogConnector,
            "prometheus": PrometheusConnector,
        }
        cls = factory.get(config.connector_type)
        if cls is None:
            raise ConnectorError(f"Unknown connector type: {config.connector_type}")
        return cls(config)
```

- [ ] **Step 4: Create connectors.yaml.example**

```yaml
# config/connectors.yaml.example
# Copy to config/connectors.yaml and fill in credentials.
# This file is gitignored.
connectors:
  aws:
    type: aws
    credentials:
      role_arn: "arn:aws:iam::123456789:role/aiops-role"
    endpoints:
      regions: ["us-east-1"]
  datadog:
    type: datadog
    credentials:
      api_key: "${DATADOG_API_KEY}"
      app_key: "${DATADOG_APP_KEY}"
    endpoints:
      site: "datadoghq.com"
    rate_limit: 30
  prometheus:
    type: prometheus
    endpoints:
      url: "http://prometheus.monitoring:9090"
  kubernetes:
    type: kubernetes
    credentials:
      kubeconfig: "~/.kube/config"
    endpoints:
      contexts: ["prod-cluster"]
```

- [ ] **Step 5: Add `connectors_config` to config.py**

In `src/agenticops/config.py`, add field near other config paths (~line 85):
```python
connectors_config: str = Field(
    default=str(PROJECT_ROOT / "config" / "connectors.yaml"),
    description="Path to connectors YAML configuration",
)
```

- [ ] **Step 6: Run tests — expect PASS**

Run: `python -m pytest tests/test_connector_base.py -v`
Expected: All 7 tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/agenticops/connectors/registry.py config/connectors.yaml.example src/agenticops/config.py tests/test_connector_base.py
git commit -m "feat(connectors): add ConnectorRegistry with YAML config loading"
```

---

### Task 3: AWS Connector (Wrap Existing)

**Files:**
- Create: `src/agenticops/connectors/aws.py`
- Test: `tests/test_connector_aws.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_connector_aws.py
import pytest
import asyncio
from unittest.mock import patch, MagicMock
from agenticops.connectors.base import ConnectorConfig
from agenticops.connectors.aws import AWSConnector


@pytest.fixture
def aws_connector():
    cfg = ConnectorConfig(
        name="aws",
        connector_type="aws",
        credentials={"role_arn": "arn:aws:iam::123:role/test"},
        endpoints={"regions": ["us-east-1"]},
    )
    return AWSConnector(cfg)


def test_supported_operations(aws_connector):
    ops = aws_connector.supported_operations()
    assert "cloudtrail_lookup" in ops
    assert "cloudwatch_metrics" in ops
    assert "cloudwatch_logs" in ops
    assert "aws_cli" in ops


@patch("agenticops.connectors.aws.lookup_cloudtrail_events")
def test_cloudtrail_lookup(mock_lookup, aws_connector):
    mock_lookup.return_value = "2 events found"
    result = asyncio.run(aws_connector.query("cloudtrail_lookup", {
        "resource_id": "i-123",
        "resource_type": "AWS::EC2::Instance",
        "region": "us-east-1",
        "lookback_hours": 24,
    }))
    assert result["source"] == "cloudtrail"
    assert result["data"] == "2 events found"
    assert result["weight"] == 0.95


@patch("agenticops.connectors.aws.get_metrics")
def test_cloudwatch_metrics(mock_metrics, aws_connector):
    mock_metrics.return_value = "CPUUtilization: 85%"
    result = asyncio.run(aws_connector.query("cloudwatch_metrics", {
        "resource_id": "i-123",
        "metric_names": ["CPUUtilization"],
        "region": "us-east-1",
    }))
    assert result["source"] == "cloudwatch_metrics"
    assert result["weight"] == 0.80
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `python -m pytest tests/test_connector_aws.py -v`

- [ ] **Step 3: Implement AWSConnector**

```python
# src/agenticops/connectors/aws.py
from __future__ import annotations
from .base import ConnectorBase, ConnectorConfig

# Evidence source weights per spec Section 5
SOURCE_WEIGHTS = {
    "cloudtrail": 0.95,
    "cloudwatch_metrics": 0.80,
    "cloudwatch_logs": 0.75,
    "aws_cli": 0.70,
}


class AWSConnector(ConnectorBase):
    def supported_operations(self) -> list[str]:
        return ["cloudtrail_lookup", "cloudwatch_metrics", "cloudwatch_logs", "aws_cli"]

    async def query(self, operation: str, params: dict) -> dict:
        self.validate_operation(operation)
        handler = {
            "cloudtrail_lookup": self._cloudtrail,
            "cloudwatch_metrics": self._cloudwatch_metrics,
            "cloudwatch_logs": self._cloudwatch_logs,
            "aws_cli": self._aws_cli,
        }[operation]
        data = handler(params)
        return {
            "source": operation.replace("_lookup", "").replace("_metrics", ""),
            "connector": self.name,
            "data": data,
            "weight": SOURCE_WEIGHTS.get(operation, 0.70),
        }

    def _cloudtrail(self, params: dict) -> str:
        from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events
        return lookup_cloudtrail_events(
            resource_id=params["resource_id"],
            resource_type=params.get("resource_type", ""),
            region=params.get("region", ""),
            lookback_hours=params.get("lookback_hours", 24),
        )

    def _cloudwatch_metrics(self, params: dict) -> str:
        from agenticops.tools.cloudwatch_tools import get_metrics
        return get_metrics(
            resource_id=params["resource_id"],
            metric_names=params.get("metric_names", []),
            region=params.get("region", ""),
        )

    def _cloudwatch_logs(self, params: dict) -> str:
        from agenticops.tools.cloudwatch_tools import query_logs
        return query_logs(
            log_group_name=params["log_group"],
            filter_pattern=params.get("filter", ""),
            region=params.get("region", ""),
        )

    def _aws_cli(self, params: dict) -> str:
        from agenticops.tools.aws_cli_tool import run_aws_cli_readonly
        return run_aws_cli_readonly(
            service=params["service"],
            command=params["command"],
            region=params.get("region", ""),
        )

    async def test_connection(self) -> bool:
        try:
            from agenticops.tools.aws_tools import assume_role
            role_arn = self.config.credentials.get("role_arn", "")
            if role_arn:
                assume_role(role_arn=role_arn, duration_seconds=900)
            return True
        except Exception:
            return False
```

- [ ] **Step 4: Run test — expect PASS**

Run: `python -m pytest tests/test_connector_aws.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/connectors/aws.py tests/test_connector_aws.py
git commit -m "feat(connectors): add AWS connector wrapping existing tools"
```

---

### Task 4: Kubernetes Connector (Wrap Existing)

**Files:**
- Create: `src/agenticops/connectors/kubernetes.py`
- Test: `tests/test_connector_aws.py` (extend with K8s tests in same pattern)

- [ ] **Step 1: Write failing test**

```python
# tests/test_connector_kubernetes.py
import pytest
import asyncio
from unittest.mock import patch
from agenticops.connectors.base import ConnectorConfig
from agenticops.connectors.kubernetes import KubernetesConnector


@pytest.fixture
def k8s_connector():
    cfg = ConnectorConfig(
        name="kubernetes",
        connector_type="kubernetes",
        credentials={"kubeconfig": "~/.kube/config"},
        endpoints={"contexts": ["prod"]},
    )
    return KubernetesConnector(cfg)


def test_supported_operations(k8s_connector):
    ops = k8s_connector.supported_operations()
    assert "kubectl" in ops
    assert "get_pods" in ops
    assert "get_events" in ops


@patch("agenticops.connectors.kubernetes.run_kubectl")
def test_kubectl_query(mock_kubectl, k8s_connector):
    mock_kubectl.return_value = "pod/nginx Running"
    result = asyncio.run(k8s_connector.query("kubectl", {
        "cluster": "prod",
        "command": "get pods -n default",
    }))
    assert result["source"] == "kubernetes"
    assert result["weight"] == 0.80
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement KubernetesConnector**

```python
# src/agenticops/connectors/kubernetes.py
from __future__ import annotations
from .base import ConnectorBase

SOURCE_WEIGHTS = {
    "kubectl": 0.80,
    "get_pods": 0.80,
    "get_events": 0.75,
    "get_logs": 0.75,
}


class KubernetesConnector(ConnectorBase):
    def supported_operations(self) -> list[str]:
        return ["kubectl", "get_pods", "get_events", "get_logs"]

    async def query(self, operation: str, params: dict) -> dict:
        self.validate_operation(operation)
        cluster = params.get("cluster", "")
        region = params.get("region", "")

        if operation == "kubectl":
            data = self._kubectl(cluster, params["command"], region)
        elif operation == "get_pods":
            data = self._kubectl(cluster, f"get pods -n {params.get('namespace', 'default')} -o wide", region)
        elif operation == "get_events":
            data = self._kubectl(cluster, f"get events -n {params.get('namespace', 'default')} --sort-by=.lastTimestamp", region)
        elif operation == "get_logs":
            data = self._kubectl(cluster, f"logs {params['pod']} -n {params.get('namespace', 'default')} --tail=100", region)

        return {
            "source": "kubernetes",
            "connector": self.name,
            "data": data,
            "weight": SOURCE_WEIGHTS.get(operation, 0.75),
        }

    def _kubectl(self, cluster: str, command: str, region: str) -> str:
        from agenticops.skills.execution import run_kubectl
        return run_kubectl(cluster_name=cluster, command=command, region=region)

    async def test_connection(self) -> bool:
        try:
            contexts = self.config.endpoints.get("contexts", [])
            if contexts:
                self._kubectl(contexts[0], "cluster-info", "")
            return True
        except Exception:
            return False
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/connectors/kubernetes.py tests/test_connector_kubernetes.py
git commit -m "feat(connectors): add Kubernetes connector wrapping existing tools"
```

---

### Task 5: Datadog Connector (New)

**Files:**
- Create: `src/agenticops/connectors/datadog.py`
- Test: `tests/test_connector_datadog.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_connector_datadog.py
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from agenticops.connectors.base import ConnectorConfig, ConnectorError
from agenticops.connectors.datadog import DatadogConnector


@pytest.fixture
def dd_connector():
    cfg = ConnectorConfig(
        name="datadog",
        connector_type="datadog",
        credentials={"api_key": "test-api", "app_key": "test-app"},
        endpoints={"site": "datadoghq.com"},
        rate_limit=30,
    )
    return DatadogConnector(cfg)


def test_supported_operations(dd_connector):
    ops = dd_connector.supported_operations()
    assert "query_metrics" in ops
    assert "search_logs" in ops
    assert "list_monitors" in ops


@patch("agenticops.connectors.datadog.httpx.AsyncClient")
def test_query_metrics(mock_client_cls, dd_connector):
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"series": [{"pointlist": [[1, 85.0]]}]}
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client

    result = asyncio.run(dd_connector.query("query_metrics", {
        "query": "avg:system.cpu.user{service:payment-api}",
        "from_ts": 1000,
        "to_ts": 2000,
    }))
    assert result["source"] == "datadog_metrics"
    assert result["weight"] == 0.80


def test_missing_credentials():
    cfg = ConnectorConfig(name="dd", connector_type="datadog", credentials={})
    conn = DatadogConnector(cfg)
    with pytest.raises(ConnectorError, match="api_key"):
        asyncio.run(conn.query("query_metrics", {"query": "test"}))
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement DatadogConnector**

```python
# src/agenticops/connectors/datadog.py
from __future__ import annotations
import httpx
from .base import ConnectorBase, ConnectorError

SOURCE_WEIGHTS = {
    "query_metrics": 0.80,
    "search_logs": 0.75,
    "list_monitors": 0.70,
    "get_events": 0.70,
}


class DatadogConnector(ConnectorBase):
    def supported_operations(self) -> list[str]:
        return ["query_metrics", "search_logs", "list_monitors", "get_events"]

    def _headers(self) -> dict:
        api_key = self.config.credentials.get("api_key")
        app_key = self.config.credentials.get("app_key")
        if not api_key:
            raise ConnectorError(f"Connector '{self.name}': api_key required in credentials")
        return {
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": app_key or "",
        }

    def _base_url(self) -> str:
        site = self.config.endpoints.get("site", "datadoghq.com")
        return f"https://api.{site}"

    async def query(self, operation: str, params: dict) -> dict:
        self.validate_operation(operation)
        handler = {
            "query_metrics": self._query_metrics,
            "search_logs": self._search_logs,
            "list_monitors": self._list_monitors,
            "get_events": self._get_events,
        }[operation]
        data = await handler(params)
        return {
            "source": f"datadog_{operation.split('_', 1)[-1]}",
            "connector": self.name,
            "data": data,
            "weight": SOURCE_WEIGHTS.get(operation, 0.70),
        }

    async def _query_metrics(self, params: dict) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url(), headers=self._headers(), timeout=30) as client:
            resp = await client.get("/api/v1/query", params={
                "query": params["query"],
                "from": params.get("from_ts", 0),
                "to": params.get("to_ts", 0),
            })
            resp.raise_for_status()
            return resp.json()

    async def _search_logs(self, params: dict) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url(), headers=self._headers(), timeout=30) as client:
            resp = await client.post("/api/v2/logs/events/search", json={
                "filter": {"query": params.get("query", "*"), "from": params.get("from", "now-1h"), "to": params.get("to", "now")},
                "sort": "timestamp",
                "page": {"limit": params.get("limit", 50)},
            })
            resp.raise_for_status()
            return resp.json()

    async def _list_monitors(self, params: dict) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url(), headers=self._headers(), timeout=30) as client:
            resp = await client.get("/api/v1/monitor", params={"tags": params.get("tags", "")})
            resp.raise_for_status()
            return resp.json()

    async def _get_events(self, params: dict) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url(), headers=self._headers(), timeout=30) as client:
            resp = await client.get("/api/v1/events", params={
                "start": params.get("from_ts", 0),
                "end": params.get("to_ts", 0),
                "tags": params.get("tags", ""),
            })
            resp.raise_for_status()
            return resp.json()

    async def test_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(base_url=self._base_url(), headers=self._headers(), timeout=10) as client:
                resp = await client.get("/api/v1/validate")
                return resp.status_code == 200
        except Exception:
            return False
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/connectors/datadog.py tests/test_connector_datadog.py
git commit -m "feat(connectors): add Datadog API connector"
```

---

### Task 6: Prometheus Connector (New)

**Files:**
- Create: `src/agenticops/connectors/prometheus.py`
- Test: `tests/test_connector_prometheus.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_connector_prometheus.py
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from agenticops.connectors.base import ConnectorConfig
from agenticops.connectors.prometheus import PrometheusConnector


@pytest.fixture
def prom_connector():
    cfg = ConnectorConfig(
        name="prometheus",
        connector_type="prometheus",
        endpoints={"url": "http://prometheus:9090"},
    )
    return PrometheusConnector(cfg)


def test_supported_operations(prom_connector):
    ops = prom_connector.supported_operations()
    assert "query" in ops
    assert "query_range" in ops
    assert "alerts" in ops


@patch("agenticops.connectors.prometheus.httpx.AsyncClient")
def test_instant_query(mock_client_cls, prom_connector):
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "success", "data": {"result": [{"value": [1, "0.85"]}]}}
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client

    result = asyncio.run(prom_connector.query("query", {
        "promql": "rate(http_requests_total[5m])",
    }))
    assert result["source"] == "prometheus"
    assert result["weight"] == 0.80
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement PrometheusConnector**

```python
# src/agenticops/connectors/prometheus.py
from __future__ import annotations
import httpx
from .base import ConnectorBase, ConnectorError

SOURCE_WEIGHTS = {
    "query": 0.80,
    "query_range": 0.80,
    "alerts": 0.75,
    "targets": 0.70,
}


class PrometheusConnector(ConnectorBase):
    def supported_operations(self) -> list[str]:
        return ["query", "query_range", "alerts", "targets"]

    def _base_url(self) -> str:
        url = self.config.endpoints.get("url")
        if not url:
            raise ConnectorError(f"Connector '{self.name}': url required in endpoints")
        return url

    async def query(self, operation: str, params: dict) -> dict:
        self.validate_operation(operation)
        handler = {
            "query": self._instant_query,
            "query_range": self._range_query,
            "alerts": self._alerts,
            "targets": self._targets,
        }[operation]
        data = await handler(params)
        return {
            "source": "prometheus",
            "connector": self.name,
            "data": data,
            "weight": SOURCE_WEIGHTS.get(operation, 0.75),
        }

    async def _instant_query(self, params: dict) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url(), timeout=30) as client:
            resp = await client.get("/api/v1/query", params={"query": params["promql"]})
            resp.raise_for_status()
            return resp.json()

    async def _range_query(self, params: dict) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url(), timeout=30) as client:
            resp = await client.get("/api/v1/query_range", params={
                "query": params["promql"],
                "start": params.get("start", ""),
                "end": params.get("end", ""),
                "step": params.get("step", "60s"),
            })
            resp.raise_for_status()
            return resp.json()

    async def _alerts(self, params: dict) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url(), timeout=30) as client:
            resp = await client.get("/api/v1/alerts")
            resp.raise_for_status()
            return resp.json()

    async def _targets(self, params: dict) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url(), timeout=30) as client:
            resp = await client.get("/api/v1/targets")
            resp.raise_for_status()
            return resp.json()

    async def test_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(base_url=self._base_url(), timeout=10) as client:
                resp = await client.get("/api/v1/status/buildinfo")
                return resp.status_code == 200
        except Exception:
            return False
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/connectors/prometheus.py tests/test_connector_prometheus.py
git commit -m "feat(connectors): add Prometheus PromQL connector"
```

---

### Task 7: Connector Agent Tools

**Files:**
- Create: `src/agenticops/tools/connector_tools.py`
- Test: `tests/test_connector_tools.py` (basic registration test)

- [ ] **Step 1: Write failing test**

```python
# tests/test_connector_tools.py
from agenticops.tools.connector_tools import list_connectors, query_connector


def test_list_connectors_returns_string():
    result = list_connectors()
    assert isinstance(result, str)
    # Without config, returns "no connectors configured"
    assert "no connectors" in result.lower() or "connector" in result.lower()
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement connector agent tools**

```python
# src/agenticops/tools/connector_tools.py
"""Agent-facing tools for querying external systems via connectors."""
from __future__ import annotations
import asyncio
from strands import tool
from agenticops.connectors.registry import ConnectorRegistry
from agenticops.config import get_settings

_registry: ConnectorRegistry | None = None


def _get_registry() -> ConnectorRegistry:
    global _registry
    if _registry is None:
        _registry = ConnectorRegistry()
        settings = get_settings()
        _registry.load_config(settings.connectors_config)
    return _registry


@tool
def list_connectors() -> str:
    """List all configured connectors and their supported operations."""
    registry = _get_registry()
    names = registry.list_names()
    if not names:
        return "No connectors configured. Ask admin to set up config/connectors.yaml."
    lines = []
    for name in names:
        try:
            conn = registry.get(name)
            ops = ", ".join(conn.supported_operations())
            lines.append(f"  {name} ({conn.config.connector_type}): {ops}")
        except Exception as e:
            lines.append(f"  {name}: error loading — {e}")
    return "Available connectors:\n" + "\n".join(lines)


@tool
def query_connector(connector_name: str, operation: str, params: str = "{}") -> str:
    """Query an external system via a configured connector.

    Args:
        connector_name: Name of the connector (e.g., 'aws', 'datadog', 'prometheus')
        operation: Operation to execute (use list_connectors to see available operations)
        params: JSON string of operation parameters
    """
    import json
    registry = _get_registry()
    try:
        conn = registry.get(connector_name)
        parsed_params = json.loads(params)
        result = asyncio.run(conn.query(operation, parsed_params))
        source = result.get("source", connector_name)
        weight = result.get("weight", 0.5)
        data = result.get("data", "")
        # Format for LLM consumption
        return (
            f"[Evidence from {source} | weight: {weight}]\n"
            f"{data if isinstance(data, str) else json.dumps(data, indent=2, default=str)}"
        )
    except Exception as e:
        return f"Connector query failed ({connector_name}/{operation}): {e}"
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/tools/connector_tools.py tests/test_connector_tools.py
git commit -m "feat(connectors): add agent-facing connector query tools"
```

---

## Chunk 2: Service Model

### Task 8: Service Model DB Tables

**Files:**
- Modify: `src/agenticops/models.py` (add 3 new tables after CloudResource)
- Test: `tests/test_service_model.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_service_model.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from agenticops.models import Base, Service, ServiceResource, ServiceDependency, CloudResource, CloudAccount


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        # seed a CloudAccount + CloudResource
        acct = CloudAccount(name="test", provider="aws", account_id="123", regions='["us-east-1"]')
        session.add(acct)
        session.flush()
        res = CloudResource(account_id=acct.id, provider="aws", region="us-east-1",
                           resource_type="ec2", resource_id="i-123", name="web-1")
        session.add(res)
        session.flush()
        yield session, acct, res


def test_create_service(db):
    session, acct, res = db
    svc = Service(name="payment-service", tier="critical", owner="team-pay", status="inferred")
    session.add(svc)
    session.flush()
    assert svc.id is not None
    assert svc.status == "inferred"


def test_service_resource_many_to_many(db):
    session, acct, res = db
    svc = Service(name="payment-service", tier="critical", owner="team-pay")
    session.add(svc)
    session.flush()
    sr = ServiceResource(service_id=svc.id, resource_id=res.id, role="compute", is_shared=False, is_primary=True)
    session.add(sr)
    session.flush()
    assert sr.service_id == svc.id
    assert sr.resource_id == res.id


def test_service_dependency(db):
    session, acct, res = db
    svc1 = Service(name="payment-service", tier="critical", owner="team-pay")
    svc2 = Service(name="order-service", tier="high", owner="team-order")
    session.add_all([svc1, svc2])
    session.flush()
    dep = ServiceDependency(
        source_service_id=svc1.id, target_service_id=svc2.id,
        dependency_type="api_call", evidence="ALB target group", status="inferred",
    )
    session.add(dep)
    session.flush()
    assert dep.source_service_id == svc1.id


def test_service_confirmed_status(db):
    session, acct, res = db
    svc = Service(name="payment-service", tier="critical", owner="team-pay", status="inferred")
    session.add(svc)
    session.flush()
    svc.status = "confirmed"
    session.flush()
    assert svc.status == "confirmed"
```

- [ ] **Step 2: Run test — expect FAIL (Service model not found)**

Run: `python -m pytest tests/test_service_model.py -v`

- [ ] **Step 3: Add Service model tables to models.py**

Add after `CloudResource` class in `src/agenticops/models.py`:

```python
class Service(Base):
    __tablename__ = "services"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    tier = Column(String, default="standard")  # critical, high, standard, low
    owner = Column(String, default="")
    status = Column(String, default="inferred")  # inferred | confirmed
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class ServiceResource(Base):
    __tablename__ = "service_resources"
    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    resource_id = Column(Integer, ForeignKey("cloud_resources.id"), nullable=False)
    role = Column(String, default="")  # compute, database, cache, load_balancer, storage
    is_shared = Column(Boolean, default=False)
    is_primary = Column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("service_id", "resource_id"),)


class ServiceDependency(Base):
    __tablename__ = "service_dependencies"
    id = Column(Integer, primary_key=True)
    source_service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    target_service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    dependency_type = Column(String, default="")  # api_call, shared_resource, data_flow
    evidence = Column(String, default="")
    status = Column(String, default="inferred")  # inferred | confirmed
    created_at = Column(DateTime, default=func.now())
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/models.py tests/test_service_model.py
git commit -m "feat(models): add Service, ServiceResource, ServiceDependency tables"
```

---

### Task 9: Service Model CRUD Tools

**Files:**
- Modify: `src/agenticops/tools/metadata_tools.py` (add service CRUD functions)
- Test: `tests/test_service_model.py` (extend)

- [ ] **Step 1: Write failing test for CRUD**

```python
# append to tests/test_service_model.py
from agenticops.tools.metadata_tools import (
    create_service, get_service, list_services,
    add_resource_to_service, confirm_service,
    add_service_dependency,
)


def test_create_service_tool():
    # Uses real DB (test fixture needed)
    result = create_service(name="test-svc", tier="standard", owner="team-x")
    assert "created" in result.lower() or "test-svc" in result


def test_list_services_empty():
    result = list_services()
    assert isinstance(result, str)
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Add service CRUD to metadata_tools.py**

Add to `src/agenticops/tools/metadata_tools.py`:

```python
@tool
def create_service(name: str, tier: str = "standard", owner: str = "", notes: str = "") -> str:
    """Create or update a service in the service model."""
    with get_db_session() as session:
        existing = session.query(Service).filter_by(name=name).first()
        if existing:
            existing.tier = tier or existing.tier
            existing.owner = owner or existing.owner
            existing.notes = notes or existing.notes
            session.commit()
            return f"Service '{name}' updated (id={existing.id})"
        svc = Service(name=name, tier=tier, owner=owner, notes=notes, status="inferred")
        session.add(svc)
        session.commit()
        return f"Service '{name}' created (id={svc.id}, status=inferred). Needs human confirmation."


@tool
def get_service(service_name: str) -> str:
    """Get service details including resources and dependencies."""
    with get_db_session() as session:
        svc = session.query(Service).filter_by(name=service_name).first()
        if not svc:
            return f"Service '{service_name}' not found."
        resources = session.query(ServiceResource).filter_by(service_id=svc.id).all()
        deps = session.query(ServiceDependency).filter_by(source_service_id=svc.id).all()
        lines = [f"Service: {svc.name} (tier={svc.tier}, owner={svc.owner}, status={svc.status})"]
        if resources:
            lines.append(f"Resources ({len(resources)}):")
            for sr in resources:
                res = session.query(CloudResource).get(sr.resource_id)
                shared = " [SHARED]" if sr.is_shared else ""
                lines.append(f"  - {res.name or res.resource_id} ({sr.role}){shared}")
        if deps:
            lines.append(f"Dependencies ({len(deps)}):")
            for d in deps:
                target = session.query(Service).get(d.target_service_id)
                lines.append(f"  -> {target.name} ({d.dependency_type}, {d.status})")
        return "\n".join(lines)


@tool
def list_services(status: str = "") -> str:
    """List all services in the service model."""
    with get_db_session() as session:
        q = session.query(Service)
        if status:
            q = q.filter_by(status=status)
        services = q.all()
        if not services:
            return "No services registered. Use create_service to add."
        lines = [f"{s.name} (tier={s.tier}, status={s.status})" for s in services]
        return f"Services ({len(services)}):\n" + "\n".join(f"  {l}" for l in lines)


@tool
def add_resource_to_service(service_name: str, resource_id: int, role: str = "", is_shared: bool = False) -> str:
    """Link a cloud resource to a service."""
    with get_db_session() as session:
        svc = session.query(Service).filter_by(name=service_name).first()
        if not svc:
            return f"Service '{service_name}' not found."
        existing = session.query(ServiceResource).filter_by(service_id=svc.id, resource_id=resource_id).first()
        if existing:
            return f"Resource {resource_id} already linked to {service_name}."
        sr = ServiceResource(service_id=svc.id, resource_id=resource_id, role=role, is_shared=is_shared)
        session.add(sr)
        session.commit()
        return f"Resource {resource_id} linked to {service_name} (role={role})"


@tool
def confirm_service(service_name: str) -> str:
    """Human-confirm a service model entry (changes status from inferred to confirmed)."""
    with get_db_session() as session:
        svc = session.query(Service).filter_by(name=service_name).first()
        if not svc:
            return f"Service '{service_name}' not found."
        svc.status = "confirmed"
        session.commit()
        return f"Service '{service_name}' confirmed."


@tool
def add_service_dependency(source_service: str, target_service: str, dep_type: str = "api_call", evidence: str = "") -> str:
    """Add a dependency between two services."""
    with get_db_session() as session:
        src = session.query(Service).filter_by(name=source_service).first()
        tgt = session.query(Service).filter_by(name=target_service).first()
        if not src:
            return f"Source service '{source_service}' not found."
        if not tgt:
            return f"Target service '{target_service}' not found."
        dep = ServiceDependency(
            source_service_id=src.id, target_service_id=tgt.id,
            dependency_type=dep_type, evidence=evidence, status="inferred",
        )
        session.add(dep)
        session.commit()
        return f"Dependency: {source_service} -> {target_service} ({dep_type})"
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/tools/metadata_tools.py tests/test_service_model.py
git commit -m "feat(tools): add service model CRUD tools for agents"
```

---

### Task 10: Service + Connector API Endpoints

**Files:**
- Modify: `src/agenticops/web/app.py` (add connector + service endpoint groups)
- Test: manual verification via `curl` (API integration test)

- [ ] **Step 1: Add Connector API endpoints to app.py**

Add after MCP server endpoints section:

```python
# --- Connector Endpoints ---

@app.get("/api/connectors")
async def list_connectors_api():
    from agenticops.connectors.registry import ConnectorRegistry
    registry = ConnectorRegistry()
    registry.load_config(settings.connectors_config)
    return [{"name": c.name, "type": c.connector_type, "rate_limit": c.rate_limit}
            for c in registry.list_configs()]

@app.post("/api/connectors/{name}/test")
async def test_connector(name: str):
    from agenticops.connectors.registry import ConnectorRegistry
    registry = ConnectorRegistry()
    registry.load_config(settings.connectors_config)
    conn = registry.get(name)
    ok = await conn.test_connection()
    return {"name": name, "connected": ok}
```

- [ ] **Step 2: Add Service API endpoints to app.py**

```python
# --- Service Model Endpoints ---

@app.get("/api/services")
async def list_services_api(status: str = "", db: Session = Depends(get_db)):
    q = db.query(Service)
    if status:
        q = q.filter_by(status=status)
    services = q.all()
    return [{"id": s.id, "name": s.name, "tier": s.tier, "owner": s.owner, "status": s.status} for s in services]

@app.get("/api/services/{service_id}")
async def get_service_detail(service_id: int, db: Session = Depends(get_db)):
    svc = db.query(Service).get(service_id)
    if not svc:
        raise HTTPException(404, "Service not found")
    resources = db.query(ServiceResource).filter_by(service_id=svc.id).all()
    deps = db.query(ServiceDependency).filter_by(source_service_id=svc.id).all()
    return {
        "id": svc.id, "name": svc.name, "tier": svc.tier, "owner": svc.owner, "status": svc.status,
        "resources": [{"resource_id": r.resource_id, "role": r.role, "is_shared": r.is_shared} for r in resources],
        "dependencies": [{"target_service_id": d.target_service_id, "type": d.dependency_type, "status": d.status} for d in deps],
    }

@app.put("/api/services/{service_id}/confirm")
async def confirm_service_api(service_id: int, db: Session = Depends(get_db)):
    svc = db.query(Service).get(service_id)
    if not svc:
        raise HTTPException(404, "Service not found")
    svc.status = "confirmed"
    db.commit()
    return {"id": svc.id, "name": svc.name, "status": "confirmed"}
```

- [ ] **Step 3: Verify compilation**

Run: `python3 -m py_compile src/agenticops/web/app.py`

- [ ] **Step 4: Commit**

```bash
git add src/agenticops/web/app.py
git commit -m "feat(api): add connector and service model REST endpoints"
```

---

## Chunk 3: Prompt Optimization Engine

### Task 11: Evidence Model + Source Weighting

**Files:**
- Create: `src/agenticops/prompt_engine/__init__.py`
- Create: `src/agenticops/prompt_engine/evidence.py`
- Test: `tests/test_evidence.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_evidence.py
from agenticops.prompt_engine.evidence import EvidenceItem, calculate_confidence


def test_evidence_item_creation():
    e = EvidenceItem(
        source="cloudtrail",
        finding="CodePipeline deployed v24 at 10:30",
        weight=0.95,
        relevant=True,
    )
    assert e.source == "cloudtrail"
    assert e.weight == 0.95


def test_confidence_single_evidence():
    items = [EvidenceItem(source="cloudtrail", finding="deploy", weight=0.95, relevant=True)]
    conf = calculate_confidence(items)
    assert conf == 0.95


def test_confidence_weighted_average():
    items = [
        EvidenceItem(source="cloudtrail", finding="deploy at 10:30", weight=0.95, relevant=True),
        EvidenceItem(source="cloudwatch", finding="memory spike", weight=0.80, relevant=True),
        EvidenceItem(source="kb_match", finding="similar case", weight=0.50, relevant=True),
    ]
    conf = calculate_confidence(items)
    expected = (0.95 + 0.80 + 0.50) / 3  # all relevant, weighted avg
    assert abs(conf - expected) < 0.01


def test_confidence_irrelevant_excluded():
    items = [
        EvidenceItem(source="cloudtrail", finding="deploy", weight=0.95, relevant=True),
        EvidenceItem(source="cloudwatch", finding="normal cpu", weight=0.80, relevant=False),
    ]
    conf = calculate_confidence(items)
    assert conf == 0.95  # only relevant items counted


def test_confidence_no_evidence():
    conf = calculate_confidence([])
    assert conf == 0.0


def test_evidence_chain_to_string():
    items = [
        EvidenceItem(source="cloudtrail", finding="deploy at 10:30", weight=0.95, relevant=True),
        EvidenceItem(source="cloudwatch", finding="memory spike", weight=0.80, relevant=True),
    ]
    text = EvidenceItem.format_chain(items)
    assert "cloudtrail" in text
    assert "0.95" in text
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement evidence module**

```python
# src/agenticops/prompt_engine/__init__.py
# Prompt Optimization Engine

# src/agenticops/prompt_engine/evidence.py
from __future__ import annotations
from dataclasses import dataclass

# Source weights per spec Section 5
DEFAULT_SOURCE_WEIGHTS = {
    "cloudtrail": 0.95,
    "apm_trace": 0.90,
    "deployment": 0.85,
    "cloudwatch_metrics": 0.80,
    "cloudwatch_logs": 0.75,
    "prometheus": 0.80,
    "datadog_metrics": 0.80,
    "datadog_logs": 0.75,
    "kubernetes": 0.80,
    "sg_analysis": 0.70,
    "kb_match": 0.50,
    "llm_inference": 0.30,
}


@dataclass
class EvidenceItem:
    source: str
    finding: str
    weight: float
    relevant: bool = True

    @staticmethod
    def format_chain(items: list[EvidenceItem]) -> str:
        lines = []
        for i, e in enumerate(items, 1):
            mark = "+" if e.relevant else "-"
            lines.append(f"  [{mark}] {e.source} (weight={e.weight:.2f}): {e.finding}")
        return "Evidence chain:\n" + "\n".join(lines)

    @staticmethod
    def from_connector_result(result: dict, finding: str, relevant: bool = True) -> EvidenceItem:
        return EvidenceItem(
            source=result.get("source", "unknown"),
            finding=finding,
            weight=result.get("weight", DEFAULT_SOURCE_WEIGHTS.get(result.get("source", ""), 0.50)),
            relevant=relevant,
        )


def calculate_confidence(items: list[EvidenceItem]) -> float:
    relevant = [e for e in items if e.relevant]
    if not relevant:
        return 0.0
    return sum(e.weight for e in relevant) / len(relevant)
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/prompt_engine/__init__.py src/agenticops/prompt_engine/evidence.py tests/test_evidence.py
git commit -m "feat(prompt-engine): add EvidenceItem model with source weighting"
```

---

### Task 12: Alert Classifier

**Files:**
- Create: `src/agenticops/prompt_engine/classifier.py`
- Test: `tests/test_alert_classifier.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_alert_classifier.py
from agenticops.prompt_engine.classifier import AlertClassifier, ClassificationResult

# Category list from spec Section 3.1
VALID_CATEGORIES = [
    "cache", "network", "compute", "database", "security",
    "storage", "deployment", "dns", "load_balancer", "unknown",
]


def test_classification_result():
    r = ClassificationResult(category="cache", pattern="cache_memory_exhaustion", confidence=0.9)
    assert r.category in VALID_CATEGORIES
    assert r.pattern == "cache_memory_exhaustion"


def test_classify_fallback_on_empty():
    """When no LLM available, classifier returns 'unknown' category."""
    classifier = AlertClassifier(llm_classify_fn=None)
    result = classifier.classify(title="something broke", description="error 500")
    assert result.category == "unknown"
    assert result.confidence < 0.5
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement AlertClassifier**

```python
# src/agenticops/prompt_engine/classifier.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

CATEGORIES = [
    "cache", "network", "compute", "database", "security",
    "storage", "deployment", "dns", "load_balancer", "unknown",
]

KEYWORD_MAP = {
    "cache": ["redis", "memcached", "elasticache", "cache", "ttl"],
    "network": ["vpc", "subnet", "sg", "security group", "nacl", "route", "timeout", "connection refused"],
    "compute": ["ec2", "ecs", "lambda", "oom", "cpu", "memory", "instance"],
    "database": ["rds", "dynamodb", "aurora", "connection", "slow query", "deadlock"],
    "security": ["iam", "unauthorized", "403", "permission", "policy"],
    "storage": ["s3", "ebs", "efs", "disk", "iops"],
    "deployment": ["deploy", "codepipeline", "codedeploy", "rollout", "release", "version"],
    "dns": ["route53", "dns", "resolve", "nxdomain"],
    "load_balancer": ["alb", "elb", "nlb", "target group", "5xx", "502", "503", "healthcheck"],
}


@dataclass
class ClassificationResult:
    category: str
    pattern: str
    confidence: float


class AlertClassifier:
    def __init__(self, llm_classify_fn: Callable | None = None):
        self._llm_fn = llm_classify_fn

    def classify(self, title: str, description: str = "") -> ClassificationResult:
        text = f"{title} {description}".lower()

        # Phase 1: keyword-based classification (fast path)
        scores: dict[str, int] = {}
        for cat, keywords in KEYWORD_MAP.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[cat] = score

        if scores:
            best_cat = max(scores, key=scores.get)
            confidence = min(0.7, 0.3 + 0.1 * scores[best_cat])
            pattern = f"{best_cat}_{self._extract_pattern(text, best_cat)}"
            return ClassificationResult(category=best_cat, pattern=pattern, confidence=confidence)

        # Fallback: unknown
        return ClassificationResult(category="unknown", pattern="unknown_alert", confidence=0.2)

    def _extract_pattern(self, text: str, category: str) -> str:
        """Extract a rough pattern label from alert text."""
        # Simple heuristic: use first matching keyword as pattern suffix
        for kw in KEYWORD_MAP.get(category, []):
            if kw in text:
                return kw.replace(" ", "_")
        return "general"
```

Note: LLM-based classification (`_llm_fn`) is wired in Task 16 when integrating with the RCA agent. Phase 1 uses keyword classification as fast path; LLM classification upgrades in Phase 2 when Wisdom Roadmap entries exist to match against.

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/prompt_engine/classifier.py tests/test_alert_classifier.py
git commit -m "feat(prompt-engine): add AlertClassifier with keyword-based classification"
```

---

### Task 13: Few-Shot Retriever

**Files:**
- Create: `src/agenticops/prompt_engine/retriever.py`
- Test: `tests/test_prompt_assembler.py` (grouped with assembler tests)

- [ ] **Step 1: Write failing test**

```python
# tests/test_prompt_assembler.py (start of file)
from agenticops.prompt_engine.retriever import FewShotRetriever


def test_retriever_returns_empty_on_no_kb():
    retriever = FewShotRetriever(search_fn=lambda *a, **kw: "No similar cases found")
    cases = retriever.retrieve(category="cache", alert_text="Redis OOM", top_k=3)
    assert cases == []


def test_retriever_parses_kb_results():
    def mock_search(resource_type, symptom):
        return "Case-42: Redis OOM after deploy\nCase-18: Cache timeout spike"
    retriever = FewShotRetriever(search_fn=mock_search)
    cases = retriever.retrieve(category="cache", alert_text="Redis OOM", top_k=1)
    assert len(cases) <= 1
    assert isinstance(cases[0], str)
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement FewShotRetriever**

```python
# src/agenticops/prompt_engine/retriever.py
from __future__ import annotations
from typing import Callable


class FewShotRetriever:
    def __init__(self, search_fn: Callable | None = None):
        self._search = search_fn

    def retrieve(self, category: str, alert_text: str, top_k: int = 3) -> list[str]:
        if self._search is None:
            return []
        result = self._search(resource_type=category, symptom=alert_text)
        if not result or "no similar" in result.lower() or "not found" in result.lower():
            return []
        # Parse KB results: each case is typically a block separated by newlines
        cases = [line.strip() for line in result.strip().split("\n") if line.strip()]
        return cases[:top_k]
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/prompt_engine/retriever.py tests/test_prompt_assembler.py
git commit -m "feat(prompt-engine): add FewShotRetriever for KB case lookup"
```

---

### Task 14: Strategy Selector

**Files:**
- Create: `src/agenticops/prompt_engine/strategy.py`
- Test: `tests/test_prompt_assembler.py` (extend)

- [ ] **Step 1: Write failing test**

```python
# append to tests/test_prompt_assembler.py
from agenticops.prompt_engine.strategy import StrategySelector


def test_strategy_returns_default_for_unknown():
    selector = StrategySelector(wisdom_search_fn=None)
    strategy = selector.select(category="unknown", pattern="unknown_alert")
    assert "investigate" in strategy.lower()
    assert isinstance(strategy, str)


def test_strategy_returns_wisdom_match():
    def mock_wisdom(pattern):
        return "Check deployments first (85% success rate), then verify target group health."
    selector = StrategySelector(wisdom_search_fn=mock_wisdom)
    strategy = selector.select(category="load_balancer", pattern="lb_5xx")
    assert "deployment" in strategy.lower()
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement StrategySelector**

```python
# src/agenticops/prompt_engine/strategy.py
from __future__ import annotations
from typing import Callable

DEFAULT_STRATEGIES = {
    "cache": "1) Check cache memory/connection metrics 2) Look for recent deployments 3) Verify TTL configuration",
    "network": "1) Check security groups and NACLs 2) Verify route tables 3) Test connectivity between resources",
    "compute": "1) Check instance/container status 2) Review CPU/memory metrics 3) Look for OOM events",
    "database": "1) Check connection count 2) Review slow query logs 3) Verify storage/IOPS limits",
    "security": "1) Check IAM policy changes 2) Review CloudTrail for unauthorized access 3) Verify resource policies",
    "storage": "1) Check disk/IOPS utilization 2) Review recent write patterns 3) Verify storage limits",
    "deployment": "1) Check CloudTrail for recent deploys 2) Compare with previous version 3) Review rollback options",
    "dns": "1) Check Route53 record propagation 2) Verify health checks 3) Test DNS resolution",
    "load_balancer": "1) Check target group health 2) Verify backend service status 3) Review recent deployments",
    "unknown": "1) Check CloudTrail for recent changes 2) Review CloudWatch metrics 3) Search KB for similar patterns",
}


class StrategySelector:
    def __init__(self, wisdom_search_fn: Callable | None = None):
        self._wisdom_fn = wisdom_search_fn

    def select(self, category: str, pattern: str) -> str:
        # Try Wisdom Roadmap first (Phase 2+ will populate this)
        if self._wisdom_fn:
            wisdom = self._wisdom_fn(pattern)
            if wisdom and "not found" not in wisdom.lower():
                return wisdom

        # Fallback to default strategies
        return DEFAULT_STRATEGIES.get(category, DEFAULT_STRATEGIES["unknown"])
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/prompt_engine/strategy.py tests/test_prompt_assembler.py
git commit -m "feat(prompt-engine): add StrategySelector with default strategies"
```

---

### Task 15: Prompt Assembler (Token Budget)

**Files:**
- Create: `src/agenticops/prompt_engine/assembler.py`
- Test: `tests/test_prompt_assembler.py` (extend)

- [ ] **Step 1: Write failing test**

```python
# append to tests/test_prompt_assembler.py
from agenticops.prompt_engine.assembler import PromptAssembler


def test_assembler_basic():
    assembler = PromptAssembler(max_tokens=3000)
    prompt = assembler.assemble(
        alert_title="ALB 5xx on payment-service",
        alert_description="HealthCheckFailures > 5",
        category="load_balancer",
        strategy="Check target group health first",
        few_shot_cases=["Case-42: similar ALB issue resolved by fixing target group"],
        service_context="payment-service: ECS x3 + Redis + RDS. Redis shared with order-service.",
    )
    assert "payment-service" in prompt
    assert "target group" in prompt
    assert "Case-42" in prompt
    assert len(prompt) > 100


def test_assembler_respects_token_budget():
    assembler = PromptAssembler(max_tokens=500)
    long_cases = ["x" * 2000]  # very long case
    prompt = assembler.assemble(
        alert_title="test",
        alert_description="",
        category="unknown",
        strategy="investigate",
        few_shot_cases=long_cases,
        service_context="",
    )
    # Token estimation: ~4 chars per token, 500 tokens ~ 2000 chars
    # Prompt should be truncated to respect budget
    assert len(prompt) < 3000  # rough check


def test_assembler_no_fewshot():
    assembler = PromptAssembler(max_tokens=3000)
    prompt = assembler.assemble(
        alert_title="Lambda timeout",
        alert_description="Duration > 30s",
        category="compute",
        strategy="Check function configuration",
        few_shot_cases=[],
        service_context="",
    )
    assert "Lambda timeout" in prompt
    assert "similar" not in prompt.lower() or "no similar" in prompt.lower()
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement PromptAssembler**

```python
# src/agenticops/prompt_engine/assembler.py
from __future__ import annotations

# Approximate chars-per-token for budget estimation (conservative)
CHARS_PER_TOKEN = 4


class PromptAssembler:
    def __init__(self, max_tokens: int = 3000):
        self.max_tokens = max_tokens

    def assemble(
        self,
        alert_title: str,
        alert_description: str,
        category: str,
        strategy: str,
        few_shot_cases: list[str],
        service_context: str,
    ) -> str:
        sections = []

        # 1. Base role (~500 tokens budget)
        sections.append(self._base_role())

        # 2. Alert context (always included, not budgeted — this is the input)
        sections.append(self._alert_section(alert_title, alert_description, category))

        # 3. Service context (~300 tokens budget)
        if service_context:
            sc = self._truncate(service_context, 300)
            sections.append(f"Service context:\n{sc}")

        # 4. Strategy (~1500 tokens budget, includes wisdom)
        sections.append(f"Investigation strategy ({category}):\n{self._truncate(strategy, 1500)}")

        # 5. Few-shot cases (~500 tokens budget)
        if few_shot_cases:
            cases_text = "\n".join(f"- {c}" for c in few_shot_cases)
            cases_text = self._truncate(cases_text, 500)
            sections.append(f"Similar past cases:\n{cases_text}")

        prompt = "\n\n".join(sections)

        # Final budget check: if over, apply overflow strategy (spec Section 3.4)
        if self._estimate_tokens(prompt) > self.max_tokens:
            prompt = self._apply_overflow(prompt, few_shot_cases, service_context, strategy, alert_title, alert_description, category)

        return prompt

    def _base_role(self) -> str:
        return (
            "You are an expert SRE agent performing root cause analysis. "
            "Investigate systematically using available tools and connectors. "
            "Collect evidence from multiple sources. Weight evidence by source reliability. "
            "Produce a root cause with confidence score and evidence chain."
        )

    def _alert_section(self, title: str, description: str, category: str) -> str:
        return f"Alert: {title}\nCategory: {category}\nDetails: {description}"

    def _truncate(self, text: str, token_budget: int) -> str:
        max_chars = token_budget * CHARS_PER_TOKEN
        if len(text) <= max_chars:
            return text
        return text[:max_chars - 3] + "..."

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // CHARS_PER_TOKEN

    def _apply_overflow(self, prompt, few_shot_cases, service_context, strategy, alert_title, alert_description, category):
        """Overflow strategy per spec Section 3.4:
        1. Reduce few-shot to summary
        2. Trim wisdom/strategy entries
        3. Truncate service context to direct dependencies
        """
        sections = [self._base_role(), self._alert_section(alert_title, alert_description, category)]

        if service_context:
            sections.append(f"Service context:\n{self._truncate(service_context, 150)}")

        sections.append(f"Strategy:\n{self._truncate(strategy, 800)}")

        if few_shot_cases:
            summary = f"({len(few_shot_cases)} similar past cases available)"
            sections.append(f"Similar cases: {summary}")

        return "\n\n".join(sections)
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/prompt_engine/assembler.py tests/test_prompt_assembler.py
git commit -m "feat(prompt-engine): add PromptAssembler with token budget and overflow strategy"
```

---

## Chunk 4: Agent Integration

### Task 16: Integrate Prompt Engine + Evidence into RCA Agent

**Files:**
- Modify: `src/agenticops/agents/rca_agent.py` (integrate prompt engine)
- Modify: `src/agenticops/agents/preamble.py` (add dynamic prompt builder)
- Modify: `src/agenticops/agents/main_agent.py` (register connector + service tools)

- [ ] **Step 1: Update preamble.py — add `build_optimized_prompt` function**

In `src/agenticops/agents/preamble.py`, add:

```python
def build_optimized_prompt(
    alert_title: str,
    alert_description: str,
    base_system_prompt: str,
) -> str:
    """Build an optimized system prompt using the Prompt Optimization Engine.
    Falls back to base_system_prompt if engine components unavailable."""
    try:
        from agenticops.prompt_engine.classifier import AlertClassifier
        from agenticops.prompt_engine.strategy import StrategySelector
        from agenticops.prompt_engine.retriever import FewShotRetriever
        from agenticops.prompt_engine.assembler import PromptAssembler

        classifier = AlertClassifier()
        classification = classifier.classify(alert_title, alert_description)

        # Strategy: try KB wisdom, fall back to defaults
        try:
            from agenticops.kb.search import search_similar_cases
            retriever = FewShotRetriever(search_fn=lambda rt, s: search_similar_cases(rt, s))
        except Exception:
            retriever = FewShotRetriever(search_fn=None)

        selector = StrategySelector(wisdom_search_fn=None)  # Phase 2: wire wisdom lookup
        strategy = selector.select(classification.category, classification.pattern)
        few_shots = retriever.retrieve(classification.category, alert_title, top_k=1)

        # Service context: try DB lookup
        service_context = ""
        try:
            from agenticops.tools.metadata_tools import get_service
            # Extract service name from alert (heuristic: first word before common suffixes)
            # This is best-effort; agent will also look up service context during investigation
        except Exception:
            pass

        assembler = PromptAssembler(max_tokens=3000)
        optimized_section = assembler.assemble(
            alert_title=alert_title,
            alert_description=alert_description,
            category=classification.category,
            strategy=strategy,
            few_shot_cases=few_shots,
            service_context=service_context,
        )

        return f"{base_system_prompt}\n\n--- Prompt Optimization Context ---\n{optimized_section}"
    except Exception:
        # Fallback: return base prompt unchanged
        return base_system_prompt
```

- [ ] **Step 2: Update main_agent.py — register new tools**

In `src/agenticops/agents/main_agent.py`, add connector + service tools to the tools list:

```python
from agenticops.tools.connector_tools import list_connectors, query_connector
from agenticops.tools.metadata_tools import (
    create_service, get_service, list_services,
    add_resource_to_service, confirm_service,
    add_service_dependency,
)
# Add to tools list in create_main_agent():
# ..., list_connectors, query_connector,
# ..., create_service, get_service, list_services,
#      add_resource_to_service, confirm_service, add_service_dependency,
```

- [ ] **Step 3: Update rca_agent.py — add connector + evidence tools**

In `src/agenticops/agents/rca_agent.py`, add to tools list:
```python
from agenticops.tools.connector_tools import list_connectors, query_connector
```

Add to system prompt investigation protocol:
```
Step 2b: Check available connectors (list_connectors). Use query_connector
to fetch evidence from external systems (Datadog, Prometheus, etc.)
Each connector result includes evidence weight — record these for confidence scoring.
```

- [ ] **Step 4: Verify compilation**

```bash
python3 -m py_compile src/agenticops/agents/preamble.py
python3 -m py_compile src/agenticops/agents/main_agent.py
python3 -m py_compile src/agenticops/agents/rca_agent.py
```

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/agents/preamble.py src/agenticops/agents/main_agent.py src/agenticops/agents/rca_agent.py
git commit -m "feat(agents): integrate prompt engine, connectors, and service tools"
```

---

### Task 17: Add `connectors.yaml` to .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add entry**

```
# Connector credentials
config/connectors.yaml
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore connectors.yaml (credentials)"
```

---

### Task 18: Integration Test — End-to-End Smoke Test

- [ ] **Step 1: Run all tests**

```bash
python -m pytest tests/test_connector_base.py tests/test_connector_aws.py tests/test_connector_datadog.py tests/test_connector_prometheus.py tests/test_service_model.py tests/test_alert_classifier.py tests/test_prompt_assembler.py tests/test_evidence.py -v
```

Expected: All tests PASS

- [ ] **Step 2: Run full test suite to check no regressions**

```bash
python -m pytest tests/ -v
```

Expected: No regressions in existing tests

- [ ] **Step 3: Verify app compiles**

```bash
python3 -m py_compile src/agenticops/web/app.py
python3 -m py_compile src/agenticops/agents/main_agent.py
python3 -m py_compile src/agenticops/models.py
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "test: Phase 1 integration verification — all tests passing"
```

---

## Summary: Phase 1 Deliverables

| Component | Tasks | Files Created | Files Modified |
|-----------|-------|--------------|----------------|
| Connector Framework | 1-7 | 8 new files | config.py, .gitignore |
| Service Model | 8-10 | 1 test file | models.py, metadata_tools.py, app.py |
| Prompt Engine | 11-15 | 6 new files | — |
| Agent Integration | 16-18 | — | preamble.py, main_agent.py, rca_agent.py |
| **Total** | **18 tasks** | **15 new files** | **7 modified files** |

### Dependency Graph

```
Task 1 (ConnectorBase) ──┬── Task 3 (AWS) ────┐
                         ├── Task 4 (K8s) ─────┤
Task 2 (Registry+Config)─┤                     ├── Task 7 (Connector Tools) ── Task 16 (Integration)
                         ├── Task 5 (Datadog)──┤
                         └── Task 6 (Prom) ────┘

Task 8 (Service DB) ── Task 9 (Service CRUD) ── Task 10 (Service API) ── Task 16 (Integration)

Task 11 (Evidence) ──┐
Task 12 (Classifier)─┤
Task 13 (Retriever) ─┼── Task 15 (Assembler) ── Task 16 (Integration)
Task 14 (Strategy) ──┘
```

Parallel tracks: Connectors (1-7), Service Model (8-10), and Prompt Engine (11-15) can be developed concurrently. Task 16 merges them.

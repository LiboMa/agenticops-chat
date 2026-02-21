"""Web Dashboard - FastAPI + HTMX simple dashboard + React SPA."""

import os
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, Request, Query, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel, Field

from agenticops.models import (
    AWSAccount,
    AWSResource,
    Anomaly,
    RCAResult,
    Report,
    MonitoringConfig,
    get_session,
    get_db_session,
    init_db,
)
from agenticops.config import settings

import json
import logging

from agenticops.graph.api import router as graph_router

logger = logging.getLogger(__name__)


def _ensure_aws_session(region: str):
    """Ensure an AWS session exists for the given region.

    If no assumed-role session exists, inject a default boto3 session
    from environment credentials (suitable for local/internal dashboard).
    """
    import boto3
    import agenticops.tools.aws_tools as aws_tools_module

    for key in aws_tools_module._session_cache:
        if key.endswith(f":{region}"):
            return  # Already have a session for this region
    # Inject default credentials session
    session = boto3.Session(region_name=region)
    aws_tools_module._session_cache[f"web:{region}"] = session
    logger.info("Injected default AWS session for region %s", region)


# ============================================================================
# Pydantic Models for API
# ============================================================================


class AccountCreate(BaseModel):
    """Schema for creating an account."""
    name: str = Field(..., max_length=100)
    account_id: str = Field(..., max_length=12)
    role_arn: str = Field(..., max_length=200)
    external_id: Optional[str] = Field(None, max_length=100)
    regions: List[str] = Field(default_factory=lambda: ["us-east-1"])
    is_active: bool = True


class AccountUpdate(BaseModel):
    """Schema for updating an account."""
    name: Optional[str] = Field(None, max_length=100)
    role_arn: Optional[str] = Field(None, max_length=200)
    external_id: Optional[str] = Field(None, max_length=100)
    regions: Optional[List[str]] = None
    is_active: Optional[bool] = None


class AccountResponse(BaseModel):
    """Schema for account response."""
    id: int
    name: str
    account_id: str
    role_arn: str
    external_id: Optional[str]
    regions: List[str]
    is_active: bool
    created_at: datetime
    last_scanned_at: Optional[datetime]

    class Config:
        from_attributes = True


class ResourceResponse(BaseModel):
    """Schema for resource response."""
    id: int
    account_id: int
    resource_id: str
    resource_arn: Optional[str]
    resource_type: str
    resource_name: Optional[str]
    region: str
    status: str
    resource_metadata: dict
    tags: dict
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AnomalyStatusUpdate(BaseModel):
    """Schema for updating anomaly status."""
    status: str = Field(..., pattern="^(open|acknowledged|resolved)$")
    note: Optional[str] = None


class AnomalyResponse(BaseModel):
    """Schema for anomaly response."""
    id: int
    resource_id: str
    resource_type: str
    region: str
    anomaly_type: str
    severity: str
    title: str
    description: str
    metric_name: Optional[str]
    expected_value: Optional[float]
    actual_value: Optional[float]
    deviation_percent: Optional[float]
    status: str
    detected_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class RCAResponse(BaseModel):
    """Schema for RCA response."""
    id: int
    anomaly_id: int
    analysis_type: str
    root_cause: str
    confidence_score: float
    contributing_factors: List[str]
    recommendations: List[str]
    related_resources: List[str]
    llm_model: str
    created_at: datetime

    class Config:
        from_attributes = True


class ReportResponse(BaseModel):
    """Schema for report response."""
    id: int
    report_type: str
    title: str
    summary: str
    content_markdown: str
    content_html: Optional[str]
    file_path: Optional[str]
    report_metadata: dict
    created_at: datetime

    class Config:
        from_attributes = True


class ReportGenerateRequest(BaseModel):
    """Schema for report generation request."""
    report_type: str = Field(default="daily", pattern="^(daily|inventory|anomaly)$")
    account_name: Optional[str] = None


class HealthResponse(BaseModel):
    """Schema for health check response."""
    status: str
    version: str
    database: str
    timestamp: datetime


# ============================================================================
# Auth Pydantic Models
# ============================================================================


class LoginRequest(BaseModel):
    """Schema for login request."""
    email: str
    password: str


class LoginResponse(BaseModel):
    """Schema for login response."""
    token: str
    user_id: int
    email: str
    name: Optional[str]
    is_admin: bool
    expires_at: datetime


class RegisterRequest(BaseModel):
    """Schema for user registration."""
    email: str
    password: str
    name: Optional[str] = None


class UserResponse(BaseModel):
    """Schema for user response."""
    id: int
    email: str
    name: Optional[str]
    is_admin: bool
    permissions: List[str]
    last_login_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class APIKeyCreate(BaseModel):
    """Schema for creating an API key."""
    name: str
    permissions: List[str] = ["read"]
    expires_days: Optional[int] = None


class APIKeyResponse(BaseModel):
    """Schema for API key response."""
    id: int
    name: str
    key_prefix: str
    permissions: List[str]
    is_active: bool
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class APIKeyCreatedResponse(BaseModel):
    """Schema for newly created API key (includes the full key)."""
    id: int
    name: str
    key: str  # Full key - only shown once!
    permissions: List[str]
    expires_at: Optional[datetime]


class PasswordChangeRequest(BaseModel):
    """Schema for password change."""
    old_password: str
    new_password: str

# Initialize FastAPI app
app = FastAPI(
    title="AgenticAIOps Dashboard",
    description="Agent-First Cloud Observability Platform",
    version="0.1.0",
)

# Graph API router
app.include_router(graph_router)

# Templates directory
TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATES_DIR.mkdir(exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ============================================================================
# Base Layout Template
# ============================================================================


BASE_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - AgenticAIOps</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .htmx-indicator { opacity: 0; transition: opacity 200ms ease-in; }
        .htmx-request .htmx-indicator { opacity: 1; }
        .htmx-request.htmx-indicator { opacity: 1; }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <!-- Navigation -->
    <nav class="bg-indigo-600 text-white shadow-lg">
        <div class="max-w-7xl mx-auto px-4 py-3">
            <div class="flex items-center justify-between">
                <div class="flex items-center space-x-4">
                    <a href="/" class="text-xl font-bold">AgenticAIOps</a>
                    <a href="/" class="hover:text-indigo-200">Dashboard</a>
                    <a href="/resources" class="hover:text-indigo-200">Resources</a>
                    <a href="/anomalies" class="hover:text-indigo-200">Anomalies</a>
                    <a href="/reports" class="hover:text-indigo-200">Reports</a>
                    <a href="/network" class="hover:text-indigo-200">Network</a>
                </div>
                <div class="text-sm text-indigo-200">
                    {{ now.strftime('%Y-%m-%d %H:%M UTC') }}
                </div>
            </div>
        </div>
    </nav>

    <!-- Main Content -->
    <main class="max-w-7xl mx-auto px-4 py-6">
        {% block content %}{% endblock %}
    </main>

    <!-- Footer -->
    <footer class="bg-gray-200 text-gray-600 text-center py-4 mt-8">
        AgenticAIOps v0.1.0 - Agent-First Cloud Observability
    </footer>
</body>
</html>'''


# ============================================================================
# Create Templates
# ============================================================================


def ensure_templates():
    """Ensure templates exist."""
    TEMPLATES_DIR.mkdir(exist_ok=True)

    # Base template
    (TEMPLATES_DIR / "base.html").write_text(BASE_TEMPLATE)

    # Dashboard template
    dashboard_html = '''{% extends "base.html" %}
{% block content %}
<div class="space-y-6">
    <!-- Summary Cards -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div class="bg-white rounded-lg shadow p-6">
            <div class="text-gray-500 text-sm">Total Resources</div>
            <div class="text-3xl font-bold text-indigo-600">{{ stats.total_resources }}</div>
        </div>
        <div class="bg-white rounded-lg shadow p-6">
            <div class="text-gray-500 text-sm">Open Anomalies</div>
            <div class="text-3xl font-bold text-red-600">{{ stats.open_anomalies }}</div>
        </div>
        <div class="bg-white rounded-lg shadow p-6">
            <div class="text-gray-500 text-sm">Critical Issues</div>
            <div class="text-3xl font-bold text-red-800">{{ stats.critical_anomalies }}</div>
        </div>
        <div class="bg-white rounded-lg shadow p-6">
            <div class="text-gray-500 text-sm">Accounts</div>
            <div class="text-3xl font-bold text-gray-700">{{ stats.total_accounts }}</div>
        </div>
    </div>

    <!-- Recent Anomalies -->
    <div class="bg-white rounded-lg shadow">
        <div class="px-6 py-4 border-b border-gray-200">
            <h2 class="text-lg font-semibold">Recent Anomalies</h2>
        </div>
        <div class="p-6">
            {% if anomalies %}
            <table class="w-full">
                <thead>
                    <tr class="text-left text-gray-500 text-sm">
                        <th class="pb-2">Severity</th>
                        <th class="pb-2">Title</th>
                        <th class="pb-2">Resource</th>
                        <th class="pb-2">Detected</th>
                    </tr>
                </thead>
                <tbody>
                    {% for a in anomalies %}
                    <tr class="border-t">
                        <td class="py-2">
                            {% if a.severity == 'critical' %}
                            <span class="px-2 py-1 text-xs rounded bg-red-600 text-white">CRITICAL</span>
                            {% elif a.severity == 'high' %}
                            <span class="px-2 py-1 text-xs rounded bg-orange-500 text-white">HIGH</span>
                            {% elif a.severity == 'medium' %}
                            <span class="px-2 py-1 text-xs rounded bg-yellow-500 text-white">MEDIUM</span>
                            {% else %}
                            <span class="px-2 py-1 text-xs rounded bg-blue-500 text-white">LOW</span>
                            {% endif %}
                        </td>
                        <td class="py-2">{{ a.title[:50] }}{% if a.title|length > 50 %}...{% endif %}</td>
                        <td class="py-2 text-sm text-gray-500">{{ a.resource_type }}/{{ a.resource_id[:20] }}</td>
                        <td class="py-2 text-sm text-gray-500">{{ a.detected_at.strftime('%m-%d %H:%M') }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p class="text-gray-500">No anomalies detected.</p>
            {% endif %}
        </div>
    </div>

    <!-- Resources by Type -->
    <div class="bg-white rounded-lg shadow">
        <div class="px-6 py-4 border-b border-gray-200">
            <h2 class="text-lg font-semibold">Resources by Type</h2>
        </div>
        <div class="p-6">
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                {% for rt, count in resource_types %}
                <div class="text-center p-4 bg-gray-50 rounded">
                    <div class="text-2xl font-bold text-indigo-600">{{ count }}</div>
                    <div class="text-sm text-gray-500">{{ rt }}</div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
</div>
{% endblock %}'''
    (TEMPLATES_DIR / "dashboard.html").write_text(dashboard_html)

    # Resources template
    resources_html = '''{% extends "base.html" %}
{% block content %}
<div class="bg-white rounded-lg shadow">
    <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
        <h2 class="text-lg font-semibold">Resources ({{ resources|length }})</h2>
        <div class="flex space-x-2">
            <select id="type-filter" class="border rounded px-3 py-1 text-sm"
                    hx-get="/resources" hx-target="body" hx-include="#region-filter"
                    name="type">
                <option value="">All Types</option>
                {% for t in types %}
                <option value="{{ t }}" {% if t == current_type %}selected{% endif %}>{{ t }}</option>
                {% endfor %}
            </select>
            <select id="region-filter" class="border rounded px-3 py-1 text-sm"
                    hx-get="/resources" hx-target="body" hx-include="#type-filter"
                    name="region">
                <option value="">All Regions</option>
                {% for r in regions %}
                <option value="{{ r }}" {% if r == current_region %}selected{% endif %}>{{ r }}</option>
                {% endfor %}
            </select>
        </div>
    </div>
    <div class="overflow-x-auto">
        <table class="w-full">
            <thead>
                <tr class="bg-gray-50 text-left text-gray-500 text-sm">
                    <th class="px-6 py-3">Type</th>
                    <th class="px-6 py-3">Resource ID</th>
                    <th class="px-6 py-3">Name</th>
                    <th class="px-6 py-3">Region</th>
                    <th class="px-6 py-3">Status</th>
                </tr>
            </thead>
            <tbody>
                {% for r in resources %}
                <tr class="border-t hover:bg-gray-50">
                    <td class="px-6 py-3">
                        <span class="px-2 py-1 text-xs rounded bg-indigo-100 text-indigo-800">{{ r.resource_type }}</span>
                    </td>
                    <td class="px-6 py-3 font-mono text-sm">{{ r.resource_id }}</td>
                    <td class="px-6 py-3">{{ r.resource_name or '-' }}</td>
                    <td class="px-6 py-3 text-sm text-gray-500">{{ r.region }}</td>
                    <td class="px-6 py-3">
                        {% if r.status == 'running' %}
                        <span class="text-green-600">{{ r.status }}</span>
                        {% elif r.status == 'stopped' %}
                        <span class="text-red-600">{{ r.status }}</span>
                        {% else %}
                        <span class="text-gray-500">{{ r.status }}</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
{% endblock %}'''
    (TEMPLATES_DIR / "resources.html").write_text(resources_html)

    # Anomalies template
    anomalies_html = '''{% extends "base.html" %}
{% block content %}
<div class="bg-white rounded-lg shadow">
    <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
        <h2 class="text-lg font-semibold">Anomalies ({{ anomalies|length }})</h2>
        <div class="flex space-x-2">
            <select class="border rounded px-3 py-1 text-sm"
                    hx-get="/anomalies" hx-target="body" name="severity">
                <option value="">All Severities</option>
                <option value="critical" {% if severity == 'critical' %}selected{% endif %}>Critical</option>
                <option value="high" {% if severity == 'high' %}selected{% endif %}>High</option>
                <option value="medium" {% if severity == 'medium' %}selected{% endif %}>Medium</option>
                <option value="low" {% if severity == 'low' %}selected{% endif %}>Low</option>
            </select>
        </div>
    </div>
    <div class="divide-y">
        {% for a in anomalies %}
        <div class="p-6 hover:bg-gray-50">
            <div class="flex items-start justify-between">
                <div>
                    <div class="flex items-center space-x-2">
                        {% if a.severity == 'critical' %}
                        <span class="px-2 py-1 text-xs rounded bg-red-600 text-white">CRITICAL</span>
                        {% elif a.severity == 'high' %}
                        <span class="px-2 py-1 text-xs rounded bg-orange-500 text-white">HIGH</span>
                        {% elif a.severity == 'medium' %}
                        <span class="px-2 py-1 text-xs rounded bg-yellow-500 text-white">MEDIUM</span>
                        {% else %}
                        <span class="px-2 py-1 text-xs rounded bg-blue-500 text-white">LOW</span>
                        {% endif %}
                        <span class="font-semibold">{{ a.title }}</span>
                    </div>
                    <p class="mt-2 text-gray-600">{{ a.description }}</p>
                    <div class="mt-2 text-sm text-gray-500">
                        {{ a.resource_type }}/{{ a.resource_id }} | {{ a.region }} | {{ a.detected_at.strftime('%Y-%m-%d %H:%M') }}
                    </div>
                </div>
                <a href="/anomaly/{{ a.id }}" class="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700">
                    View
                </a>
            </div>
        </div>
        {% endfor %}
        {% if not anomalies %}
        <div class="p-6 text-center text-gray-500">No anomalies found.</div>
        {% endif %}
    </div>
</div>
{% endblock %}'''
    (TEMPLATES_DIR / "anomalies.html").write_text(anomalies_html)

    # Anomaly detail template
    anomaly_detail_html = '''{% extends "base.html" %}
{% block content %}
<div class="space-y-6">
    <div class="bg-white rounded-lg shadow p-6">
        <div class="flex items-center space-x-2 mb-4">
            {% if anomaly.severity == 'critical' %}
            <span class="px-2 py-1 text-xs rounded bg-red-600 text-white">CRITICAL</span>
            {% elif anomaly.severity == 'high' %}
            <span class="px-2 py-1 text-xs rounded bg-orange-500 text-white">HIGH</span>
            {% elif anomaly.severity == 'medium' %}
            <span class="px-2 py-1 text-xs rounded bg-yellow-500 text-white">MEDIUM</span>
            {% else %}
            <span class="px-2 py-1 text-xs rounded bg-blue-500 text-white">LOW</span>
            {% endif %}
            <h1 class="text-2xl font-bold">{{ anomaly.title }}</h1>
        </div>
        <p class="text-gray-600 mb-4">{{ anomaly.description }}</p>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div><span class="text-gray-500">Resource:</span> {{ anomaly.resource_id }}</div>
            <div><span class="text-gray-500">Type:</span> {{ anomaly.resource_type }}</div>
            <div><span class="text-gray-500">Region:</span> {{ anomaly.region }}</div>
            <div><span class="text-gray-500">Status:</span> {{ anomaly.status }}</div>
        </div>
        {% if anomaly.metric_name %}
        <div class="mt-4 p-4 bg-gray-50 rounded">
            <h3 class="font-semibold mb-2">Metric Details</h3>
            <div class="grid grid-cols-3 gap-4 text-sm">
                <div><span class="text-gray-500">Metric:</span> {{ anomaly.metric_name }}</div>
                <div><span class="text-gray-500">Expected:</span> {{ anomaly.expected_value }}</div>
                <div><span class="text-gray-500">Actual:</span> {{ anomaly.actual_value }}</div>
            </div>
        </div>
        {% endif %}
    </div>

    {% if rca %}
    <div class="bg-white rounded-lg shadow p-6">
        <h2 class="text-xl font-bold mb-4">Root Cause Analysis</h2>
        <div class="mb-4">
            <div class="text-sm text-gray-500 mb-1">Confidence: {{ (rca.confidence_score * 100)|int }}%</div>
            <div class="w-full bg-gray-200 rounded-full h-2">
                <div class="bg-indigo-600 h-2 rounded-full" style="width: {{ rca.confidence_score * 100 }}%"></div>
            </div>
        </div>
        <div class="mb-4">
            <h3 class="font-semibold mb-2">Root Cause</h3>
            <p class="text-gray-700">{{ rca.root_cause }}</p>
        </div>
        {% if rca.contributing_factors %}
        <div class="mb-4">
            <h3 class="font-semibold mb-2">Contributing Factors</h3>
            <ul class="list-disc list-inside text-gray-700">
                {% for f in rca.contributing_factors %}
                <li>{{ f }}</li>
                {% endfor %}
            </ul>
        </div>
        {% endif %}
        {% if rca.recommendations %}
        <div>
            <h3 class="font-semibold mb-2">Recommendations</h3>
            <ol class="list-decimal list-inside text-gray-700">
                {% for r in rca.recommendations %}
                <li>{{ r }}</li>
                {% endfor %}
            </ol>
        </div>
        {% endif %}
    </div>
    {% endif %}
</div>
{% endblock %}'''
    (TEMPLATES_DIR / "anomaly_detail.html").write_text(anomaly_detail_html)

    # Reports template
    reports_html = '''{% extends "base.html" %}
{% block content %}
<div class="bg-white rounded-lg shadow">
    <div class="px-6 py-4 border-b border-gray-200">
        <h2 class="text-lg font-semibold">Reports</h2>
    </div>
    <div class="divide-y">
        {% for r in reports %}
        <div class="p-6 hover:bg-gray-50">
            <div class="flex items-start justify-between">
                <div>
                    <span class="px-2 py-1 text-xs rounded bg-gray-200 text-gray-700">{{ r.report_type }}</span>
                    <span class="ml-2 font-semibold">{{ r.title }}</span>
                    <p class="mt-2 text-sm text-gray-600">{{ r.summary[:200] }}{% if r.summary|length > 200 %}...{% endif %}</p>
                    <div class="mt-2 text-sm text-gray-500">{{ r.created_at.strftime('%Y-%m-%d %H:%M') }}</div>
                </div>
                {% if r.file_path %}
                <a href="/report/{{ r.id }}" class="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700">
                    View
                </a>
                {% endif %}
            </div>
        </div>
        {% endfor %}
        {% if not reports %}
        <div class="p-6 text-center text-gray-500">No reports generated yet.</div>
        {% endif %}
    </div>
</div>
{% endblock %}'''
    (TEMPLATES_DIR / "reports.html").write_text(reports_html)

    # Network / VPC Topology template
    network_html = '''{% extends "base.html" %}
{% block content %}
<div class="space-y-6">
    <!-- Input Form -->
    <div class="bg-white rounded-lg shadow p-6">
        <h2 class="text-lg font-semibold mb-4">VPC Topology Analysis</h2>
        <div class="flex flex-wrap items-end gap-4">
            <div>
                <label class="block text-sm text-gray-600 mb-1">Region</label>
                <input id="region" type="text" value="us-east-1"
                       class="border rounded px-3 py-2 w-48 text-sm" placeholder="us-east-1">
            </div>
            <div>
                <label class="block text-sm text-gray-600 mb-1">VPC ID</label>
                <input id="vpc-id" type="text"
                       class="border rounded px-3 py-2 w-64 text-sm" placeholder="vpc-0abc123...">
            </div>
            <button hx-get="/api/network/vpc-topology"
                    hx-include="#region, #vpc-id"
                    hx-vals=\'js:{region: document.getElementById("region").value, vpc_id: document.getElementById("vpc-id").value}\'
                    hx-target="#result"
                    hx-indicator="#spinner"
                    class="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 text-sm">
                Analyze Topology
            </button>
            <button hx-get="/api/network/vpcs"
                    hx-vals=\'js:{region: document.getElementById("region").value}\'
                    hx-target="#vpc-list"
                    hx-indicator="#spinner"
                    class="bg-gray-600 text-white px-4 py-2 rounded hover:bg-gray-700 text-sm">
                List VPCs
            </button>
            <span id="spinner" class="htmx-indicator">
                <svg class="animate-spin h-5 w-5 text-indigo-600 inline" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                Loading...
            </span>
        </div>
        <!-- VPC List Helper -->
        <div id="vpc-list" class="mt-4"></div>
    </div>

    <!-- Result Area -->
    <div id="result"></div>
</div>
{% endblock %}'''
    (TEMPLATES_DIR / "network.html").write_text(network_html)

    # VPC list fragment template (returned by /api/network/vpcs)
    vpc_list_fragment = '''<div class="bg-gray-50 rounded p-4">
    <h3 class="text-sm font-semibold text-gray-700 mb-2">VPCs in {{ region }} ({{ vpcs|length }})</h3>
    {% if vpcs %}
    <table class="w-full text-sm">
        <thead>
            <tr class="text-left text-gray-500">
                <th class="pb-1 pr-4">VPC ID</th>
                <th class="pb-1 pr-4">CIDR</th>
                <th class="pb-1 pr-4">Name</th>
                <th class="pb-1 pr-4">State</th>
                <th class="pb-1">Default</th>
                <th class="pb-1"></th>
            </tr>
        </thead>
        <tbody>
            {% for v in vpcs %}
            <tr class="border-t border-gray-200">
                <td class="py-1 pr-4 font-mono">{{ v.VpcId }}</td>
                <td class="py-1 pr-4">{{ v.CidrBlock }}</td>
                <td class="py-1 pr-4">{{ v.Name or "-" }}</td>
                <td class="py-1 pr-4">{{ v.State }}</td>
                <td class="py-1">{{ "Yes" if v.IsDefault else "No" }}</td>
                <td class="py-1">
                    <button onclick="document.getElementById(\'vpc-id\').value=\'{{ v.VpcId }}\'"
                            class="text-indigo-600 hover:text-indigo-800 text-xs underline">Use</button>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p class="text-gray-500 text-sm">No VPCs found in this region.</p>
    {% endif %}
</div>'''
    (TEMPLATES_DIR / "vpc_list_fragment.html").write_text(vpc_list_fragment)

    # VPC topology result fragment template
    topology_fragment = '''<div class="space-y-4">
    <!-- Reachability Summary -->
    <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-lg font-semibold mb-3">Reachability Summary</h3>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <div class="text-center p-3 bg-gray-50 rounded">
                <div class="text-2xl font-bold {% if topology.reachability_summary.has_igw %}text-green-600{% else %}text-gray-400{% endif %}">
                    {{ "Yes" if topology.reachability_summary.has_igw else "No" }}
                </div>
                <div class="text-xs text-gray-500">Internet Gateway</div>
            </div>
            <div class="text-center p-3 bg-gray-50 rounded">
                <div class="text-2xl font-bold text-indigo-600">{{ topology.reachability_summary.public_subnets }}</div>
                <div class="text-xs text-gray-500">Public Subnets</div>
            </div>
            <div class="text-center p-3 bg-gray-50 rounded">
                <div class="text-2xl font-bold text-gray-700">{{ topology.reachability_summary.private_subnets }}</div>
                <div class="text-xs text-gray-500">Private Subnets</div>
            </div>
            <div class="text-center p-3 bg-gray-50 rounded">
                <div class="text-2xl font-bold text-orange-600">{{ topology.reachability_summary.nat_gateways }}</div>
                <div class="text-xs text-gray-500">NAT Gateways</div>
            </div>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div class="text-center p-3 bg-gray-50 rounded">
                <div class="text-xl font-bold text-gray-600">{{ topology.reachability_summary.transit_gateways }}</div>
                <div class="text-xs text-gray-500">Transit Gateways</div>
            </div>
            <div class="text-center p-3 bg-gray-50 rounded">
                <div class="text-xl font-bold text-gray-600">{{ topology.reachability_summary.peering_connections }}</div>
                <div class="text-xs text-gray-500">VPC Peering</div>
            </div>
            <div class="text-center p-3 bg-gray-50 rounded">
                <div class="text-xl font-bold text-gray-600">{{ topology.reachability_summary.vpc_endpoints }}</div>
                <div class="text-xs text-gray-500">VPC Endpoints</div>
            </div>
            <div class="text-center p-3 bg-gray-50 rounded">
                <div class="text-xl font-bold {% if topology.reachability_summary.issues|length > 0 %}text-red-600{% else %}text-green-600{% endif %}">
                    {{ topology.reachability_summary.issues|length }}
                </div>
                <div class="text-xs text-gray-500">Issues</div>
            </div>
        </div>
        {% if topology.reachability_summary.issues %}
        <div class="mt-4 p-3 bg-red-50 border border-red-200 rounded">
            <h4 class="text-sm font-semibold text-red-800 mb-1">Issues</h4>
            <ul class="text-sm text-red-700 list-disc list-inside">
                {% for issue in topology.reachability_summary.issues %}
                <li>{{ issue }}</li>
                {% endfor %}
            </ul>
        </div>
        {% endif %}
    </div>

    <!-- VPC Info -->
    <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-lg font-semibold mb-3">VPC Details</h3>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div><span class="text-gray-500">VPC ID:</span> <span class="font-mono">{{ topology.vpc_id }}</span></div>
            <div><span class="text-gray-500">CIDR:</span> {{ topology.cidr_block }}</div>
            <div><span class="text-gray-500">Name:</span> {{ topology.vpc_name or "-" }}</div>
            <div><span class="text-gray-500">Region:</span> {{ topology.region }}</div>
        </div>
    </div>

    <!-- Subnets Table -->
    <div class="bg-white rounded-lg shadow">
        <div class="px-6 py-4 border-b border-gray-200">
            <h3 class="text-lg font-semibold">Subnets ({{ topology.subnets|length }})</h3>
        </div>
        <div class="overflow-x-auto">
            <table class="w-full text-sm">
                <thead>
                    <tr class="bg-gray-50 text-left text-gray-500">
                        <th class="px-4 py-2">Subnet ID</th>
                        <th class="px-4 py-2">Name</th>
                        <th class="px-4 py-2">AZ</th>
                        <th class="px-4 py-2">CIDR</th>
                        <th class="px-4 py-2">Type</th>
                        <th class="px-4 py-2">Available IPs</th>
                        <th class="px-4 py-2">Route Table</th>
                        <th class="px-4 py-2">Default Target</th>
                    </tr>
                </thead>
                <tbody>
                    {% for s in topology.subnets %}
                    <tr class="border-t hover:bg-gray-50">
                        <td class="px-4 py-2 font-mono">{{ s.subnet_id }}</td>
                        <td class="px-4 py-2">{{ s.name or "-" }}</td>
                        <td class="px-4 py-2">{{ s.availability_zone }}</td>
                        <td class="px-4 py-2">{{ s.cidr_block }}</td>
                        <td class="px-4 py-2">
                            {% if s.type == "public" %}
                            <span class="px-2 py-0.5 text-xs rounded bg-green-100 text-green-800">public</span>
                            {% else %}
                            <span class="px-2 py-0.5 text-xs rounded bg-gray-200 text-gray-700">private</span>
                            {% endif %}
                        </td>
                        <td class="px-4 py-2">{{ s.available_ips }}</td>
                        <td class="px-4 py-2 font-mono text-xs">{{ s.route_table_id or "-" }}</td>
                        <td class="px-4 py-2 text-xs">{{ s.default_route_target or "-" }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Blackhole Routes Alert -->
    {% if topology.blackhole_routes %}
    <div class="bg-red-50 border border-red-300 rounded-lg shadow p-6">
        <h3 class="text-lg font-semibold text-red-800 mb-2">Blackhole Routes</h3>
        <table class="w-full text-sm">
            <thead>
                <tr class="text-left text-red-700">
                    <th class="pb-1 pr-4">Route Table</th>
                    <th class="pb-1 pr-4">Destination</th>
                    <th class="pb-1">Target</th>
                </tr>
            </thead>
            <tbody>
                {% for bh in topology.blackhole_routes %}
                <tr class="border-t border-red-200">
                    <td class="py-1 pr-4 font-mono">{{ bh.route_table_id }}</td>
                    <td class="py-1 pr-4">{{ bh.destination }}</td>
                    <td class="py-1">{{ bh.target }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}

    <!-- Security Group Dependency Map -->
    {% if topology.sg_dependency_map %}
    <div class="bg-white rounded-lg shadow">
        <details>
            <summary class="px-6 py-4 cursor-pointer hover:bg-gray-50 font-semibold text-lg">
                Security Group Dependencies ({{ topology.sg_dependency_map|length }})
            </summary>
            <div class="px-6 pb-4 overflow-x-auto">
                <table class="w-full text-sm">
                    <thead>
                        <tr class="text-left text-gray-500">
                            <th class="pb-1 pr-4">SG ID</th>
                            <th class="pb-1 pr-4">Name</th>
                            <th class="pb-1 pr-4">Inbound From SGs</th>
                            <th class="pb-1">Outbound To SGs</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for sg in topology.sg_dependency_map %}
                        <tr class="border-t">
                            <td class="py-1 pr-4 font-mono">{{ sg.sg_id }}</td>
                            <td class="py-1 pr-4">{{ sg.name or "-" }}</td>
                            <td class="py-1 pr-4 text-xs">{{ sg.inbound_from | join(", ") if sg.inbound_from else "-" }}</td>
                            <td class="py-1 text-xs">{{ sg.outbound_to | join(", ") if sg.outbound_to else "-" }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </details>
    </div>
    {% endif %}
</div>'''
    (TEMPLATES_DIR / "topology_fragment.html").write_text(topology_fragment)


# ============================================================================
# Routes
# ============================================================================


@app.on_event("startup")
async def startup():
    """Initialize on startup."""
    init_db()
    ensure_templates()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Dashboard homepage."""
    session = get_session()
    try:
        from sqlalchemy import func

        stats = {
            "total_resources": session.query(AWSResource).count(),
            "open_anomalies": session.query(Anomaly).filter_by(status="open").count(),
            "critical_anomalies": session.query(Anomaly).filter_by(severity="critical", status="open").count(),
            "total_accounts": session.query(AWSAccount).count(),
        }

        anomalies = (
            session.query(Anomaly)
            .filter_by(status="open")
            .order_by(Anomaly.detected_at.desc())
            .limit(10)
            .all()
        )

        resource_types = (
            session.query(AWSResource.resource_type, func.count(AWSResource.id))
            .group_by(AWSResource.resource_type)
            .all()
        )

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "title": "Dashboard",
                "now": datetime.utcnow(),
                "stats": stats,
                "anomalies": anomalies,
                "resource_types": resource_types,
            },
        )
    finally:
        session.close()


@app.get("/resources", response_class=HTMLResponse)
async def resources_list(
    request: Request,
    type: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
):
    """Resources list page."""
    session = get_session()
    try:
        query = session.query(AWSResource)

        if type:
            query = query.filter_by(resource_type=type)
        if region:
            query = query.filter_by(region=region)

        resources = query.limit(100).all()

        # Get unique types and regions for filters
        types = [r[0] for r in session.query(AWSResource.resource_type).distinct().all()]
        regions = [r[0] for r in session.query(AWSResource.region).distinct().all()]

        return templates.TemplateResponse(
            "resources.html",
            {
                "request": request,
                "title": "Resources",
                "now": datetime.utcnow(),
                "resources": resources,
                "types": types,
                "regions": regions,
                "current_type": type,
                "current_region": region,
            },
        )
    finally:
        session.close()


@app.get("/anomalies", response_class=HTMLResponse)
async def anomalies_list(
    request: Request,
    severity: Optional[str] = Query(None),
):
    """Anomalies list page."""
    session = get_session()
    try:
        query = session.query(Anomaly).order_by(Anomaly.detected_at.desc())

        if severity:
            query = query.filter_by(severity=severity)

        anomalies = query.limit(50).all()

        return templates.TemplateResponse(
            "anomalies.html",
            {
                "request": request,
                "title": "Anomalies",
                "now": datetime.utcnow(),
                "anomalies": anomalies,
                "severity": severity,
            },
        )
    finally:
        session.close()


@app.get("/anomaly/{anomaly_id}", response_class=HTMLResponse)
async def anomaly_detail(request: Request, anomaly_id: int):
    """Anomaly detail page."""
    session = get_session()
    try:
        anomaly = session.query(Anomaly).filter_by(id=anomaly_id).first()
        if not anomaly:
            return HTMLResponse("Anomaly not found", status_code=404)

        rca = (
            session.query(RCAResult)
            .filter_by(anomaly_id=anomaly_id)
            .order_by(RCAResult.created_at.desc())
            .first()
        )

        return templates.TemplateResponse(
            "anomaly_detail.html",
            {
                "request": request,
                "title": f"Anomaly #{anomaly_id}",
                "now": datetime.utcnow(),
                "anomaly": anomaly,
                "rca": rca,
            },
        )
    finally:
        session.close()


@app.get("/reports", response_class=HTMLResponse)
async def reports_list(request: Request):
    """Reports list page."""
    session = get_session()
    try:
        reports = (
            session.query(Report)
            .order_by(Report.created_at.desc())
            .limit(settings.default_list_limit)
            .all()
        )

        return templates.TemplateResponse(
            "reports.html",
            {
                "request": request,
                "title": "Reports",
                "now": datetime.utcnow(),
                "reports": reports,
            },
        )
    finally:
        session.close()


@app.get("/network", response_class=HTMLResponse)
async def network_page(request: Request):
    """Network / VPC Topology analysis page."""
    return templates.TemplateResponse(
        "network.html",
        {"request": request, "title": "Network", "now": datetime.utcnow()},
    )


# ============================================================================
# Network API Endpoints
# ============================================================================


@app.get("/api/network/vpcs")
async def api_list_vpcs(request: Request, region: str = Query("us-east-1")):
    """List VPCs in a region (live AWS API call)."""
    try:
        _ensure_aws_session(region)
        from agenticops.tools.network_tools import describe_vpcs

        result = describe_vpcs(region=region)
        vpcs = json.loads(result)
        return JSONResponse({"region": region, "vpcs": vpcs})
    except Exception as e:
        logger.exception("Failed to list VPCs")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/network/region-topology")
async def api_region_topology(request: Request, region: str = Query("us-east-1")):
    """Get region-level topology: VPCs, Transit Gateways, Peering connections."""
    try:
        _ensure_aws_session(region)
        from agenticops.tools.network_tools import describe_region_topology

        result = describe_region_topology(region=region)
        topology = json.loads(result)
        return JSONResponse(topology)
    except Exception as e:
        logger.exception("Failed to get region topology")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/network/vpc-topology")
async def api_vpc_topology(
    request: Request,
    region: str = Query(...),
    vpc_id: str = Query(...),
):
    """Analyze VPC topology (live AWS API call)."""
    try:
        _ensure_aws_session(region)
        from agenticops.tools.network_tools import analyze_vpc_topology

        result = analyze_vpc_topology(region=region, vpc_id=vpc_id)
        topology = json.loads(result)
        return JSONResponse(topology)
    except Exception as e:
        logger.exception("Failed to analyze VPC topology")
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================================
# API Endpoints
# ============================================================================


@app.get("/api/health", response_model=HealthResponse)
async def api_health():
    """Health check endpoint."""
    from agenticops import __version__

    db_status = "ok"
    try:
        with get_db_session() as session:
            session.execute("SELECT 1")
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="healthy" if db_status == "ok" else "degraded",
        version=__version__,
        database=db_status,
        timestamp=datetime.utcnow(),
    )


@app.get("/api/stats")
async def api_stats():
    """API endpoint for dashboard stats."""
    with get_db_session() as session:
        return {
            "total_resources": session.query(AWSResource).count(),
            "open_anomalies": session.query(Anomaly).filter_by(status="open").count(),
            "critical_anomalies": session.query(Anomaly).filter_by(severity="critical", status="open").count(),
            "total_accounts": session.query(AWSAccount).count(),
        }


# ============================================================================
# Account API Endpoints
# ============================================================================


@app.get("/api/accounts", response_model=List[AccountResponse])
async def api_list_accounts():
    """List all AWS accounts."""
    with get_db_session() as session:
        accounts = session.query(AWSAccount).all()
        return [AccountResponse.model_validate(a) for a in accounts]


@app.get("/api/accounts/{account_id}", response_model=AccountResponse)
async def api_get_account(account_id: int):
    """Get account by ID."""
    with get_db_session() as session:
        account = session.query(AWSAccount).filter_by(id=account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return AccountResponse.model_validate(account)


@app.post("/api/accounts", response_model=AccountResponse, status_code=201)
async def api_create_account(account: AccountCreate):
    """Create a new AWS account."""
    with get_db_session() as session:
        # Check if account name or account_id already exists
        existing = session.query(AWSAccount).filter(
            (AWSAccount.name == account.name) | (AWSAccount.account_id == account.account_id)
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Account name or ID already exists")

        db_account = AWSAccount(
            name=account.name,
            account_id=account.account_id,
            role_arn=account.role_arn,
            external_id=account.external_id,
            regions=account.regions,
            is_active=account.is_active,
        )
        session.add(db_account)
        session.flush()  # Get the ID
        return AccountResponse.model_validate(db_account)


@app.put("/api/accounts/{account_id}", response_model=AccountResponse)
async def api_update_account(account_id: int, account: AccountUpdate):
    """Update an existing AWS account."""
    with get_db_session() as session:
        db_account = session.query(AWSAccount).filter_by(id=account_id).first()
        if not db_account:
            raise HTTPException(status_code=404, detail="Account not found")

        update_data = account.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_account, key, value)

        session.flush()
        return AccountResponse.model_validate(db_account)


@app.delete("/api/accounts/{account_id}", status_code=204)
async def api_delete_account(account_id: int):
    """Delete an AWS account."""
    with get_db_session() as session:
        db_account = session.query(AWSAccount).filter_by(id=account_id).first()
        if not db_account:
            raise HTTPException(status_code=404, detail="Account not found")

        session.delete(db_account)


# ============================================================================
# Resource API Endpoints
# ============================================================================


@app.get("/api/resources", response_model=List[ResourceResponse])
async def api_list_resources(
    resource_type: Optional[str] = Query(None, alias="type"),
    region: Optional[str] = None,
    account_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    """List resources with filtering."""
    with get_db_session() as session:
        query = session.query(AWSResource)

        if resource_type:
            query = query.filter_by(resource_type=resource_type)
        if region:
            query = query.filter_by(region=region)
        if account_id:
            query = query.filter_by(account_id=account_id)
        if status:
            query = query.filter_by(status=status)

        resources = query.offset(offset).limit(limit).all()
        return [ResourceResponse.model_validate(r) for r in resources]


@app.get("/api/resources/{resource_id}", response_model=ResourceResponse)
async def api_get_resource(resource_id: int):
    """Get resource by ID."""
    with get_db_session() as session:
        resource = session.query(AWSResource).filter_by(id=resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        return ResourceResponse.model_validate(resource)


# ============================================================================
# Anomaly API Endpoints
# ============================================================================


@app.get("/api/anomalies", response_model=List[AnomalyResponse])
async def api_list_anomalies(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    resource_type: Optional[str] = None,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = 0,
):
    """List anomalies with filtering."""
    with get_db_session() as session:
        query = session.query(Anomaly).order_by(Anomaly.detected_at.desc())

        if severity:
            query = query.filter_by(severity=severity)
        if status:
            query = query.filter_by(status=status)
        if resource_type:
            query = query.filter_by(resource_type=resource_type)

        anomalies = query.offset(offset).limit(limit).all()
        return [AnomalyResponse.model_validate(a) for a in anomalies]


@app.get("/api/anomalies/{anomaly_id}", response_model=AnomalyResponse)
async def api_get_anomaly(anomaly_id: int):
    """Get anomaly by ID."""
    with get_db_session() as session:
        anomaly = session.query(Anomaly).filter_by(id=anomaly_id).first()
        if not anomaly:
            raise HTTPException(status_code=404, detail="Anomaly not found")
        return AnomalyResponse.model_validate(anomaly)


@app.put("/api/anomalies/{anomaly_id}/status", response_model=AnomalyResponse)
async def api_update_anomaly_status(anomaly_id: int, update: AnomalyStatusUpdate):
    """Update anomaly status."""
    with get_db_session() as session:
        anomaly = session.query(Anomaly).filter_by(id=anomaly_id).first()
        if not anomaly:
            raise HTTPException(status_code=404, detail="Anomaly not found")

        anomaly.status = update.status
        if update.status == "resolved":
            anomaly.resolved_at = datetime.utcnow()

        session.flush()
        return AnomalyResponse.model_validate(anomaly)


@app.get("/api/anomalies/{anomaly_id}/rca", response_model=Optional[RCAResponse])
async def api_get_anomaly_rca(anomaly_id: int):
    """Get RCA result for an anomaly."""
    with get_db_session() as session:
        anomaly = session.query(Anomaly).filter_by(id=anomaly_id).first()
        if not anomaly:
            raise HTTPException(status_code=404, detail="Anomaly not found")

        rca = (
            session.query(RCAResult)
            .filter_by(anomaly_id=anomaly_id)
            .order_by(RCAResult.created_at.desc())
            .first()
        )

        if not rca:
            return None

        return RCAResponse.model_validate(rca)


# ============================================================================
# Report API Endpoints
# ============================================================================


@app.get("/api/reports", response_model=List[ReportResponse])
async def api_list_reports(
    report_type: Optional[str] = None,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = 0,
):
    """List reports with filtering."""
    with get_db_session() as session:
        query = session.query(Report).order_by(Report.created_at.desc())

        if report_type:
            query = query.filter_by(report_type=report_type)

        reports = query.offset(offset).limit(limit).all()
        return [ReportResponse.model_validate(r) for r in reports]


@app.get("/api/reports/{report_id}", response_model=ReportResponse)
async def api_get_report(report_id: int):
    """Get report by ID."""
    with get_db_session() as session:
        report = session.query(Report).filter_by(id=report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        return ReportResponse.model_validate(report)


@app.post("/api/reports/generate", response_model=ReportResponse, status_code=201)
async def api_generate_report(request: ReportGenerateRequest):
    """Generate a new report."""
    from agenticops.report import ReportGenerator

    with get_db_session() as session:
        # Get account if specified
        account = None
        if request.account_name:
            account = session.query(AWSAccount).filter_by(name=request.account_name).first()
            if not account:
                raise HTTPException(status_code=404, detail="Account not found")
        else:
            account = session.query(AWSAccount).filter_by(is_active=True).first()

        generator = ReportGenerator(account)

        if request.report_type == "daily":
            content = generator.generate_daily_report()
        elif request.report_type == "inventory":
            content = generator.generate_inventory_report()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown report type: {request.report_type}")

        # Get the last generated report
        report = (
            session.query(Report)
            .order_by(Report.created_at.desc())
            .first()
        )

        if report:
            return ReportResponse.model_validate(report)
        else:
            raise HTTPException(status_code=500, detail="Report generation failed")


# ============================================================================
# Authentication API Endpoints
# ============================================================================


@app.post("/api/auth/register", response_model=UserResponse, status_code=201)
async def api_register(request_data: RegisterRequest):
    """Register a new user."""
    from agenticops.auth import AuthService

    try:
        user = AuthService.create_user(
            email=request_data.email,
            password=request_data.password,
            name=request_data.name,
        )
        return UserResponse.model_validate(user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/login", response_model=LoginResponse)
async def api_login(request: Request, request_data: LoginRequest):
    """Login and get a session token."""
    from agenticops.auth import AuthService
    from datetime import timedelta

    user = AuthService.authenticate(request_data.email, request_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Get client info
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Create session
    token = AuthService.create_session(user.id, ip_address, user_agent)

    return LoginResponse(
        token=token,
        user_id=user.id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
        expires_at=datetime.utcnow() + timedelta(hours=AuthService.SESSION_DURATION_HOURS),
    )


@app.post("/api/auth/logout")
async def api_logout(request: Request):
    """Logout and invalidate the session."""
    from agenticops.auth import AuthService

    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        AuthService.invalidate_session(token)

    return {"message": "Logged out successfully"}


@app.get("/api/users/me", response_model=UserResponse)
async def api_get_current_user(request: Request):
    """Get the currently authenticated user."""
    from agenticops.auth import get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Extract credentials from header
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return UserResponse.model_validate(user)


@app.put("/api/users/me/password")
async def api_change_password(request: Request, request_data: PasswordChangeRequest):
    """Change the current user's password."""
    from agenticops.auth import AuthService, get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not AuthService.update_password(user.id, request_data.old_password, request_data.new_password):
        raise HTTPException(status_code=400, detail="Invalid current password")

    return {"message": "Password changed successfully"}


@app.post("/api/api-keys", response_model=APIKeyCreatedResponse, status_code=201)
async def api_create_api_key(request: Request, request_data: APIKeyCreate):
    """Create a new API key for the current user."""
    from agenticops.auth import AuthService, get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Create API key
    key = AuthService.create_api_key(
        user_id=user.id,
        name=request_data.name,
        permissions=request_data.permissions,
        expires_days=request_data.expires_days,
    )

    # Get the created key info
    with get_db_session() as session:
        from agenticops.auth.models import APIKey
        api_key = session.query(APIKey).filter_by(user_id=user.id).order_by(APIKey.created_at.desc()).first()

        return APIKeyCreatedResponse(
            id=api_key.id,
            name=api_key.name,
            key=key,  # Full key - only shown once!
            permissions=api_key.permissions,
            expires_at=api_key.expires_at,
        )


@app.get("/api/api-keys", response_model=List[APIKeyResponse])
async def api_list_api_keys(request: Request):
    """List API keys for the current user."""
    from agenticops.auth import AuthService, get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    keys = AuthService.list_api_keys(user.id)
    return [APIKeyResponse.model_validate(k) for k in keys]


@app.delete("/api/api-keys/{key_id}", status_code=204)
async def api_revoke_api_key(request: Request, key_id: int):
    """Revoke an API key."""
    from agenticops.auth import AuthService, get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not AuthService.revoke_api_key(key_id, user.id):
        raise HTTPException(status_code=404, detail="API key not found")


# ============================================================================
# Audit API Endpoints
# ============================================================================


class AuditLogResponse(BaseModel):
    """Schema for audit log response."""
    id: int
    timestamp: datetime
    user_id: Optional[int]
    user_email: Optional[str]
    action: str
    entity_type: str
    entity_id: str
    entity_name: Optional[str]
    details: dict
    old_values: Optional[dict]
    new_values: Optional[dict]
    ip_address: Optional[str]

    class Config:
        from_attributes = True


@app.get("/api/audit", response_model=List[AuditLogResponse])
async def api_list_audit_logs(
    request: Request,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    user_id: Optional[int] = None,
    hours: int = Query(24, le=720),
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    """List audit log entries (requires admin)."""
    from agenticops.auth import get_current_user
    from agenticops.audit import AuditService
    from fastapi.security import HTTPAuthorizationCredentials
    from datetime import timedelta

    # Get current user (admin required)
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    start_time = datetime.utcnow() - timedelta(hours=hours)

    logs = AuditService.query(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        start_time=start_time,
        limit=limit,
        offset=offset,
    )

    return [AuditLogResponse.model_validate(log) for log in logs]


@app.get("/api/audit/entity/{entity_type}/{entity_id}", response_model=List[AuditLogResponse])
async def api_get_entity_audit(
    request: Request,
    entity_type: str,
    entity_id: str,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
):
    """Get audit history for a specific entity."""
    from agenticops.auth import get_current_user
    from agenticops.audit import AuditService
    from fastapi.security import HTTPAuthorizationCredentials

    # Get current user
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = await get_current_user(request, credentials)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    else:
        raise HTTPException(status_code=401, detail="Authentication required")

    logs = AuditService.get_entity_history(
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
    )

    return [AuditLogResponse.model_validate(log) for log in logs]


@app.get("/api/audit/stats")
async def api_get_audit_stats(request: Request, hours: int = Query(24, le=720)):
    """Get audit statistics (requires admin)."""
    from agenticops.auth import get_current_user
    from agenticops.audit import AuditService
    from fastapi.security import HTTPAuthorizationCredentials
    from datetime import timedelta

    # Get current user (admin required)
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(request, credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    start_time = datetime.utcnow() - timedelta(hours=hours)

    return {
        "period_hours": hours,
        "total_events": AuditService.count_actions(start_time=start_time),
        "creates": AuditService.count_actions(action="create", start_time=start_time),
        "updates": AuditService.count_actions(action="update", start_time=start_time),
        "deletes": AuditService.count_actions(action="delete", start_time=start_time),
        "logins": AuditService.count_actions(action="login", start_time=start_time),
        "login_failures": AuditService.count_actions(action="login_failed", start_time=start_time),
    }


# ============================================================================
# React SPA (served at /app/*)
# ============================================================================

FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"

# Mount built SPA assets
if (FRONTEND_DIR / "assets").exists():
    app.mount(
        "/app/assets",
        StaticFiles(directory=str(FRONTEND_DIR / "assets")),
        name="spa-assets",
    )


@app.get("/app/{full_path:path}")
async def serve_spa(full_path: str):
    """SPA fallback — serve index.html for all /app/* routes."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    raise HTTPException(status_code=404, detail="Frontend not built. Run: cd frontend && npm install && npm run build")


# ============================================================================
# Dev CORS (only when AIOPS_DEV_MODE is set)
# ============================================================================

if os.getenv("AIOPS_DEV_MODE"):
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ============================================================================
# Run Server Function
# ============================================================================


def run_server(host: str = "127.0.0.1", port: int = 8080):
    """Run the web server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()

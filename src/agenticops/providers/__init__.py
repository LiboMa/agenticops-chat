"""Providers package — multi-cloud provider abstraction.

Imports provider modules to auto-register via @register_provider.
Azure and GCP are conditional on SDK availability.
Alicloud is always available (CLI-only, no Python SDK dependency).
"""

from .base import (  # noqa: F401
    CloudProvider,
    SessionCache,
    get_provider_class,
    register_provider,
    registered_providers,
)

# Auto-register built-in providers
from . import aws  # noqa: F401
from . import alicloud  # noqa: F401

# Conditional: only register if SDK is installed
try:
    from . import azure  # noqa: F401
except ImportError:
    pass

try:
    from . import gcp  # noqa: F401
except ImportError:
    pass

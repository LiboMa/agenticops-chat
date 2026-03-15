"""Providers package — multi-cloud provider abstraction.

Import aws module to auto-register AWSProvider.
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

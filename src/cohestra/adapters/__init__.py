"""Provider-neutral contracts, filesystem strategies, and portable adapters."""

from .contracts import Adapter, Capability, DispatchRequest, DispatchResult
from .providers import PROVIDERS, ProviderDescriptor, detect_providers

__all__ = [
    "Adapter",
    "Capability",
    "DispatchRequest",
    "DispatchResult",
    "PROVIDERS",
    "ProviderDescriptor",
    "detect_providers",
]

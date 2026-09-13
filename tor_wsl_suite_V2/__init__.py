"""
Cyberdeck Tor Suite - Root Package Init
Exponiert die zentralen Manager-Klassen und den Orchestrator für die direkte Nutzung.
"""

from core import (
    PrivoxyManager,
    RAMDiskManager,
    SecurityManager,
    SystemChecker,
    TorManager,
    WindowsProxyManager,
)
from core.service_manager import TorServiceManager

__version__ = "1.0.0"
__author__ = "Cyberdeck"

__all__ = [
    # Core Managers
    "SystemChecker",
    "SecurityManager",
    "WindowsProxyManager",
    "TorServiceManager",
    "TorManager",
    "PrivoxyManager",
    "RAMDiskManager",
    # Main Entry Points (Lazy Loaded)
    "TorSuiteOrchestrator",
    "ensure_root",
    "main",
]


def __getattr__(name: str):
    """Verhindert Circular Imports durch verzögertes Laden der main.py-Komponenten."""
    if name in ("TorSuiteOrchestrator", "ensure_root", "main"):
        import main as main_module
        return getattr(main_module, name)
    raise AttributeError(f"Modul {__name__!r} hat kein Attribut {name!r}")
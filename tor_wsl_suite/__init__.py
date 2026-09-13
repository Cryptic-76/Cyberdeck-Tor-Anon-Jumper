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
from main import TorSuiteOrchestrator, ensure_root, main

__version__ = "1.0.0"
__author__ = "Cyberdeck"

__all__ = [
    # Main Orchestrator & Entry Points
    "TorSuiteOrchestrator",
    "ensure_root",
    "main",
    # Core Managers
    "SystemChecker",
    "SecurityManager",
    "WindowsProxyManager",
    "TorServiceManager",
    "TorManager",
    "PrivoxyManager",
    "RAMDiskManager",
]
"""Dejo as MCP tools: a browser with a memory, for the AI you already use."""

from .server import build_server, run_stdio

__version__ = "0.3.0"
__all__ = ["build_server", "run_stdio", "__version__"]

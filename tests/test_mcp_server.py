# tests/test_mcp_server.py
import asyncio

from app.mcp.server import mcp


def test_process_email_tool_is_registered():
    registered_tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in registered_tools]
    assert "process_email" in names

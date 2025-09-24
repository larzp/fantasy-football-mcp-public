#!/usr/bin/env python3
"""
Entry point for the Fantasy Football MCP Server.
This script provides a clean entry point for Claude Desktop.
"""

import sys
import os
import asyncio
from pathlib import Path

# Add the project root to the path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

if __name__ == "__main__":
    try:
        # Import the main function from the module
        import subprocess
        result = subprocess.run([
            sys.executable, "-m", "src.mcp_server"
        ], cwd=str(current_dir))
        sys.exit(result.returncode)
    except Exception as e:
        print(f"Error starting MCP server: {e}", file=sys.stderr)
        sys.exit(1)
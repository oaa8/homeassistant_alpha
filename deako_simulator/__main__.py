"""
Entry point for python -m deako_simulator execution.

Author: GitHub Copilot
Created: 2025-10-26
Last Modified: 2026-08-11
Purpose: Enable 'python -m deako_simulator' command execution

Key Assumptions:
    - All argument parsing and startup logic lives in cli.main(); this module
      stays a thin shim so that the console-script entry point declared in
      pyproject.toml and 'python -m' invocation share identical behavior.
    - cli.main() returns a process exit code rather than raising SystemExit.
"""

from __future__ import annotations

from deako_simulator.cli import main

if __name__ == "__main__":
    import sys
    sys.exit(main())

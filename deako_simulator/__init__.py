"""Deako Hub and Device Simulator.

Author: GitHub Copilot
Created: 2025-10-25
Last Modified: 2026-08-11
Purpose: Test facility for Home Assistant Deako integration without physical hardware

This package provides a telnet-based simulator that replicates the Deako hub protocol,
enabling comprehensive integration testing with validated hardware behavior.

Key Assumptions:
    - The simulator is a test facility, not a shipped product; fidelity to
      observed hardware behavior outweighs protocol elegance.
    - Every replicated quirk traces to a dated hardware validation document
      under specs/001-deako-hub-simulator/research/.
"""

from __future__ import annotations

__version__ = "0.1.0"
__author__ = "GitHub Copilot"

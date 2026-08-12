"""Pytest configuration and shared fixtures.

Author: GitHub Copilot
Created: 2025-10-25
Purpose: Common test fixtures and configuration for all tests
"""

import pytest


@pytest.fixture
def sample_device_dict():
    """Sample device dictionary for testing."""
    return {
        "uuid": "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
        "name": "Test Light",
        "capabilities": ["power", "dim"],
        "state": {"power": False, "dim": 0},
    }


@pytest.fixture
def sample_config_dict():
    """Sample configuration dictionary for testing."""
    return {
        "devices": [
            {
                "uuid": "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
                "name": "Test Light 1",
                "capabilities": ["power", "dim"],
                "state": {"power": False, "dim": 0},
            },
            {
                "uuid": "b2c3d4e5-f6a7-4890-b123-c4d5e6f7a890",
                "name": "Test Light 2",
                "capabilities": ["power"],
                "state": {"power": False, "dim": None},
            },
        ],
        "network": {
            "host": "0.0.0.0",
            "port": 23,
            "http_port": 8080,
            "mdns_name": "test-integration",
        },
        "log_level": "INFO",
    }

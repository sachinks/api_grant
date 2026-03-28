"""
conftest.py — Pytest configuration and shared fixtures.

This file is automatically loaded by pytest before running any tests.
Fixtures defined here are available to all test files without importing.

What is a fixture?
    A fixture is a reusable piece of setup data or an object that your tests
    need. Instead of repeating the same setup in every test, you define it
    once here and pytest injects it automatically.
"""

import sys
from pathlib import Path

import pytest

# Make sure the project root is on the path so tests can import our modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def sample_nih_response():
    """
    A realistic fake NIH API response with two grant records.

    Used in NIH extractor tests to avoid making real HTTP calls.
    Mirrors the actual structure returned by the NIH RePORTER API.
    """
    return {
        "meta": {"total": 2},
        "results": [
            {
                "appl_id": 12345678,
                "project_title": "Study of Neural Plasticity",
                "award_amount": 500000,
                "award_notice_date": "2025-01-10T00:00:00",
                "principal_investigators": [
                    {"first_name": "Jane", "last_name": "Smith"}
                ],
                "organization": {"org_name": "HARVARD UNIVERSITY"},
            },
            {
                "appl_id": 87654321,
                "project_title": "Cancer Immunotherapy Research",
                "award_amount": 750000,
                "award_notice_date": "2025-01-10T00:00:00",
                "principal_investigators": [
                    {"first_name": "John", "last_name": "Doe"}
                ],
                "organization": {"org_name": "MIT"},
            },
        ],
    }


@pytest.fixture
def empty_nih_response():
    """
    A valid NIH API response that contains zero records.
    Used to test that the extractor handles empty results gracefully.
    """
    return {
        "meta": {"total": 0},
        "results": [],
    }


@pytest.fixture
def malformed_nih_record():
    """
    A single NIH record with missing fields.
    Used to verify that bad records are skipped, not crashed on.
    """
    return {
        "appl_id": 99999999,
        # Missing: project_title, award_amount, principal_investigators, organization
    }

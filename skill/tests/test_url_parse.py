"""Smoke tests for URL parsing and field splitting (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from dataverse import parse_plan_url, split_fields, SCHEDULING_FIELDS  # noqa: E402


def test_parse_full_url():
    url = (
        "https://planner.cloud.microsoft/webui/premiumplan/"
        "53cfae4f-8cfb-47a7-9c22-9328595eb2b3/org/"
        "08a33ade-54b7-43cd-80e7-d7ce66b87a27/view/board"
        "?tid=72f988bf-86f1-41af-91ab-2d7cd011db47"
    )
    p = parse_plan_url(url)
    assert p["planId"] == "53cfae4f-8cfb-47a7-9c22-9328595eb2b3"
    assert p["orgId"] == "08a33ade-54b7-43cd-80e7-d7ce66b87a27"
    assert p["tenantId"] == "72f988bf-86f1-41af-91ab-2d7cd011db47"


def test_parse_url_no_tid():
    url = (
        "https://planner.cloud.microsoft/webui/premiumplan/"
        "53cfae4f-8cfb-47a7-9c22-9328595eb2b3/org/"
        "08a33ade-54b7-43cd-80e7-d7ce66b87a27/view/board"
    )
    p = parse_plan_url(url)
    assert p["planId"]
    assert p["tenantId"] is None


def test_parse_invalid():
    import pytest
    with pytest.raises(ValueError):
        parse_plan_url("https://tasks.office.com/foo/bar")


def test_split_fields_partitions_correctly():
    fields = {
        "msdyn_subject": "rename",
        "msdyn_progress": 0.5,
        "msdyn_priority": 100000001,
        "msdyn_finish": "2026-05-01T00:00:00Z",
    }
    patch, sched = split_fields(fields)
    assert "msdyn_subject" in patch
    assert "msdyn_priority" in patch
    assert "msdyn_progress" in sched
    assert "msdyn_finish" in sched
    assert set(sched.keys()).issubset(SCHEDULING_FIELDS)

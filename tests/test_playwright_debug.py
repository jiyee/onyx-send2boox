from __future__ import annotations

from send2boox.playwright_debug import (
    CapturedRequest,
    analyze_interfaces,
    extract_endpoint_candidates,
)


def test_extract_endpoint_candidates_finds_relative_and_absolute_paths() -> None:
    source = """
    const a = "/api/1/users/me";
    const b = "https://eur.boox.com/api/1/push/message?offset=0";
    const c = "/v1/internal/debug";
    const d = "https://cdn.example.com/static/app.js";
    """

    endpoints = extract_endpoint_candidates(source)

    assert "/api/1/users/me" in endpoints
    assert "https://eur.boox.com/api/1/push/message?offset=0" in endpoints
    assert "/v1/internal/debug" in endpoints
    assert "https://cdn.example.com/static/app.js" not in endpoints


def test_analyze_interfaces_merges_network_and_script_signals() -> None:
    network = [
        CapturedRequest(
            url="https://eur.boox.com/api/1/users/me",
            method="GET",
            status=200,
            resource_type="xhr",
        ),
        CapturedRequest(
            url="https://eur.boox.com/api/1/push/saveAndPush",
            method="POST",
            status=200,
            resource_type="fetch",
        ),
    ]
    script_texts = [
        """
        const listApi = "/api/1/push/message";
        const deleteApi = "https://eur.boox.com/api/1/push/message/batchDelete";
        const style = "/static/main.css";
        """
    ]

    insights = analyze_interfaces(network, script_texts)

    by_endpoint = {item.endpoint: item for item in insights}

    assert "/api/1/push/message" in by_endpoint
    assert by_endpoint["/api/1/push/message"].seen_in == {"script"}

    assert "/api/1/users/me" in by_endpoint
    assert by_endpoint["/api/1/users/me"].methods == {"GET"}
    assert by_endpoint["/api/1/users/me"].seen_in == {"network"}

    assert "/api/1/push/saveAndPush" in by_endpoint
    assert by_endpoint["/api/1/push/saveAndPush"].methods == {"POST"}
    assert by_endpoint["/api/1/push/saveAndPush"].hosts == {"eur.boox.com"}

    assert "/api/1/push/message/batchDelete" in by_endpoint
    assert by_endpoint["/api/1/push/message/batchDelete"].seen_in == {"script"}

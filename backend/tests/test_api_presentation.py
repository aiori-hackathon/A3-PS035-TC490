"""
Unit and integration tests for Phase 10 FastAPI presentation endpoints.

Validates:
- Health and readiness contracts
- Five-router topology and link health contracts
- Archived scenario snapshot catalogs
- Deterministic diagnosis endpoints
- Counterfactual verification reporting
- Safe read-only probe recommendations
- Evidence explorer query and detail endpoints
- Structured 404 error responses
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_endpoints(client: TestClient) -> None:
    res1 = client.get("/health")
    assert res1.status_code == 200
    assert res1.json()["status"] == "healthy"

    res2 = client.get("/api/v1/health")
    assert res2.status_code == 200
    assert res2.json()["service"] == "nexora-backend"


def test_readiness_endpoints(client: TestClient) -> None:
    res = client.get("/api/v1/readiness")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ready"
    assert data["data_source_mode"] == "ARCHIVED_REPLAY"
    assert data["ground_truth_isolation_active"] is True
    assert "deterministic_diagnostic_engine" in data["subsystems"]
    assert "counterfactual_verification_engine" in data["subsystems"]
    assert len(data["available_archived_scenarios"]) >= 5


def test_topology_endpoints(client: TestClient) -> None:
    # Default topology
    res = client.get("/api/v1/topology")
    assert res.status_code == 200
    data = res.json()
    assert len(data["routers"]) == 5
    assert len(data["links"]) == 5

    # Canonical topology
    res_canon = client.get("/api/v1/topology/canonical")
    assert res_canon.status_code == 200
    assert res_canon.json()["snapshot_id"] == "canonical-5-node-ring"

    # Topology status
    res_status = client.get("/api/v1/topology/status?snapshot_id=f1")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert status_data["total_routers"] == 5
    assert status_data["total_links"] == 5
    assert "L12" in status_data["link_statuses"]
    assert status_data["link_statuses"]["L12"] == "DOWN"

    # Routers list & detail
    res_routers = client.get("/api/v1/topology/routers")
    assert res_routers.status_code == 200
    assert len(res_routers.json()) == 5

    res_r1 = client.get("/api/v1/topology/routers/R1")
    assert res_r1.status_code == 200
    assert res_r1.json()["router"]["router_id"] == "R1"
    assert "eth1" in [i["interface_name"] for i in res_r1.json()["router"]["interfaces"]]

    res_r_none = client.get("/api/v1/topology/routers/R99")
    assert res_r_none.status_code == 404

    # Links list & detail
    res_links = client.get("/api/v1/topology/links")
    assert res_links.status_code == 200
    assert len(res_links.json()) == 5

    res_l12 = client.get("/api/v1/topology/links/L12")
    assert res_l12.status_code == 200
    assert res_l12.json()["link"]["link_id"] == "L12"

    res_l_none = client.get("/api/v1/topology/links/L99")
    assert res_l_none.status_code == 404


def test_snapshots_catalog(client: TestClient) -> None:
    res = client.get("/api/v1/snapshots")
    assert res.status_code == 200
    items = res.json()
    assert len(items) >= 5
    scenario_keys = {item["scenario_key"] for item in items}
    assert "baseline" in scenario_keys or "BASELINE" in scenario_keys
    assert "F1" in scenario_keys

    # Get specific snapshot
    f1_item = next(it for it in items if it["scenario_key"] == "F1")
    res_snap = client.get(f"/api/v1/snapshots/{f1_item['snapshot_id']}")
    assert res_snap.status_code == 200
    snap_data = res_snap.json()
    assert len(snap_data["evidence_records"]) > 0

    # 404 test
    res_none = client.get("/api/v1/snapshots/nonexistent-snap-id")
    assert res_none.status_code == 404


def test_incidents_endpoints(client: TestClient) -> None:
    res = client.get("/api/v1/incidents")
    assert res.status_code == 200
    incidents = res.json()
    assert len(incidents) >= 5

    first = incidents[0]
    res_inc = client.get(f"/api/v1/incidents/{first['incident_id']}")
    assert res_inc.status_code == 200
    assert res_inc.json()["incident_id"] == first["incident_id"]

    res_none = client.get("/api/v1/incidents/nonexistent-inc-id")
    assert res_none.status_code == 404


def test_diagnosis_endpoints(client: TestClient) -> None:
    res = client.get("/api/v1/diagnosis")
    assert res.status_code == 200
    diagnoses = res.json()
    assert len(diagnoses) >= 5

    # Check F1 diagnosis
    f1_inc = next((d for d in diagnoses if d["top1_hypothesis"] and d["top1_hypothesis"]["fault_location"]["component_id"] == "L12"), None)
    assert f1_inc is not None
    assert f1_inc["top1_hypothesis"]["fault_type"] == "LINK_FAILURE"

    # Single diagnosis endpoint
    res_diag = client.get(f"/api/v1/diagnosis/{f1_inc['incident_id']}")
    assert res_diag.status_code == 200
    assert res_diag.json()["evidence_certificate"]["evidence_sufficiency_met"] is True

    # Hypotheses endpoint
    res_hyps = client.get(f"/api/v1/diagnosis/{f1_inc['incident_id']}/hypotheses")
    assert res_hyps.status_code == 200
    assert len(res_hyps.json()) >= 1

    res_none = client.get("/api/v1/diagnosis/nonexistent-inc-id")
    assert res_none.status_code == 404


def test_verification_endpoints(client: TestClient) -> None:
    res = client.get("/api/v1/verification")
    assert res.status_code == 200
    reports = res.json()
    assert len(reports) >= 5

    first = reports[0]
    res_verif = client.get(f"/api/v1/verification/{first['incident_id']}")
    assert res_verif.status_code == 200
    data = res_verif.json()
    assert "top_hypotheses_verifications" in data

    res_none = client.get("/api/v1/verification/nonexistent-inc-id")
    assert res_none.status_code == 404


def test_probes_endpoints(client: TestClient) -> None:
    res = client.get("/api/v1/probes/recommendations")
    assert res.status_code == 200
    plans = res.json()
    assert len(plans) >= 5
    for p in plans:
        assert p["execution_permitted"] is False
        assert p["safety_guardrail"] == "STRICT_READ_ONLY_GUARDED"

    first = plans[0]
    res_single = client.get(f"/api/v1/probes/recommendations/{first['incident_id']}")
    assert res_single.status_code == 200
    assert res_single.json()["incident_id"] == first["incident_id"]

    res_none = client.get("/api/v1/probes/recommendations/nonexistent-inc-id")
    assert res_none.status_code == 404


def test_evidence_endpoints(client: TestClient) -> None:
    res = client.get("/api/v1/evidence?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] > 0
    assert len(data["items"]) == 10

    # Filter by router
    res_r1 = client.get("/api/v1/evidence?router_id=R1&limit=5")
    assert res_r1.status_code == 200
    for it in res_r1.json()["items"]:
        assert it["source_router"] == "R1"

    # Single evidence item
    first_ev = data["items"][0]
    res_single = client.get(f"/api/v1/evidence/{first_ev['evidence_id']}")
    assert res_single.status_code == 200
    assert res_single.json()["evidence_id"] == first_ev["evidence_id"]

    res_none = client.get("/api/v1/evidence/nonexistent-ev-id")
    assert res_none.status_code == 404

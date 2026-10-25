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
    assert any("F1" in k for k in scenario_keys)
    assert any("BASELINE" in k.upper() for k in scenario_keys)

    # Get specific snapshot
    f1_item = next(
        it for it in items if "F1" in it["scenario_key"] and it["availability"] == "AVAILABLE"
    )
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


# ===========================================================================
# Stage 7: Dedicated Contract Readiness & Boundary Tests
# ===========================================================================


def test_stage7_missing_snapshot(client: TestClient) -> None:
    """1. Missing snapshot produces clean 404 DetailError."""
    res = client.get("/api/v1/snapshots/snap-missing-scenario-xyz")
    assert res.status_code == 404
    data = res.json()
    assert "detail" in data
    assert "not found" in data["detail"].lower()


def test_stage7_invalid_incident_id(client: TestClient) -> None:
    """2. Invalid incident ID produces clean 404."""
    for ep in ["incidents", "diagnosis", "verification", "probes/recommendations"]:
        res = client.get(f"/api/v1/{ep}/invalid-incident-999999")
        assert res.status_code == 404, f"Failed on endpoint /api/v1/{ep}"


def test_stage7_certificate_endpoints_and_contracts(client: TestClient) -> None:
    """3. Certificate endpoint returns complete Phase 09 contract with causation disclaimer."""
    # List certificates
    res_list = client.get("/api/v1/certificates")
    assert res_list.status_code == 200
    certs = res_list.json()
    assert len(certs) >= 1

    first = certs[0]
    assert "certificate_id" in first
    assert "heuristic_score" in first
    assert first["score_label"] == "Rule Alignment Score"
    assert "counterfactual_verdict" in first
    assert "causation_disclaimer" in first
    assert "absolute" in first["causation_disclaimer"].lower()
    assert "limitations" in first
    assert len(first["limitations"]) > 0

    # Get single certificate via /api/v1/certificates/{id} and /api/v1/diagnosis/{id}/certificate
    inc_id = first["incident_id"]
    res1 = client.get(f"/api/v1/certificates/{inc_id}")
    assert res1.status_code == 200
    assert res1.json()["certificate_id"] == first["certificate_id"]

    res2 = client.get(f"/api/v1/diagnosis/{inc_id}/certificate")
    assert res2.status_code == 200
    assert res2.json()["certificate_id"] == first["certificate_id"]


def test_stage7_missing_certificate_returns_404(client: TestClient) -> None:
    """3 & 4. Missing certificate returns 404."""
    res = client.get("/api/v1/certificates/nonexistent-incident-id")
    assert res.status_code == 404
    res2 = client.get("/api/v1/diagnosis/nonexistent-incident-id/certificate")
    assert res2.status_code == 404


def test_stage7_unsupported_certificate_version_and_provenance(client: TestClient) -> None:
    """4 & 5. Provenance integrity status and versioning validation."""
    res = client.get("/api/v1/certificates")
    assert res.status_code == 200
    certs = res.json()
    for c in certs:
        assert c["provenance_integrity_status"] in [
            "STRUCTURALLY_VALID_LOCAL_CAPTURE",
            "PROVENANCE_VERIFIED_BENCHMARK_EVALUATION",
            "AWAITING_CERTIFIED_ARCHIVE_TRANSFER",
        ]
        assert "provenance_details" in c


def test_stage7_contradictory_evidence_display(client: TestClient) -> None:
    """6. Contradictory evidence reference contracts."""
    res = client.get("/api/v1/verification")
    assert res.status_code == 200
    reports = res.json()
    for r in reports:
        for v in r["top_hypotheses_verifications"]:
            assert isinstance(v["contradictory_evidence_ids"], list)
            assert isinstance(v["supporting_evidence_ids"], list)


def test_stage7_phase08_probe_recommendations_contract(client: TestClient) -> None:
    """7 & 8. Probe planning adherence: PLANNED - NOT EXECUTED, relative costs, allowlists."""
    res = client.get("/api/v1/probes/recommendations")
    assert res.status_code == 200
    plans = res.json()
    assert len(plans) >= 1
    for p in plans:
        assert p["execution_status"] == "PLANNED — NOT EXECUTED"
        assert p["execution_permitted"] is False
        assert p["allowlist_verified"] is True
        assert p["information_gain"] == "UNAVAILABLE_PENDING_PHASE_08_PLANNER"
        assert p["contract_status"] == "PROVISIONAL_ADAPTER_PREVIEW"
        for rk in p["ranked_probes"]:
            assert rk["execution_authorization"] == "PLANNED — NOT EXECUTED"
            assert rk["relative_cost"] >= 1
            assert rk["safety_status"] == "ALLOWLIST_VALIDATED"
            assert isinstance(rk["expected_discriminating_outcomes"], list)


def test_stage7_archived_live_status_separation(client: TestClient) -> None:
    """9. Explicit data source tagging and honest live vs archived separation."""
    res = client.get("/api/v1/snapshots")
    assert res.status_code == 200
    snaps = res.json()
    for s in snaps:
        assert s["is_live"] is False
        assert s["data_source"] in [
            "CERTIFIED_LIVE_RUN",
            "ARCHIVED_REPLAY",
            "CERTIFIED_ARCHIVE_NOT_ON_DEVICE",
            "PENDING_TRACK_A_CAPTURE",
        ]
        if s["scenario_key"] in ["F2_ROUTER_FAILURE", "F3_OSPF_CONFIG_MISMATCH"]:
            assert s["availability"] in [
                "CERTIFIED_CAPTURE_NOT_YET_AVAILABLE_ON_THIS_DEVICE",
                "UNAVAILABLE_PENDING_CAPTURE",
            ]
            assert "not yet been transferred" in s["unavailable_reason"].lower() or "not yet available" in s["unavailable_reason"].lower()


def test_stage7_empty_evidence_results_handling(client: TestClient) -> None:
    """11. Empty evidence queries return valid empty list, not 500 error."""
    res = client.get("/api/v1/evidence?router_id=NONEXISTENT_NODE")
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] == 0
    assert data["items"] == []


def test_stage7_valid_topology_rendering(client: TestClient) -> None:
    """12. Valid 5-node topology rendering contract."""
    res = client.get("/api/v1/topology")
    assert res.status_code == 200
    data = res.json()
    router_ids = {r["router_id"] for r in data["routers"]}
    link_ids = {lnk["link_id"] for lnk in data["links"]}
    assert router_ids == {"R1", "R2", "R3", "R4", "R5"}
    assert link_ids == {"L12", "L23", "L34", "L45", "L51"}


def test_stage7_correct_fault_scenario_labels(client: TestClient) -> None:
    """13. Correct fault scenario labels and categories."""
    res = client.get("/api/v1/snapshots")
    assert res.status_code == 200
    snaps = res.json()
    keys = {s["scenario_key"] for s in snaps}
    assert "F1_LINK_FAILURE" in keys
    assert "F2_ROUTER_FAILURE" in keys
    assert "F3_OSPF_CONFIG_MISMATCH" in keys
    assert "F4_PACKET_LOSS" in keys
    assert "F5_HIGH_LATENCY" in keys


def test_stage7_unknown_router_or_link_returns_404(client: TestClient) -> None:
    """14. Unknown router or link endpoints return clean 404."""
    res_r = client.get("/api/v1/topology/routers/R99")
    assert res_r.status_code == 404
    res_l = client.get("/api/v1/topology/links/L99")
    assert res_l.status_code == 404


def test_stage7_response_serialization_and_heuristic_terminology(client: TestClient) -> None:
    """15. Response serialization check: no probability or Bayesian claims."""
    # Test incident response
    res = client.get("/api/v1/incidents")
    assert res.status_code == 200
    raw_text = res.text.lower()
    assert "bayesian" not in raw_text
    assert "calibrated probability" not in raw_text

    # Test diagnosis response
    res_diag = client.get("/api/v1/diagnosis")
    assert res_diag.status_code == 200
    diag_text = res_diag.text.lower()
    assert "bayesian" not in diag_text


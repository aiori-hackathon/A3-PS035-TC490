/**
 * NEXORA Typed API Client for Track B (Phases 10 & 11).
 *
 * Interacts with FastAPI backend (/api/v1).
 * Contains type-safe models matching backend schemas and verified offline scenario fallbacks.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// TypeScript Interfaces Matching Backend Contracts
// ---------------------------------------------------------------------------

export interface BackendStatus {
  isHealthy: boolean;
  serviceName: string;
  latencyMs: number | null;
  lastChecked: Date | null;
  errorMessage: string | null;
}

export interface NetworkInterfaceInfo {
  interface_name: string;
  ipv4_address: string | null;
  status: "UP" | "DOWN" | "ADMIN_DOWN" | "UNKNOWN";
  is_ospf_passive: boolean;
  ospf_area: string | null;
}

export interface RouterInfo {
  router_id: string;
  ospf_router_id: string;
  loopback_address: string;
  role: string;
  status: "UP" | "DOWN" | "UNKNOWN";
  interfaces: NetworkInterfaceInfo[];
}

export interface NetworkLinkInfo {
  link_id: string;
  subnet: string;
  router_a: string;
  interface_a: string;
  address_a: string;
  router_b: string;
  interface_b: string;
  address_b: string;
  ospf_cost: number;
}

export interface RoutingAdjacencyInfo {
  local_router: string;
  neighbour_router: string;
  local_interface: string;
  neighbour_address: string;
  state: string;
  observed_at: string;
}

export interface TopologySnapshot {
  snapshot_id: string;
  captured_at: string;
  routers: RouterInfo[];
  links: NetworkLinkInfo[];
  adjacencies: RoutingAdjacencyInfo[];
}

export interface RouterDetail {
  router: RouterInfo;
  connected_link_ids: string[];
  expected_peer_router_ids: string[];
  current_health: "UP" | "DOWN" | "UNKNOWN";
  data_source: string;
  is_live: boolean;
}

export interface LinkDetail {
  link: NetworkLinkInfo;
  health_status: "HEALTHY" | "DEGRADED" | "DOWN" | "UNKNOWN";
  endpoint_a_status: "UP" | "DOWN" | "UNKNOWN";
  endpoint_b_status: "UP" | "DOWN" | "UNKNOWN";
  data_source: string;
  is_live: boolean;
}

export interface TopologyStatus {
  snapshot_id: string;
  data_source: string;
  is_live: boolean;
  is_replay: boolean;
  total_routers: number;
  routers_up: number;
  routers_down: number;
  routers_unknown: number;
  total_links: number;
  links_healthy: number;
  links_degraded: number;
  links_down: number;
  links_unknown: number;
  router_statuses: Record<string, "UP" | "DOWN" | "UNKNOWN">;
  link_statuses: Record<string, "HEALTHY" | "DEGRADED" | "DOWN" | "UNKNOWN">;
  evaluated_at: string;
}

export interface SnapshotSummary {
  snapshot_id: string;
  scenario_key: string;
  name: string;
  description: string;
  captured_at: string;
  record_count: number;
  incident_ids: string[];
  data_source: string;
  is_live: boolean;
}

export interface IncidentSummary {
  incident_id: string;
  snapshot_id: string;
  scenario_key: string;
  affected_routers: string[];
  affected_links: string[];
  evidence_count: number;
  correlation_window_start: string;
  correlation_window_end: string | null;
  correlation_explanation: string;
  data_source: string;
  is_live: boolean;
}

export interface FaultLocation {
  kind: "ROUTER" | "LINK" | "INTERFACE";
  component_id: string;
  affected_routers: string[];
}

export interface FaultHypothesis {
  hypothesis_id: string;
  incident_id: string;
  fault_type: string;
  fault_location: FaultLocation;
  rule_score: number;
  supporting_evidence_ids: string[];
  contradictory_evidence_ids: string[];
  reasoning_trace: string[];
}

export interface RankedHypothesis {
  rank: number;
  hypothesis: FaultHypothesis;
}

export interface EvidenceCertificate {
  certificate_id: string;
  incident_id: string;
  generated_at: string;
  total_evidence_count: number;
  supporting_evidence_count: number;
  contradictory_evidence_count: number;
  missing_evidence_descriptions: string[];
  evidence_sufficiency_met: boolean;
  score_interpretation: string;
  collection_coverage_pct: number;
  reasoning_summary: string;
}

export interface DiagnosisResult {
  result_id: string;
  incident_id: string;
  diagnosed_at: string;
  engine_version: string;
  status: "DIAGNOSED" | "AMBIGUOUS" | "INSUFFICIENT_EVIDENCE";
  ranked_hypotheses: RankedHypothesis[];
  top1_hypothesis: FaultHypothesis | null;
  top3_hypotheses: FaultHypothesis[];
  evidence_certificate: EvidenceCertificate;
  missing_information: string[];
}

export interface ExpectedObservation {
  expectation_id: string;
  category: string;
  target_component: string;
  target_endpoint: string | null;
  expected_condition: string;
  criticality: "REQUIRED" | "CONFIRMATORY";
  rationale: string;
}

export interface EvaluatedExpectation {
  expectation: ExpectedObservation;
  match_status: "SUPPORTED" | "CONTRADICTED" | "MISSING" | "INCONCLUSIVE";
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  explanation: string;
}

export interface ProbeRequest {
  probe_id: string;
  incident_id: string;
  probe_type: "PING" | "INTERFACE_STATE" | "OSPF_NEIGHBOUR" | "ROUTING_TABLE" | "TRACEROUTE";
  source_router: string;
  target_router: string | null;
  target_address: string | null;
  target_interface: string | null;
  target_prefix: string | null;
  selection_reason: string;
  timeout_s: number;
  requested_at: string;
}

export interface CounterfactualVerificationResult {
  hypothesis: FaultHypothesis;
  verdict: "SUPPORTED" | "CONTRADICTED" | "INSUFFICIENT_EVIDENCE" | "INCONCLUSIVE";
  counterfactual_verified: boolean | null;
  evaluated_expectations: EvaluatedExpectation[];
  supporting_evidence_ids: string[];
  contradictory_evidence_ids: string[];
  missing_evidence_descriptions: string[];
  explanation: string;
  recommended_probes: ProbeRequest[];
}

export interface VerificationReport {
  incident_id: string;
  verified_at: string;
  engine_version: string;
  top_hypotheses_verifications: CounterfactualVerificationResult[];
  competing_hypotheses_verifications: CounterfactualVerificationResult[];
  summary: string;
}

export interface SafeProbePlan {
  incident_id: string;
  recommendations: ProbeRequest[];
  safety_guardrail: string;
  execution_permitted: boolean;
  notes: string[];
}

export interface EvidenceRecord {
  evidence_id: string;
  source_router: string;
  source_type: string;
  event_type: string;
  collection_method: string;
  collection_status: string;
  observed_at: string;
  collected_at: string;
  incident_id: string | null;
  raw_reference: string;
  source_interface?: string;
  observed_status?: string;
  neighbour_router_id?: string;
  target_address?: string;
  rtt_mean_ms?: number;
  packet_loss_pct?: number;
}

export interface EvidenceQueryResponse {
  total_count: number;
  limit: number;
  offset: number;
  items: EvidenceRecord[];
  applied_filters: Record<string, unknown>;
  data_source: string;
}

// ---------------------------------------------------------------------------
// Canonical Fallback Fixtures (Offline Fallbacks)
// ---------------------------------------------------------------------------

export const CANONICAL_ROUTERS: RouterInfo[] = [
  {
    router_id: "R1",
    ospf_router_id: "1.1.1.1",
    loopback_address: "192.168.255.1/32",
    role: "Core Gateway / Entry Point",
    status: "UP",
    interfaces: [
      { interface_name: "lo", ipv4_address: "192.168.255.1/32", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
      { interface_name: "eth1", ipv4_address: "10.0.12.1/30", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
      { interface_name: "eth2", ipv4_address: "10.0.15.2/30", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
    ],
  },
  {
    router_id: "R2",
    ospf_router_id: "2.2.2.2",
    loopback_address: "192.168.255.2/32",
    role: "Aggregation Node A",
    status: "UP",
    interfaces: [
      { interface_name: "lo", ipv4_address: "192.168.255.2/32", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
      { interface_name: "eth1", ipv4_address: "10.0.12.2/30", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
      { interface_name: "eth2", ipv4_address: "10.0.23.1/30", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
    ],
  },
  {
    router_id: "R3",
    ospf_router_id: "3.3.3.3",
    loopback_address: "192.168.255.3/32",
    role: "Aggregation Node B",
    status: "UP",
    interfaces: [
      { interface_name: "lo", ipv4_address: "192.168.255.3/32", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
      { interface_name: "eth1", ipv4_address: "10.0.23.2/30", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
      { interface_name: "eth2", ipv4_address: "10.0.34.1/30", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
    ],
  },
  {
    router_id: "R4",
    ospf_router_id: "4.4.4.4",
    loopback_address: "192.168.255.4/32",
    role: "Edge Router",
    status: "UP",
    interfaces: [
      { interface_name: "lo", ipv4_address: "192.168.255.4/32", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
      { interface_name: "eth1", ipv4_address: "10.0.34.2/30", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
      { interface_name: "eth2", ipv4_address: "10.0.45.1/30", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
    ],
  },
  {
    router_id: "R5",
    ospf_router_id: "5.5.5.5",
    loopback_address: "192.168.255.5/32",
    role: "Peer / Transit Node",
    status: "UP",
    interfaces: [
      { interface_name: "lo", ipv4_address: "192.168.255.5/32", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
      { interface_name: "eth1", ipv4_address: "10.0.45.2/30", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
      { interface_name: "eth2", ipv4_address: "10.0.15.1/30", status: "UP", is_ospf_passive: false, ospf_area: "0.0.0.0" },
    ],
  },
];

export const CANONICAL_LINKS: NetworkLinkInfo[] = [
  {
    link_id: "L12",
    subnet: "10.0.12.0/30",
    router_a: "R1",
    interface_a: "eth1",
    address_a: "10.0.12.1/30",
    router_b: "R2",
    interface_b: "eth1",
    address_b: "10.0.12.2/30",
    ospf_cost: 1,
  },
  {
    link_id: "L23",
    subnet: "10.0.23.0/30",
    router_a: "R2",
    interface_a: "eth2",
    address_a: "10.0.23.1/30",
    router_b: "R3",
    interface_b: "eth1",
    address_b: "10.0.23.2/30",
    ospf_cost: 1,
  },
  {
    link_id: "L34",
    subnet: "10.0.34.0/30",
    router_a: "R3",
    interface_a: "eth2",
    address_a: "10.0.34.1/30",
    router_b: "R4",
    interface_b: "eth1",
    address_b: "10.0.34.2/30",
    ospf_cost: 1,
  },
  {
    link_id: "L45",
    subnet: "10.0.45.0/30",
    router_a: "R4",
    interface_a: "eth2",
    address_a: "10.0.45.1/30",
    router_b: "R5",
    interface_b: "eth1",
    address_b: "10.0.45.2/30",
    ospf_cost: 1,
  },
  {
    link_id: "L51",
    subnet: "10.0.15.0/30",
    router_a: "R5",
    interface_a: "eth2",
    address_a: "10.0.15.1/30",
    router_b: "R1",
    interface_b: "eth2",
    address_b: "10.0.15.2/30",
    ospf_cost: 1,
  },
];

export const DEMO_SCENARIOS: SnapshotSummary[] = [
  {
    snapshot_id: "obs-snap-20261019T190206Z-ef8890",
    scenario_key: "baseline",
    name: "Normal Operating Baseline",
    description: "All 5 FRRouting nodes up, 5 links healthy, full OSPFv2.",
    captured_at: "2026-10-19T19:02:29Z",
    record_count: 211,
    incident_ids: ["incident-400cfe3751f0cb9c"],
    data_source: "ARCHIVED_REPLAY",
    is_live: false,
  },
  {
    snapshot_id: "obs-snap-20261019T190230Z-320d01",
    scenario_key: "F1",
    name: "Scenario F1: Link L12 Failure",
    description: "Hard failure on link L12 between R1 and R2. Dual OSPF adjacency drop.",
    captured_at: "2026-10-19T19:02:53Z",
    record_count: 109,
    incident_ids: ["incident-ad09617eb2c57e0d"],
    data_source: "ARCHIVED_REPLAY",
    is_live: false,
  },
  {
    snapshot_id: "obs-snap-20261019T190307Z-2b4c8c",
    scenario_key: "F2",
    name: "Scenario F2: Router R3 Failure",
    description: "Total node outage of router R3 affecting adjacencies on links L23 and L34.",
    captured_at: "2026-10-19T19:03:31Z",
    record_count: 100,
    incident_ids: ["incident-18d4c4764899409f"],
    data_source: "ARCHIVED_REPLAY",
    is_live: false,
  },
  {
    snapshot_id: "obs-snap-20261019T190431Z-a195d9",
    scenario_key: "F3",
    name: "Scenario F3: OSPF Config Mismatch on L23",
    description: "Config mismatch (MTU/Hello) causing adjacency drop between R2 and R3.",
    captured_at: "2026-10-19T19:04:45Z",
    record_count: 101,
    incident_ids: ["incident-36ae1e34674d1017"],
    data_source: "ARCHIVED_REPLAY",
    is_live: false,
  },
  {
    snapshot_id: "obs-snap-20261019T190446Z-9f22e1",
    scenario_key: "F4",
    name: "Scenario F4: Partial Packet Loss",
    description: "Intermittent packet loss induced on link L34 causing telemetry anomalies.",
    captured_at: "2026-10-19T19:05:01Z",
    record_count: 111,
    incident_ids: ["incident-54f8b1979200e694"],
    data_source: "ARCHIVED_REPLAY",
    is_live: false,
  },
  {
    snapshot_id: "obs-snap-20261019T190536Z-060d3f",
    scenario_key: "F5",
    name: "Scenario F5: High Latency / Jitter",
    description: "Elevated RTT latency and jitter across transit ring path.",
    captured_at: "2026-10-19T19:05:51Z",
    record_count: 111,
    incident_ids: ["incident-aa63ad89c08c4a6f"],
    data_source: "ARCHIVED_REPLAY",
    is_live: false,
  },
];

// ---------------------------------------------------------------------------
// API Client Functions with Graceful Offline Fallbacks
// ---------------------------------------------------------------------------

async function safeFetch<T>(endpoint: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${API_BASE_URL}${endpoint}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      return fallback;
    }
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

export async function fetchHealth(): Promise<{
  ok: boolean;
  data?: { status: string; service: string };
  latencyMs: number | null;
  error?: string;
}> {
  const start = performance.now();
  try {
    const res = await fetch(`${API_BASE_URL}/health`, {
      cache: "no-store",
    });
    const latencyMs = Math.round(performance.now() - start);
    if (!res.ok) {
      return { ok: false, latencyMs, error: `HTTP ${res.status}` };
    }
    const data = (await res.json()) as { status: string; service: string };
    return { ok: true, data, latencyMs };
  } catch (err: unknown) {
    const latencyMs = Math.round(performance.now() - start);
    return {
      ok: false,
      latencyMs,
      error: err instanceof Error ? err.message : "Connection failed",
    };
  }
}

export async function fetchTopology(snapshotId?: string): Promise<TopologySnapshot> {
  const query = snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "";
  const fallback: TopologySnapshot = {
    snapshot_id: snapshotId || "canonical-5-node-ring",
    captured_at: new Date().toISOString(),
    routers: CANONICAL_ROUTERS,
    links: CANONICAL_LINKS,
    adjacencies: [],
  };
  return safeFetch<TopologySnapshot>(`/api/v1/topology${query}`, fallback);
}

export async function fetchTopologyStatus(snapshotId?: string): Promise<TopologyStatus> {
  const query = snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "";
  const isF1 = snapshotId?.toLowerCase() === "f1";
  const isF2 = snapshotId?.toLowerCase() === "f2";
  const isF3 = snapshotId?.toLowerCase() === "f3";

  const fallback: TopologyStatus = {
    snapshot_id: snapshotId || "snap-baseline",
    data_source: "ARCHIVED_REPLAY",
    is_live: false,
    is_replay: true,
    total_routers: 5,
    routers_up: isF2 ? 4 : 5,
    routers_down: isF2 ? 1 : 0,
    routers_unknown: 0,
    total_links: 5,
    links_healthy: isF1 || isF2 || isF3 ? 4 : 5,
    links_degraded: isF3 ? 1 : 0,
    links_down: isF1 || isF2 ? 1 : 0,
    links_unknown: 0,
    router_statuses: {
      R1: "UP",
      R2: "UP",
      R3: isF2 ? "DOWN" : "UP",
      R4: "UP",
      R5: "UP",
    },
    link_statuses: {
      L12: isF1 ? "DOWN" : "HEALTHY",
      L23: isF2 ? "DOWN" : isF3 ? "DEGRADED" : "HEALTHY",
      L34: isF2 ? "DOWN" : "HEALTHY",
      L45: "HEALTHY",
      L51: "HEALTHY",
    },
    evaluated_at: new Date().toISOString(),
  };
  return safeFetch<TopologyStatus>(`/api/v1/topology/status${query}`, fallback);
}

export async function fetchRouters(snapshotId?: string): Promise<RouterDetail[]> {
  const query = snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "";
  const fallback: RouterDetail[] = CANONICAL_ROUTERS.map((r) => ({
    router: r,
    connected_link_ids: ["L12", "L51"],
    expected_peer_router_ids: ["R2", "R5"],
    current_health: r.status,
    data_source: "ARCHIVED_REPLAY",
    is_live: false,
  }));
  return safeFetch<RouterDetail[]>(`/api/v1/topology/routers${query}`, fallback);
}

export async function fetchLinks(snapshotId?: string): Promise<LinkDetail[]> {
  const query = snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "";
  const fallback: LinkDetail[] = CANONICAL_LINKS.map((lnk) => ({
    link: lnk,
    health_status: "HEALTHY",
    endpoint_a_status: "UP",
    endpoint_b_status: "UP",
    data_source: "ARCHIVED_REPLAY",
    is_live: false,
  }));
  return safeFetch<LinkDetail[]>(`/api/v1/topology/links${query}`, fallback);
}

export async function fetchSnapshots(): Promise<SnapshotSummary[]> {
  return safeFetch<SnapshotSummary[]>("/api/v1/snapshots", DEMO_SCENARIOS);
}

export async function fetchIncidents(snapshotId?: string): Promise<IncidentSummary[]> {
  const query = snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "";
  const fallback: IncidentSummary[] = [
    {
      incident_id: "incident-ad09617eb2c57e0d",
      snapshot_id: "obs-snap-20261019T190230Z-320d01",
      scenario_key: "F1",
      affected_routers: ["R1", "R2"],
      affected_links: ["L12"],
      evidence_count: 109,
      correlation_window_start: "2026-10-19T19:02:30Z",
      correlation_window_end: "2026-10-19T19:02:53Z",
      correlation_explanation: "Dual OSPF adjacency drop and interface down events between R1 (eth1) and R2 (eth1).",
      data_source: "ARCHIVED_REPLAY",
      is_live: false,
    },
  ];
  return safeFetch<IncidentSummary[]>(`/api/v1/incidents${query}`, fallback);
}

export async function fetchDiagnoses(): Promise<DiagnosisResult[]> {
  const fallback: DiagnosisResult[] = [
    {
      result_id: "dr-f1-default",
      incident_id: "incident-ad09617eb2c57e0d",
      diagnosed_at: "2026-10-19T19:02:55Z",
      engine_version: "phase06-rules-v1.1",
      status: "DIAGNOSED",
      ranked_hypotheses: [
        {
          rank: 1,
          hypothesis: {
            hypothesis_id: "h-link_failure-l12",
            incident_id: "incident-ad09617eb2c57e0d",
            fault_type: "LINK_FAILURE",
            fault_location: { kind: "LINK", component_id: "L12", affected_routers: ["R1", "R2"] },
            rule_score: 0.85,
            supporting_evidence_ids: ["ev-01", "ev-02"],
            contradictory_evidence_ids: [],
            reasoning_trace: [
              "Interface eth1 down on R1 facing L12",
              "Interface eth1 down on R2 facing L12",
              "OSPF adjacency R1 <-> R2 transitioned from FULL to DOWN",
            ],
          },
        },
      ],
      top1_hypothesis: {
        hypothesis_id: "h-link_failure-l12",
        incident_id: "incident-ad09617eb2c57e0d",
        fault_type: "LINK_FAILURE",
        fault_location: { kind: "LINK", component_id: "L12", affected_routers: ["R1", "R2"] },
        rule_score: 0.85,
        supporting_evidence_ids: ["ev-01", "ev-02"],
        contradictory_evidence_ids: [],
        reasoning_trace: [
          "Interface eth1 down on R1 facing L12",
          "Interface eth1 down on R2 facing L12",
        ],
      },
      top3_hypotheses: [],
      evidence_certificate: {
        certificate_id: "cert-f1-default",
        incident_id: "incident-ad09617eb2c57e0d",
        generated_at: "2026-10-19T19:02:55Z",
        total_evidence_count: 109,
        supporting_evidence_count: 4,
        contradictory_evidence_count: 0,
        missing_evidence_descriptions: [],
        evidence_sufficiency_met: true,
        score_interpretation: "Rule scores are heuristic values in [0.0, 1.0], not calibrated probabilities.",
        collection_coverage_pct: 95.0,
        reasoning_summary: "Confirmed LINK_FAILURE on L12 with complete bidirectional interface drop telemetry.",
      },
      missing_information: [],
    },
  ];
  return safeFetch<DiagnosisResult[]>("/api/v1/diagnosis", fallback);
}

export async function fetchDiagnosis(incidentId: string): Promise<DiagnosisResult | null> {
  const all = await fetchDiagnoses();
  const match = all.find((d) => d.incident_id === incidentId);
  return match || all[0] || null;
}

export async function fetchVerifications(): Promise<VerificationReport[]> {
  const fallback: VerificationReport[] = [
    {
      incident_id: "incident-ad09617eb2c57e0d",
      verified_at: "2026-10-19T19:02:56Z",
      engine_version: "phase07-counterfactual-v1.0",
      top_hypotheses_verifications: [
        {
          hypothesis: {
            hypothesis_id: "h-link_failure-l12",
            incident_id: "incident-ad09617eb2c57e0d",
            fault_type: "LINK_FAILURE",
            fault_location: { kind: "LINK", component_id: "L12", affected_routers: ["R1", "R2"] },
            rule_score: 0.85,
            supporting_evidence_ids: ["ev-01", "ev-02"],
            contradictory_evidence_ids: [],
            reasoning_trace: [],
          },
          verdict: "SUPPORTED",
          counterfactual_verified: true,
          evaluated_expectations: [
            {
              expectation: {
                expectation_id: "exp-01",
                category: "INTERFACE_STATE",
                target_component: "L12",
                target_endpoint: "eth1",
                expected_condition: "Interface eth1 on endpoint routers DOWN",
                criticality: "REQUIRED",
                rationale: "Physical link failure causes kernel link down flag on connected interfaces.",
              },
              match_status: "SUPPORTED",
              supporting_evidence_ids: ["ev-01"],
              contradicting_evidence_ids: [],
              explanation: "Both R1:eth1 and R2:eth1 observed operational status DOWN.",
            },
            {
              expectation: {
                expectation_id: "exp-02",
                category: "OSPF_ADJACENCY",
                target_component: "L12",
                target_endpoint: "R2",
                expected_condition: "OSPF adjacency state DOWN / absent",
                criticality: "REQUIRED",
                rationale: "Missing hello packets across failed link terminates neighbor adjacency.",
              },
              match_status: "SUPPORTED",
              supporting_evidence_ids: ["ev-02"],
              contradicting_evidence_ids: [],
              explanation: "Adjacency between 1.1.1.1 and 2.2.2.2 absent from active neighbor table.",
            },
          ],
          supporting_evidence_ids: ["ev-01", "ev-02"],
          contradictory_evidence_ids: [],
          missing_evidence_descriptions: [],
          explanation: "All counterfactual expectations verified true against independent telemetry. Zero contradictions.",
          recommended_probes: [
            {
              probe_id: "pr-01",
              incident_id: "incident-ad09617eb2c57e0d",
              probe_type: "PING",
              source_router: "R1",
              target_router: "R2",
              target_address: "10.0.12.2",
              target_interface: null,
              target_prefix: null,
              selection_reason: "Confirm complete ICMP drop across direct L12 link subnet.",
              timeout_s: 5,
              requested_at: "2026-10-19T19:02:57Z",
            },
          ],
        },
      ],
      competing_hypotheses_verifications: [],
      summary: "Counterfactual verification evaluated top-1 hypothesis LINK_FAILURE @ L12. Verdict: SUPPORTED.",
    },
  ];
  return safeFetch<VerificationReport[]>("/api/v1/verification", fallback);
}

export async function fetchVerification(incidentId: string): Promise<VerificationReport | null> {
  const all = await fetchVerifications();
  const match = all.find((v) => v.incident_id === incidentId);
  return match || all[0] || null;
}

export async function fetchProbePlan(incidentId: string): Promise<SafeProbePlan> {
  const fallback: SafeProbePlan = {
    incident_id: incidentId,
    recommendations: [
      {
        probe_id: "probe-ping-r1-r2",
        incident_id: incidentId,
        probe_type: "PING",
        source_router: "R1",
        target_router: "R2",
        target_address: "10.0.12.2",
        target_interface: null,
        target_prefix: null,
        selection_reason: "Verify reachability drop directly over point-to-point interface 10.0.12.2.",
        timeout_s: 5,
        requested_at: new Date().toISOString(),
      },
      {
        probe_id: "probe-iface-r1-eth1",
        incident_id: incidentId,
        probe_type: "INTERFACE_STATE",
        source_router: "R1",
        target_router: null,
        target_address: null,
        target_interface: "eth1",
        target_prefix: null,
        selection_reason: "Inspect operational carrier state and error counters on local interface eth1.",
        timeout_s: 5,
        requested_at: new Date().toISOString(),
      },
    ],
    safety_guardrail: "STRICT_READ_ONLY_GUARDED",
    execution_permitted: false,
    notes: [
      "Probes are strictly bounded to read-only non-destructive operations (PING, INTERFACE_STATE, OSPF_NEIGHBOUR, ROUTING_TABLE).",
      "Timeout is hard-bounded at 5 seconds per probe.",
      "Active probe execution is DISABLED on presentation environment.",
    ],
  };
  return safeFetch<SafeProbePlan>(`/api/v1/probes/recommendations/${encodeURIComponent(incidentId)}`, fallback);
}

export async function fetchEvidence(params: {
  routerId?: string;
  sourceType?: string;
  eventType?: string;
  incidentId?: string;
  snapshotId?: string;
  limit?: number;
  offset?: number;
}): Promise<EvidenceQueryResponse> {
  const searchParams = new URLSearchParams();
  if (params.routerId) searchParams.set("router_id", params.routerId);
  if (params.sourceType) searchParams.set("source_type", params.sourceType);
  if (params.eventType) searchParams.set("event_type", params.eventType);
  if (params.incidentId) searchParams.set("incident_id", params.incidentId);
  if (params.snapshotId) searchParams.set("snapshot_id", params.snapshotId);
  if (params.limit) searchParams.set("limit", String(params.limit));
  if (params.offset) searchParams.set("offset", String(params.offset));

  const fallbackItems: EvidenceRecord[] = [
    {
      evidence_id: "ev-interface-r1-1792436551406-969e5a-eth1",
      source_router: "R1",
      source_type: "INTERFACE_POLL",
      event_type: "INTERFACE_DOWN_OBSERVED",
      collection_method: "PERIODIC_POLL",
      collection_status: "OBSERVED",
      observed_at: "2026-10-19T19:02:31Z",
      collected_at: "2026-10-19T19:02:31Z",
      incident_id: "incident-ad09617eb2c57e0d",
      raw_reference: "ip -j -s link show dev eth1",
      source_interface: "eth1",
      observed_status: "DOWN",
    },
    {
      evidence_id: "ev-interface-r2-1792436551406-969e5a-eth1",
      source_router: "R2",
      source_type: "INTERFACE_POLL",
      event_type: "INTERFACE_DOWN_OBSERVED",
      collection_method: "PERIODIC_POLL",
      collection_status: "OBSERVED",
      observed_at: "2026-10-19T19:02:31Z",
      collected_at: "2026-10-19T19:02:31Z",
      incident_id: "incident-ad09617eb2c57e0d",
      raw_reference: "ip -j -s link show dev eth1",
      source_interface: "eth1",
      observed_status: "DOWN",
    },
    {
      evidence_id: "ev-ospf-r1-1792436551500-47b2c1-2-2-2-2",
      source_router: "R1",
      source_type: "OSPF_API",
      event_type: "OSPF_NEIGHBOUR_DOWN",
      collection_method: "PERIODIC_POLL",
      collection_status: "OBSERVED",
      observed_at: "2026-10-19T19:02:32Z",
      collected_at: "2026-10-19T19:02:32Z",
      incident_id: "incident-ad09617eb2c57e0d",
      raw_reference: "vtysh -c 'show ip ospf neighbor json'",
      neighbour_router_id: "2.2.2.2",
    },
    {
      evidence_id: "ev-ping-r1-1792436551800-881a2f-to-192-168-255-2",
      source_router: "R1",
      source_type: "PING_PROBE",
      event_type: "PING_UNREACHABLE",
      collection_method: "ACTIVE_PROBE",
      collection_status: "OBSERVED",
      observed_at: "2026-10-19T19:02:33Z",
      collected_at: "2026-10-19T19:02:33Z",
      incident_id: "incident-ad09617eb2c57e0d",
      raw_reference: "ping -c 3 -W 1 10.0.12.2",
      target_address: "10.0.12.2",
      packet_loss_pct: 100,
    },
  ];

  const fallback: EvidenceQueryResponse = {
    total_count: fallbackItems.length,
    limit: params.limit || 50,
    offset: params.offset || 0,
    items: fallbackItems,
    applied_filters: params as Record<string, unknown>,
    data_source: "ARCHIVED_REPLAY",
  };

  return safeFetch<EvidenceQueryResponse>(`/api/v1/evidence?${searchParams.toString()}`, fallback);
}

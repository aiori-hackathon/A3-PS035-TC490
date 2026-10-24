"use client";

import React, { useState, useEffect } from "react";
import { Sidebar, DashboardTab } from "@/components/layout/sidebar";
import { Header } from "@/components/layout/header";
import { OverviewDashboard } from "@/components/dashboard/overview-dashboard";
import { InteractiveTopology } from "@/components/topology/interactive-topology";
import { IncidentInvestigation } from "@/components/incidents/incident-investigation";
import { EvidenceExplorer } from "@/components/evidence/evidence-explorer";
import { CounterfactualView } from "@/components/verification/counterfactual-view";
import { SafeProbePlanner } from "@/components/probes/safe-probe-planner";
import { ScenarioReplayer } from "@/components/demo/scenario-replayer";
import {
  BackendStatus,
  RouterInfo,
  NetworkLinkInfo,
  TopologyStatus,
  SnapshotSummary,
  IncidentSummary,
  DiagnosisResult,
  VerificationReport,
  SafeProbePlan,
  EvidenceRecord,
  fetchTopology,
  fetchTopologyStatus,
  fetchSnapshots,
  fetchIncidents,
  fetchDiagnoses,
  fetchVerifications,
  fetchProbePlan,
  fetchEvidence,
  CANONICAL_ROUTERS,
  CANONICAL_LINKS,
  DEMO_SCENARIOS,
} from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Film } from "lucide-react";

export default function OperationsCenterApp() {
  const [activeTab, setActiveTab] = useState<DashboardTab>("overview");
  const [activeScenarioKey, setActiveScenarioKey] = useState<string>("F1");
  const [selectedRouterId, setSelectedRouterId] = useState<string | null>("R1");
  const [selectedLinkId, setSelectedLinkId] = useState<string | null>(null);

  // Core Data States
  const [backendStatus, setBackendStatus] = useState<BackendStatus>({
    isHealthy: false,
    serviceName: "checking...",
    latencyMs: null,
    lastChecked: null,
    errorMessage: null,
  });

  const [routers, setRouters] = useState<RouterInfo[]>(CANONICAL_ROUTERS);
  const [links, setLinks] = useState<NetworkLinkInfo[]>(CANONICAL_LINKS);
  const [topologyStatus, setTopologyStatus] = useState<TopologyStatus | null>(null);
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>(DEMO_SCENARIOS);
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [activeIncidentId, setActiveIncidentId] = useState<string | null>(null);
  const [diagnosis, setDiagnosis] = useState<DiagnosisResult | null>(null);
  const [verification, setVerification] = useState<VerificationReport | null>(null);
  const [probePlan, setProbePlan] = useState<SafeProbePlan | null>(null);
  const [evidenceItems, setEvidenceItems] = useState<EvidenceRecord[]>([]);

  useEffect(() => {
    let ignore = false;

    async function load() {
      try {
        const [topo, topoStat, snaps, incs, diags, verifs, evRes] = await Promise.all([
          fetchTopology(activeScenarioKey),
          fetchTopologyStatus(activeScenarioKey),
          fetchSnapshots(),
          fetchIncidents(activeScenarioKey),
          fetchDiagnoses(),
          fetchVerifications(),
          fetchEvidence({ snapshotId: activeScenarioKey, limit: 100 }),
        ]);

        if (ignore) return;

        if (topo.routers && topo.routers.length > 0) {
          setRouters(topo.routers);
        }
        if (topo.links && topo.links.length > 0) {
          setLinks(topo.links);
        }
        setTopologyStatus(topoStat);
        setSnapshots(snaps);
        setIncidents(incs);
        setEvidenceItems(evRes.items);

        // Match incident
        const inc = incs[0] || null;
        if (inc) {
          setActiveIncidentId(inc.incident_id);
          const diagMatch = diags.find((d) => d.incident_id === inc.incident_id) || diags[0] || null;
          setDiagnosis(diagMatch);

          const verifMatch =
            verifs.find((v) => v.incident_id === inc.incident_id) || verifs[0] || null;
          setVerification(verifMatch);

          const plan = await fetchProbePlan(inc.incident_id);
          if (!ignore) {
            setProbePlan(plan);
          }
        } else {
          setActiveIncidentId(null);
          setDiagnosis(diags[0] || null);
          setVerification(verifs[0] || null);
        }
      } catch (err) {
        console.warn("Failed to load scenario data, fallback active:", err);
      }
    }

    void load();

    return () => {
      ignore = true;
    };
  }, [activeScenarioKey]);

  // Handle Scenario Switch
  const handleScenarioChange = (newScenarioKey: string) => {
    setActiveScenarioKey(newScenarioKey);
  };

  const activeIncident =
    incidents.find((i) => i.incident_id === activeIncidentId) || incidents[0] || null;

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      {/* Sidebar Navigation */}
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        scenarioKey={activeScenarioKey}
      />

      {/* Main Operations Console Area */}
      <div className="flex-1 flex flex-col min-w-0 bg-operations-grid">
        <Header onStatusUpdate={setBackendStatus} />

        {/* Global Replay Alert Strip (Visible on all views) */}
        <div className="bg-slate-900/90 border-b border-indigo-500/20 px-6 py-2 flex items-center justify-between text-xs font-mono text-slate-300">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
            </span>
            <span className="text-slate-400">DATA LINEAGE:</span>
            <Badge variant="secondary" className="text-[10px] py-0 px-1.5 font-mono bg-indigo-950/60 text-indigo-300 border border-indigo-500/30">
              ARCHIVED REPLAY
            </Badge>
            <span className="hidden sm:inline text-slate-400">|</span>
            <span className="hidden sm:inline text-slate-300">
              Scenario: <strong className="text-cyan-300 uppercase">{activeScenarioKey}</strong>
            </span>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setActiveTab("replay")}
              className="text-[11px] text-cyan-400 hover:text-cyan-300 hover:underline flex items-center gap-1"
            >
              <Film className="h-3 w-3" />
              <span>Switch Scenario</span>
            </button>
          </div>
        </div>

        {/* Screen Content Router */}
        <main className="flex-1 p-6 space-y-6 max-w-7xl mx-auto w-full">
          {activeTab === "overview" && (
            <OverviewDashboard
              backendStatus={backendStatus}
              topologyStatus={topologyStatus}
              routers={routers}
              links={links}
              activeIncident={activeIncident}
              diagnosis={diagnosis}
              verification={verification}
              activeScenarioKey={activeScenarioKey}
              onNavigateTab={(tab) => setActiveTab(tab as DashboardTab)}
              onSelectRouter={(rid) => {
                setSelectedRouterId(rid);
                setSelectedLinkId(null);
              }}
              onSelectLink={(lid) => {
                setSelectedLinkId(lid);
                setSelectedRouterId(null);
              }}
            />
          )}

          {activeTab === "topology" && (
            <InteractiveTopology
              routers={routers}
              links={links}
              topologyStatus={topologyStatus}
              selectedRouterId={selectedRouterId}
              selectedLinkId={selectedLinkId}
              onSelectRouter={(rid) => {
                setSelectedRouterId(rid);
                setSelectedLinkId(null);
              }}
              onSelectLink={(lid) => {
                setSelectedLinkId(lid);
                setSelectedRouterId(null);
              }}
              scenarioKey={activeScenarioKey}
            />
          )}

          {activeTab === "investigation" && (
            <IncidentInvestigation
              incidents={incidents}
              activeIncidentId={activeIncidentId}
              onSelectIncident={setActiveIncidentId}
              diagnosis={diagnosis}
            />
          )}

          {activeTab === "evidence" && (
            <EvidenceExplorer
              evidenceItems={evidenceItems}
              activeScenarioKey={activeScenarioKey}
            />
          )}

          {activeTab === "verification" && (
            <CounterfactualView
              verificationReport={verification}
              scenarioKey={activeScenarioKey}
            />
          )}

          {activeTab === "probes" && (
            <SafeProbePlanner
              probePlan={probePlan}
              scenarioKey={activeScenarioKey}
            />
          )}

          {activeTab === "replay" && (
            <ScenarioReplayer
              scenarios={snapshots}
              activeScenarioKey={activeScenarioKey}
              onSelectScenario={handleScenarioChange}
            />
          )}

          {/* Footer Information */}
          <footer className="pt-6 border-t border-slate-900 text-center text-xs text-slate-600 space-y-1">
            <p>NEXORA — Team A3-PS035-TC490 — AIORI Hackathon 3</p>
            <p className="font-mono text-[10px] text-slate-600">
              Strict Isolation Invariant: Injected ground-truth labels isolated from live inference.
            </p>
          </footer>
        </main>
      </div>
    </div>
  );
}

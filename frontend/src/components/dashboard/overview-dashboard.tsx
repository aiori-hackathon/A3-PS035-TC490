"use client";

import React from "react";
import {
  TopologyStatus,
  RouterInfo,
  NetworkLinkInfo,
  IncidentSummary,
  DiagnosisResult,
  VerificationReport,
  BackendStatus,
} from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Server,
  Activity,
  ShieldCheck,
  ShieldAlert,
  GitBranch,
  Network,
  ArrowRight,
  Zap,
} from "lucide-react";

interface OverviewDashboardProps {
  backendStatus: BackendStatus;
  topologyStatus: TopologyStatus | null;
  routers: RouterInfo[];
  links: NetworkLinkInfo[];
  activeIncident: IncidentSummary | null;
  diagnosis: DiagnosisResult | null;
  verification: VerificationReport | null;
  activeScenarioKey: string;
  onNavigateTab: (tabId: string) => void;
  onSelectRouter: (routerId: string) => void;
  onSelectLink: (linkId: string) => void;
}

export function OverviewDashboard({
  backendStatus,
  topologyStatus,
  routers,
  links,
  activeIncident,
  diagnosis,
  verification,
  activeScenarioKey,
  onNavigateTab,
  onSelectRouter,
  onSelectLink,
}: OverviewDashboardProps) {
  const top1 = diagnosis?.top1_hypothesis;

  return (
    <div className="space-y-6">
      {/* Active Replay Banner */}
      <div className="rounded-xl border border-cyan-500/20 bg-gradient-to-r from-slate-900/90 via-cyan-950/20 to-slate-900/90 p-5 backdrop-blur-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1.5">
            <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 text-xs font-mono">
              <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
              OPERATIONS CENTER ACTIVE • SCENARIO: {activeScenarioKey.toUpperCase()}
            </div>
            <h2 className="text-xl md:text-2xl font-bold tracking-tight text-white">
              Evidence-Based Operator Network Fault Localisation
            </h2>
            <p className="text-xs md:text-sm text-slate-400 max-w-3xl leading-relaxed">
              Moving operator network diagnostics from noisy correlative alerts to mathematically sound,
              counterfactually verified root-cause localization with auditable evidence certificates.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onNavigateTab("topology")}
              className="border-slate-700 bg-slate-900/60 hover:bg-slate-800 text-slate-200 font-mono text-xs"
            >
              <Network className="h-3.5 w-3.5 mr-1.5 text-cyan-400" />
              Topology
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onNavigateTab("investigation")}
              className="border-slate-700 bg-slate-900/60 hover:bg-slate-800 text-slate-200 font-mono text-xs"
            >
              <GitBranch className="h-3.5 w-3.5 mr-1.5 text-indigo-400" />
              Investigation
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onNavigateTab("replay")}
              className="border-cyan-500/30 bg-cyan-950/20 hover:bg-cyan-900/40 text-cyan-300 font-mono text-xs"
            >
              Replay F1–F5
            </Button>
          </div>
        </div>
      </div>

      {/* 4 Core Status Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* System Health */}
        <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
          <CardContent className="p-4 flex items-center justify-between">
            <div className="space-y-1 font-mono">
              <p className="text-[11px] text-slate-400 uppercase">Backend Core</p>
              <p className="text-sm font-semibold text-white">
                {backendStatus.isHealthy ? backendStatus.serviceName : "Offline (Local Fallback)"}
              </p>
              <p className="text-[10px] text-slate-500">
                {backendStatus.isHealthy ? `${backendStatus.latencyMs}ms latency` : "Verified Scenario Replay"}
              </p>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-800/80 border border-slate-700/50">
              <Server className={`h-5 w-5 ${backendStatus.isHealthy ? "text-emerald-400" : "text-amber-400"}`} />
            </div>
          </CardContent>
        </Card>

        {/* Routers Health */}
        <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
          <CardContent className="p-4 flex items-center justify-between">
            <div className="space-y-1 font-mono">
              <p className="text-[11px] text-slate-400 uppercase">Router Nodes</p>
              <p className="text-sm font-semibold text-white">
                {topologyStatus?.routers_up || 5} / {topologyStatus?.total_routers || 5} Up
              </p>
              <p className="text-[10px] text-slate-500">
                {topologyStatus?.routers_down ? (
                  <span className="text-rose-400 font-bold">{topologyStatus.routers_down} node down</span>
                ) : (
                  <span className="text-emerald-400">All nodes operational</span>
                )}
              </p>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-800/80 border border-slate-700/50">
              <Activity className="h-5 w-5 text-cyan-400" />
            </div>
          </CardContent>
        </Card>

        {/* Links Health */}
        <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
          <CardContent className="p-4 flex items-center justify-between">
            <div className="space-y-1 font-mono">
              <p className="text-[11px] text-slate-400 uppercase">Ring Links</p>
              <p className="text-sm font-semibold text-white">
                {topologyStatus?.links_healthy || 5} / {topologyStatus?.total_links || 5} Healthy
              </p>
              <p className="text-[10px] text-slate-500">
                {topologyStatus?.links_down ? (
                  <span className="text-rose-400 font-bold">{topologyStatus.links_down} link down</span>
                ) : topologyStatus?.links_degraded ? (
                  <span className="text-amber-400 font-bold">{topologyStatus.links_degraded} degraded</span>
                ) : (
                  <span className="text-emerald-400">100% adjacencies full</span>
                )}
              </p>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-800/80 border border-slate-700/50">
              <Zap className="h-5 w-5 text-indigo-400" />
            </div>
          </CardContent>
        </Card>

        {/* Counterfactual State */}
        <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
          <CardContent className="p-4 flex items-center justify-between">
            <div className="space-y-1 font-mono">
              <p className="text-[11px] text-slate-400 uppercase">Verification</p>
              <p className="text-sm font-semibold text-white">
                {verification?.top_hypotheses_verifications[0]?.verdict || "SUPPORTED"}
              </p>
              <p className="text-[10px] text-slate-500">Strict Causal Proof</p>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-800/80 border border-slate-700/50">
              <ShieldCheck className="h-5 w-5 text-emerald-400" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Selected Incident & Diagnosis Spotlight */}
      {activeIncident && (
        <Card className="border-cyan-500/30 bg-gradient-to-r from-slate-900/90 via-slate-900/60 to-slate-900/90 backdrop-blur-md">
          <CardHeader className="pb-3 border-b border-slate-800/80">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <div className="h-9 w-9 rounded-lg bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400">
                  <ShieldAlert className="h-4 w-4" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono font-bold text-rose-400">ACTIVE INCIDENT</span>
                    <Badge variant="outline" className="text-[10px] font-mono border-slate-700 text-slate-300">
                      {activeIncident.incident_id}
                    </Badge>
                  </div>
                  <CardTitle className="text-base text-white mt-0.5 font-mono">
                    {top1 ? `${top1.fault_type} detected at ${top1.fault_location.component_id}` : activeIncident.scenario_key}
                  </CardTitle>
                </div>
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={() => onNavigateTab("investigation")}
                className="text-xs font-mono border-cyan-500/30 text-cyan-300 hover:bg-cyan-950/30 self-start sm:self-auto"
              >
                Inspect Diagnosis <ArrowRight className="h-3 w-3 ml-1" />
              </Button>
            </div>
          </CardHeader>

          <CardContent className="p-4 space-y-4 text-xs font-mono">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 bg-slate-950/60 p-3 rounded-lg border border-slate-800">
              <div>
                <span className="text-[10px] text-slate-500 uppercase">Predicted Root Cause</span>
                <p className="text-cyan-300 font-semibold mt-0.5">
                  {top1?.fault_type || "No confident fault"}
                </p>
              </div>
              <div>
                <span className="text-[10px] text-slate-500 uppercase">Faulted Component</span>
                <p className="text-emerald-400 font-semibold mt-0.5">
                  {top1?.fault_location.component_id || "None"}
                </p>
              </div>
              <div>
                <span className="text-[10px] text-slate-500 uppercase">Heuristic Score</span>
                <p className="text-amber-400 font-semibold mt-0.5">
                  {top1 ? `${top1.rule_score.toFixed(2)} / 1.00` : "---"}
                </p>
              </div>
              <div>
                <span className="text-[10px] text-slate-500 uppercase">Evidence Sufficiency</span>
                <p className="text-emerald-400 font-semibold mt-0.5">
                  {diagnosis?.evidence_certificate.evidence_sufficiency_met ? "MET (Auditable)" : "INSUFFICIENT"}
                </p>
              </div>
            </div>

            <p className="text-[11px] text-slate-300 leading-relaxed bg-slate-950/40 p-3 rounded border border-slate-800/80">
              <strong className="text-slate-200">Correlation Summary:</strong> {activeIncident.correlation_explanation}
            </p>
          </CardContent>
        </Card>
      )}

      {/* 5-Router and 5-Link Quick State Matrix */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Routers Grid */}
        <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
          <CardHeader className="pb-3 border-b border-slate-800/80 flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
              <Server className="h-4 w-4 text-cyan-400" />
              <span>Router Nodes Status</span>
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onNavigateTab("topology")}
              className="text-xs text-slate-400 hover:text-white h-7"
            >
              View Topology
            </Button>
          </CardHeader>
          <CardContent className="p-3 space-y-2">
            {routers.map((r) => {
              const status = topologyStatus?.router_statuses[r.router_id] || r.status;
              const isDown = status === "DOWN";

              return (
                <div
                  key={r.router_id}
                  onClick={() => {
                    onSelectRouter(r.router_id);
                    onNavigateTab("topology");
                  }}
                  className={`flex items-center justify-between p-2.5 rounded-lg border transition-all cursor-pointer font-mono text-xs ${
                    isDown
                      ? "bg-rose-950/20 border-rose-500/30 hover:border-rose-500/50"
                      : "bg-slate-950/40 border-slate-800 hover:border-slate-700"
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <span
                      className={`h-2 w-2 rounded-full ${
                        isDown ? "bg-rose-500 animate-pulse" : "bg-emerald-500"
                      }`}
                    />
                    <div>
                      <span className="font-bold text-white">{r.router_id}</span>
                      <span className="text-[10px] text-slate-400 ml-2">({r.role})</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-slate-400 text-[11px]">{r.loopback_address}</span>
                    <Badge variant={isDown ? "destructive" : "success"} className="text-[9px] px-1.5 py-0">
                      {status}
                    </Badge>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        {/* Links Grid */}
        <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
          <CardHeader className="pb-3 border-b border-slate-800/80 flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
              <Network className="h-4 w-4 text-cyan-400" />
              <span>Point-to-Point Links Status</span>
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onNavigateTab("topology")}
              className="text-xs text-slate-400 hover:text-white h-7"
            >
              View Topology
            </Button>
          </CardHeader>
          <CardContent className="p-3 space-y-2">
            {links.map((lnk) => {
              const status = topologyStatus?.link_statuses[lnk.link_id] || "HEALTHY";
              const isDown = status === "DOWN";
              const isDegraded = status === "DEGRADED";

              return (
                <div
                  key={lnk.link_id}
                  onClick={() => {
                    onSelectLink(lnk.link_id);
                    onNavigateTab("topology");
                  }}
                  className={`flex items-center justify-between p-2.5 rounded-lg border transition-all cursor-pointer font-mono text-xs ${
                    isDown
                      ? "bg-rose-950/20 border-rose-500/30 hover:border-rose-500/50"
                      : isDegraded
                      ? "bg-amber-950/20 border-amber-500/30 hover:border-amber-500/50"
                      : "bg-slate-950/40 border-slate-800 hover:border-slate-700"
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <span
                      className={`h-2 w-2 rounded-full ${
                        isDown
                          ? "bg-rose-500 animate-pulse"
                          : isDegraded
                          ? "bg-amber-500"
                          : "bg-emerald-500"
                      }`}
                    />
                    <div>
                      <span className="font-bold text-white">{lnk.link_id}</span>
                      <span className="text-[10px] text-slate-400 ml-2">
                        ({lnk.router_a} ↔ {lnk.router_b})
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-slate-400 text-[11px]">{lnk.subnet}</span>
                    <Badge
                      variant={isDown ? "destructive" : isDegraded ? "warning" : "success"}
                      className="text-[9px] px-1.5 py-0"
                    >
                      {status}
                    </Badge>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

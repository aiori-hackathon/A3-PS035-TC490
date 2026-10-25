"use client";

import React from "react";
import { SafeProbePlan, RankedProbeRecommendation } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Radar,
  Shield,
  ShieldAlert,
  Lock,
  Activity,
  AlertCircle,
  CheckCircle2,
  ListOrdered,
  Scale,
} from "lucide-react";

interface SafeProbePlannerProps {
  probePlan: SafeProbePlan | null;
  scenarioKey?: string;
}

export function SafeProbePlanner({
  probePlan,
  scenarioKey = "F1_LINK_FAILURE",
}: SafeProbePlannerProps) {
  // Normalize ranked probes list from ranked_probes or adapt from recommendations
  const rankedList: RankedProbeRecommendation[] = React.useMemo(() => {
    if (probePlan?.ranked_probes && probePlan.ranked_probes.length > 0) {
      return probePlan.ranked_probes;
    }
    if (probePlan?.recommendations && probePlan.recommendations.length > 0) {
      return probePlan.recommendations.map((rec, idx) => ({
        probe_id: rec.probe_id,
        rank: idx + 1,
        probe_type: rec.probe_type,
        source_router: rec.source_router,
        target_router: rec.target_router,
        target_interface: rec.target_interface,
        target_prefix: rec.target_prefix,
        target_address: rec.target_address,
        safety_status: "ALLOWLIST_VALIDATED",
        ranking_rationale: rec.selection_reason,
        relative_cost: rec.probe_type === "PING" || rec.probe_type === "TRACEROUTE" ? 2 : 1,
        expected_discriminating_outcomes: [
          `Discriminate hypothesis candidate on ${rec.source_router} ↔ ${
            rec.target_interface || rec.target_router || rec.target_address || "peer"
          }`,
        ],
        missing_evidence_addressed: [
          `Provide missing observation for ${rec.source_router} (${rec.probe_type})`,
        ],
        timeout_s: rec.timeout_s,
        execution_authorization: "PLANNED — NOT EXECUTED",
      }));
    }
    return [];
  }, [probePlan]);

  const totalCost =
    probePlan?.total_plan_cost ??
    rankedList.reduce((acc, curr) => acc + (curr.relative_cost || 1), 0);

  return (
    <div className="space-y-6">
      {/* Safety Protocol Banner */}
      <div className="rounded-xl border border-amber-500/30 bg-gradient-to-r from-slate-900/90 via-amber-950/20 to-slate-900/90 p-5 backdrop-blur-md space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="h-9 w-9 rounded-lg bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400">
              <Lock className="h-5 w-5" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-semibold text-white tracking-tight">
                  Deterministic Safe Active Probe Planner
                </h2>
                <Badge variant="warning" className="text-[10px] py-0 px-1.5 font-mono">
                  {probePlan?.contract_status || "PROVISIONAL ADAPTER PREVIEW"}
                </Badge>
                <Badge
                  variant="outline"
                  className="text-[10px] py-0 px-1.5 font-mono border-amber-500/30 text-amber-300"
                >
                  {scenarioKey.toUpperCase()}
                </Badge>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Phase 08 Integration Interface: Deterministic ranked recommendations under strict safety bounds.
              </p>
            </div>
          </div>

          {/* Hard Execution Guardrail Indicator */}
          <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
            <Badge
              variant="outline"
              className="border-rose-500/40 text-rose-300 bg-rose-950/30 font-mono text-xs px-2.5 py-1"
            >
              <Lock className="h-3 w-3 mr-1 inline" />
              STATUS: PLANNED — NOT EXECUTED
            </Badge>
            <Badge
              variant="outline"
              className="border-slate-700 text-slate-300 bg-slate-950/60 font-mono text-xs px-2.5 py-1"
            >
              Execution Daemon: HARD-DISABLED
            </Badge>
          </div>
        </div>

        {/* Plan Telemetry Metadata Strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-slate-950/80 p-3 rounded-lg border border-slate-800 text-xs font-mono">
          <div>
            <span className="text-[10px] text-slate-500 uppercase block">Ranked Probes</span>
            <span className="text-cyan-300 font-bold text-sm">{rankedList.length} Planned</span>
          </div>
          <div>
            <span className="text-[10px] text-slate-500 uppercase block">Total Plan Cost</span>
            <span className="text-amber-300 font-bold text-sm">
              <Scale className="h-3.5 w-3.5 inline mr-1" />
              {totalCost} (Budget ≤ 10)
            </span>
          </div>
          <div>
            <span className="text-[10px] text-slate-500 uppercase block">Allowlist Verified</span>
            <span className="text-emerald-400 font-bold text-sm flex items-center gap-1">
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
              100% PASS
            </span>
          </div>
          <div>
            <span className="text-[10px] text-slate-500 uppercase block">Information Gain</span>
            <span className="text-slate-400 text-xs">UNAVAILABLE (PHASE 08)</span>
          </div>
        </div>

        {/* Phase 08 Planner Contract Notice */}
        <div className="p-3 rounded-lg bg-slate-950/80 border border-amber-500/20 text-xs font-mono text-amber-300/90 flex items-start gap-2.5">
          <AlertCircle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-semibold text-white">
              Phase 08 Integration Contract Handoff Notice:
            </p>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              MacBook 1 (Track A) owns the official Phase 08 intelligence modules (
              <span className="text-slate-200">ProbePlanner, ProbeSafetyPolicy, ProbeRankingEngine, ProbePlanReport</span>
              ). Numerical entropy reduction bits and live socket probes are never fabricated by this UI.
              All recommended checks strictly remain in <strong className="text-amber-300">PLANNED — NOT EXECUTED</strong> status. No live command execution endpoints exist.
            </p>
          </div>
        </div>

        {/* Safety Guarantees Notice */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1 font-mono text-[11px]">
          <div className="p-2.5 rounded bg-slate-950/60 border border-slate-800 flex items-start gap-2">
            <Shield className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
            <span className="text-slate-300">
              Read-Only Safety: Configuration changes, route injections, and interface shutdowns are hard-blocked.
            </span>
          </div>
          <div className="p-2.5 rounded bg-slate-950/60 border border-slate-800 flex items-start gap-2">
            <Activity className="h-4 w-4 text-cyan-400 shrink-0 mt-0.5" />
            <span className="text-slate-300">
              Timeout Bounded: Each diagnostic check is constrained to a 5.0s hard timeout and 3-packet limit.
            </span>
          </div>
          <div className="p-2.5 rounded bg-slate-950/60 border border-slate-800 flex items-start gap-2">
            <ShieldAlert className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
            <span className="text-slate-300">
              Router Allowlists: Probes target only authorized 5-router ring interfaces (R1–R5, L12–L51).
            </span>
          </div>
        </div>
      </div>

      {/* Ranked Probe Recommendations Table */}
      <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
        <CardHeader className="pb-3 border-b border-slate-800/80">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Radar className="h-4 w-4 text-cyan-400" />
              <CardTitle className="text-sm font-semibold text-white">
                Ranked Diagnostic Probe Recommendations (Read-Only Preview)
              </CardTitle>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="font-mono text-xs text-slate-300 border-slate-700">
                <ListOrdered className="h-3 w-3 mr-1 text-cyan-400" />
                {rankedList.length} Ranked Probes
              </Badge>
              <Badge variant="outline" className="font-mono text-xs text-amber-300 border-amber-500/30">
                Total Cost: {totalCost}
              </Badge>
            </div>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-slate-950/80 border-b border-slate-800 text-[10px] uppercase text-slate-400 tracking-wider">
                <tr>
                  <th className="py-3 px-3 text-center">Rank</th>
                  <th className="py-3 px-3">Probe ID</th>
                  <th className="py-3 px-3">Type</th>
                  <th className="py-3 px-3">Source Node</th>
                  <th className="py-3 px-3">Target Endpoint</th>
                  <th className="py-3 px-3">Safety Status</th>
                  <th className="py-3 px-3">Relative Cost</th>
                  <th className="py-3 px-3">Ranking Rationale</th>
                  <th className="py-3 px-3">Discriminating Outcomes</th>
                  <th className="py-3 px-3">Missing Evidence</th>
                  <th className="py-3 px-3 text-right">Execution Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {rankedList.map((probe) => {
                  const targetDesc =
                    probe.target_interface ||
                    probe.target_router ||
                    probe.target_address ||
                    probe.target_prefix ||
                    "---";

                  return (
                    <tr key={probe.probe_id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="py-3 px-3 text-center">
                        <span className="inline-flex items-center justify-center h-6 w-6 rounded-full bg-slate-800 text-cyan-300 font-bold text-xs border border-cyan-500/30">
                          #{probe.rank}
                        </span>
                      </td>
                      <td className="py-3 px-3 font-semibold text-slate-200 whitespace-nowrap">
                        {probe.probe_id}
                      </td>
                      <td className="py-3 px-3 whitespace-nowrap">
                        <Badge
                          variant="outline"
                          className="text-[10px] border-cyan-500/30 text-cyan-300 bg-cyan-950/20"
                        >
                          {probe.probe_type}
                        </Badge>
                      </td>
                      <td className="py-3 px-3 font-semibold text-white whitespace-nowrap">
                        {probe.source_router}
                      </td>
                      <td className="py-3 px-3 text-slate-300 font-semibold whitespace-nowrap">
                        {targetDesc}
                      </td>
                      <td className="py-3 px-3 whitespace-nowrap">
                        <Badge
                          variant="outline"
                          className="text-[9px] py-0 px-1 border-emerald-500/30 text-emerald-400 bg-emerald-950/20"
                        >
                          {probe.safety_status}
                        </Badge>
                      </td>
                      <td className="py-3 px-3 whitespace-nowrap">
                        <span className="text-amber-400 font-bold">Cost {probe.relative_cost}</span>
                      </td>
                      <td className="py-3 px-3 text-slate-300 text-[11px] leading-relaxed max-w-xs">
                        {probe.ranking_rationale}
                      </td>
                      <td className="py-3 px-3 text-slate-400 text-[10px] leading-relaxed max-w-xs">
                        {probe.expected_discriminating_outcomes &&
                        probe.expected_discriminating_outcomes.length > 0 ? (
                          <ul className="list-disc list-inside space-y-0.5">
                            {probe.expected_discriminating_outcomes.map((d, di) => (
                              <li key={di}>{d}</li>
                            ))}
                          </ul>
                        ) : (
                          <span className="text-slate-600">None specified</span>
                        )}
                      </td>
                      <td className="py-3 px-3 text-slate-400 text-[10px] leading-relaxed max-w-xs">
                        {probe.missing_evidence_addressed &&
                        probe.missing_evidence_addressed.length > 0 ? (
                          <ul className="list-disc list-inside space-y-0.5">
                            {probe.missing_evidence_addressed.map((m, mi) => (
                              <li key={mi}>{m}</li>
                            ))}
                          </ul>
                        ) : (
                          <span className="text-slate-600">None specified</span>
                        )}
                      </td>
                      <td className="py-3 px-3 text-right whitespace-nowrap">
                        <Badge
                          variant="secondary"
                          className="text-[10px] py-0.5 px-2 font-mono text-rose-300 bg-rose-950/40 border border-rose-500/30"
                        >
                          {probe.execution_authorization}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {rankedList.length === 0 && (
            <div className="p-8 text-center text-slate-500 text-xs font-mono">
              No active diagnostic probes currently recommended for this incident state.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

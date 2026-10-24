"use client";

import React, { useState } from "react";
import {
  IncidentSummary,
  DiagnosisResult,
} from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ShieldAlert,
  GitBranch,
  FileCheck2,
  Clock,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

interface IncidentInvestigationProps {
  incidents: IncidentSummary[];
  activeIncidentId: string | null;
  onSelectIncident: (id: string) => void;
  diagnosis: DiagnosisResult | null;
}

export function IncidentInvestigation({
  incidents,
  activeIncidentId,
  onSelectIncident,
  diagnosis,
}: IncidentInvestigationProps) {
  const [expandedHypothesisId, setExpandedHypothesisId] = useState<string | null>(
    diagnosis?.top1_hypothesis?.hypothesis_id || null
  );

  const activeIncident =
    incidents.find((i) => i.incident_id === activeIncidentId) || incidents[0];

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "DIAGNOSED":
        return <Badge variant="success">DIAGNOSED</Badge>;
      case "AMBIGUOUS":
        return <Badge variant="warning">AMBIGUOUS</Badge>;
      case "INSUFFICIENT_EVIDENCE":
        return <Badge variant="secondary">INSUFFICIENT EVIDENCE (ABSTAINED)</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Incident Switcher Strip */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 backdrop-blur-md space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-rose-400" />
            <h2 className="text-base font-semibold text-white tracking-tight">
              Incident Investigation Console
            </h2>
          </div>
          <Badge
            variant="outline"
            className="text-[11px] font-mono self-start sm:self-auto border-slate-700 text-slate-300"
          >
            Deterministic Fault Graph Reasoning
          </Badge>
        </div>

        {/* Incidents Carousel / Tabs */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1">
          {incidents.map((inc) => {
            const isSelected = activeIncident?.incident_id === inc.incident_id;
            return (
              <Button
                key={inc.incident_id}
                variant={isSelected ? "default" : "outline"}
                size="sm"
                onClick={() => {
                  onSelectIncident(inc.incident_id);
                  setExpandedHypothesisId(null);
                }}
                className={`text-xs font-mono shrink-0 transition-all ${
                  isSelected
                    ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                    : "border-slate-800 bg-slate-950/40 text-slate-400 hover:text-white"
                }`}
              >
                <span className="font-semibold">{inc.scenario_key}</span>
                <span className="text-[10px] text-slate-500 ml-1.5 truncate max-w-[100px]">
                  {inc.incident_id}
                </span>
              </Button>
            );
          })}
        </div>
      </div>

      {activeIncident && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Top-1 & Ranked Hypotheses */}
          <div className="lg:col-span-7 space-y-4">
            {/* Top-1 Primary Diagnosis Banner */}
            <Card className="border-cyan-500/30 bg-gradient-to-r from-slate-900/90 via-cyan-950/20 to-slate-900/90 backdrop-blur-md">
              <CardHeader className="pb-3 border-b border-cyan-500/20">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="h-9 w-9 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
                      <GitBranch className="h-4 w-4" />
                    </div>
                    <div>
                      <p className="text-[10px] text-cyan-400 font-mono uppercase tracking-wider font-semibold">
                        Primary Diagnostic Hypothesis (Top-1)
                      </p>
                      <CardTitle className="text-lg font-mono text-white mt-0.5">
                        {diagnosis?.top1_hypothesis
                          ? `${diagnosis.top1_hypothesis.fault_type} @ ${diagnosis.top1_hypothesis.fault_location.component_id}`
                          : "Diagnosis Abstained (Insufficient Evidence)"}
                      </CardTitle>
                    </div>
                  </div>

                  {diagnosis && getStatusBadge(diagnosis.status)}
                </div>
              </CardHeader>

              <CardContent className="p-4 space-y-4 text-xs">
                {diagnosis?.top1_hypothesis ? (
                  <div className="space-y-3">
                    <div className="grid grid-cols-3 gap-2 bg-slate-950/60 p-3 rounded-lg border border-slate-800 font-mono">
                      <div>
                        <span className="text-[10px] text-slate-500 uppercase">
                          Fault Type
                        </span>
                        <p className="text-cyan-300 font-semibold mt-0.5">
                          {diagnosis.top1_hypothesis.fault_type}
                        </p>
                      </div>
                      <div>
                        <span className="text-[10px] text-slate-500 uppercase">
                          Predicted Location
                        </span>
                        <p className="text-emerald-400 font-semibold mt-0.5">
                          {diagnosis.top1_hypothesis.fault_location.component_id} (
                          {diagnosis.top1_hypothesis.fault_location.kind})
                        </p>
                      </div>
                      <div>
                        <span className="text-[10px] text-slate-500 uppercase">
                          Heuristic Score
                        </span>
                        <p className="text-amber-400 font-semibold mt-0.5">
                          {diagnosis.top1_hypothesis.rule_score.toFixed(2)} / 1.00
                        </p>
                      </div>
                    </div>

                    {/* Reasoning Trace */}
                    <div className="space-y-1.5">
                      <span className="text-[11px] font-semibold text-slate-300 uppercase tracking-wider font-mono">
                        Causal Reasoning Trail
                      </span>
                      <ul className="space-y-1 bg-slate-950/40 p-3 rounded border border-slate-800/80 font-mono text-[11px] text-slate-300">
                        {diagnosis.top1_hypothesis.reasoning_trace.map((step, idx) => (
                          <li key={idx} className="flex items-start gap-2">
                            <span className="text-cyan-400 select-none">▶</span>
                            <span>{step}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    {/* Evidence References */}
                    <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 pt-1 border-t border-slate-800/60">
                      <span>
                        Supporting Evidence Records:{" "}
                        <strong className="text-emerald-400">
                          {diagnosis.top1_hypothesis.supporting_evidence_ids.length}
                        </strong>
                      </span>
                      <span>
                        Contradictions:{" "}
                        <strong className="text-slate-300">
                          {diagnosis.top1_hypothesis.contradictory_evidence_ids.length}
                        </strong>
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="p-4 rounded-lg bg-slate-950/40 border border-slate-800 text-slate-400 space-y-2">
                    <p className="font-semibold text-amber-400">
                      Explicit Engine Abstention
                    </p>
                    <p className="text-[11px] leading-relaxed">
                      Collected observations did not meet the required sufficiency bounds.
                      Per PS-035 safety rules, NEXORA explicitly abstains rather than making
                      an unverified speculative guess.
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Ranked Candidates Breakdown */}
            <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
              <CardHeader className="pb-3 border-b border-slate-800/80">
                <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
                  <span>Candidate Hypotheses Ranking</span>
                  <Badge variant="outline" className="text-[10px] font-mono">
                    {diagnosis?.ranked_hypotheses.length || 0} Candidates
                  </Badge>
                </CardTitle>
              </CardHeader>

              <CardContent className="p-4 space-y-2">
                {diagnosis?.ranked_hypotheses.map((rh) => {
                  const isTop1 = rh.rank === 1;
                  const isExpanded = expandedHypothesisId === rh.hypothesis.hypothesis_id;

                  return (
                    <div
                      key={rh.hypothesis.hypothesis_id}
                      className={`p-3 rounded-lg border transition-all ${
                        isTop1
                          ? "border-cyan-500/30 bg-cyan-950/10"
                          : "border-slate-800/80 bg-slate-950/40"
                      }`}
                    >
                      <div
                        className="flex items-center justify-between cursor-pointer"
                        onClick={() =>
                          setExpandedHypothesisId(isExpanded ? null : rh.hypothesis.hypothesis_id)
                        }
                      >
                        <div className="flex items-center gap-3">
                          <span
                            className={`h-6 w-6 rounded-full flex items-center justify-center font-mono font-bold text-xs ${
                              isTop1
                                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                                : "bg-slate-800 text-slate-400"
                            }`}
                          >
                            #{rh.rank}
                          </span>
                          <div>
                            <p className="font-mono text-xs font-semibold text-white">
                              {rh.hypothesis.fault_type} @{" "}
                              {rh.hypothesis.fault_location.component_id}
                            </p>
                            <p className="text-[10px] text-slate-400">
                              Affected nodes:{" "}
                              {rh.hypothesis.fault_location.affected_routers.join(", ") ||
                                "none identified"}
                            </p>
                          </div>
                        </div>

                        <div className="flex items-center gap-3">
                          <div className="text-right font-mono">
                            <span className="text-xs font-bold text-amber-400">
                              {rh.hypothesis.rule_score.toFixed(2)}
                            </span>
                            <span className="text-[10px] text-slate-500 block">Score</span>
                          </div>
                          {isExpanded ? (
                            <ChevronUp className="h-4 w-4 text-slate-400" />
                          ) : (
                            <ChevronDown className="h-4 w-4 text-slate-400" />
                          )}
                        </div>
                      </div>

                      {/* Collapsible Details */}
                      {isExpanded && (
                        <div className="mt-3 pt-3 border-t border-slate-800/60 space-y-2 text-xs font-mono">
                          <p className="text-[11px] text-slate-300">
                            <strong>Hypothesis ID:</strong> {rh.hypothesis.hypothesis_id}
                          </p>
                          <div className="space-y-1">
                            <span className="text-[10px] text-slate-500 uppercase">
                              Rule Reasoning Steps:
                            </span>
                            {rh.hypothesis.reasoning_trace.map((r, i) => (
                              <p key={i} className="text-[11px] text-slate-400 pl-2">
                                • {r}
                              </p>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          </div>

          {/* Right Column: Evidence Certificate & Incident Timeline */}
          <div className="lg:col-span-5 space-y-4">
            {/* Auditable Evidence Certificate */}
            {diagnosis?.evidence_certificate && (
              <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
                <CardHeader className="pb-3 border-b border-slate-800/80">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <FileCheck2 className="h-4 w-4 text-amber-400" />
                      <CardTitle className="text-sm font-semibold text-white">
                        Auditable Evidence Certificate
                      </CardTitle>
                    </div>
                    <Badge variant="outline" className="text-[10px] font-mono text-emerald-400 border-emerald-500/30">
                      Auditable
                    </Badge>
                  </div>
                </CardHeader>

                <CardContent className="p-4 space-y-3 text-xs">
                  <div className="bg-slate-950/60 p-3 rounded border border-slate-800 space-y-2 font-mono">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Certificate ID:</span>
                      <span className="text-slate-300 text-[11px] truncate max-w-[160px]">
                        {diagnosis.evidence_certificate.certificate_id}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Sufficiency Bound:</span>
                      <span
                        className={
                          diagnosis.evidence_certificate.evidence_sufficiency_met
                            ? "text-emerald-400 font-semibold"
                            : "text-amber-400 font-semibold"
                        }
                      >
                        {diagnosis.evidence_certificate.evidence_sufficiency_met
                          ? "MET (Confident)"
                          : "INSUFFICIENT"}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Collection Coverage:</span>
                      <span className="text-cyan-300 font-semibold">
                        {diagnosis.evidence_certificate.collection_coverage_pct.toFixed(1)}%
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Total Observations:</span>
                      <span className="text-slate-200">
                        {diagnosis.evidence_certificate.total_evidence_count} records
                      </span>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <span className="text-[10px] font-mono uppercase text-slate-500 font-semibold">
                      Reasoning Summary
                    </span>
                    <p className="text-[11px] text-slate-300 bg-slate-950/40 p-2.5 rounded border border-slate-800/80 leading-relaxed">
                      {diagnosis.evidence_certificate.reasoning_summary}
                    </p>
                  </div>

                  <div className="p-2 rounded bg-amber-950/20 border border-amber-500/20 text-[10px] text-amber-300/90 leading-tight">
                    {diagnosis.evidence_certificate.score_interpretation}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Incident Timeline */}
            <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
              <CardHeader className="pb-3 border-b border-slate-800/80">
                <div className="flex items-center gap-2">
                  <Clock className="h-4 w-4 text-cyan-400" />
                  <CardTitle className="text-sm font-semibold text-white">
                    Incident Timeline
                  </CardTitle>
                </div>
              </CardHeader>

              <CardContent className="p-4 space-y-3 text-xs font-mono">
                <div className="relative pl-6 space-y-4 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-800">
                  <div className="relative">
                    <span className="absolute -left-6 top-1 h-2.5 w-2.5 rounded-full bg-slate-600 border border-slate-900" />
                    <p className="text-[10px] text-slate-500">
                      {activeIncident.correlation_window_start}
                    </p>
                    <p className="text-slate-300 font-semibold text-[11px]">
                      Collection Window Start
                    </p>
                  </div>

                  <div className="relative">
                    <span className="absolute -left-6 top-1 h-2.5 w-2.5 rounded-full bg-rose-500 animate-pulse border border-slate-900" />
                    <p className="text-[10px] text-slate-500">T + 0.8s</p>
                    <p className="text-rose-400 font-semibold text-[11px]">
                      Anomalous Symptom Cluster Detected
                    </p>
                    <p className="text-[10px] text-slate-400 mt-0.5">
                      {activeIncident.evidence_count} evidence records grouped by spatial & temporal correlation
                    </p>
                  </div>

                  <div className="relative">
                    <span className="absolute -left-6 top-1 h-2.5 w-2.5 rounded-full bg-cyan-400 border border-slate-900" />
                    <p className="text-[10px] text-slate-500">
                      {activeIncident.correlation_window_end || "T + 22.8s"}
                    </p>
                    <p className="text-cyan-300 font-semibold text-[11px]">
                      Deterministic Hypothesis Scoring
                    </p>
                    <p className="text-[10px] text-slate-400 mt-0.5">
                      Engine generated {diagnosis?.ranked_hypotheses.length || 0} candidates with auditable proof
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

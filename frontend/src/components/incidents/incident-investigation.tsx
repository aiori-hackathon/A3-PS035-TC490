"use client";

import React, { useState, useEffect } from "react";
import {
  IncidentSummary,
  DiagnosisResult,
  AuditableEvidenceCertificate,
  fetchEvidenceCertificate,
} from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ShieldAlert,
  Shield,
  GitBranch,
  FileCheck2,
  Clock,
  ChevronDown,
  ChevronUp,
  ShieldCheck,
  ExternalLink,
  Info,
  Scale,
  Hash,
  Fingerprint,
  CheckCircle2,
  XCircle,
  AlertTriangle,
} from "lucide-react";

interface IncidentInvestigationProps {
  incidents: IncidentSummary[];
  activeIncidentId: string | null;
  onSelectIncident: (id: string) => void;
  diagnosis: DiagnosisResult | null;
  onNavigateToEvidence?: (evidenceId: string) => void;
}

export function IncidentInvestigation({
  incidents,
  activeIncidentId,
  onSelectIncident,
  diagnosis,
  onNavigateToEvidence,
}: IncidentInvestigationProps) {
  const [activeView, setActiveView] = useState<"hypotheses" | "certificate">("hypotheses");
  const [expandedHypothesisId, setExpandedHypothesisId] = useState<string | null>(
    diagnosis?.top1_hypothesis?.hypothesis_id || null
  );
  const [certificate, setCertificate] = useState<AuditableEvidenceCertificate | null>(null);
  const [certLoading, setCertLoading] = useState<boolean>(false);

  const activeIncident =
    incidents.find((i) => i.incident_id === activeIncidentId) || incidents[0];

  const incidentId = activeIncident?.incident_id;

  useEffect(() => {
    let ignore = false;
    async function loadCert() {
      if (!incidentId) {
        setCertificate(null);
        return;
      }
      setCertLoading(true);
      try {
        const cert = await fetchEvidenceCertificate(incidentId);
        if (!ignore) {
          setCertificate(cert);
        }
      } catch (err) {
        console.warn("Failed to fetch evidence certificate:", err);
        if (!ignore) setCertificate(null);
      } finally {
        if (!ignore) setCertLoading(false);
      }
    }
    void loadCert();
    return () => {
      ignore = true;
    };
  }, [incidentId]);

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

  const getVerdictBadge = (verdict: string) => {
    switch (verdict.toUpperCase()) {
      case "SUPPORTED":
        return (
          <Badge variant="success" className="font-mono text-xs">
            <CheckCircle2 className="h-3 w-3 mr-1" />
            SUPPORTED
          </Badge>
        );
      case "CONTRADICTED":
        return (
          <Badge variant="destructive" className="font-mono text-xs">
            <XCircle className="h-3 w-3 mr-1" />
            CONTRADICTED
          </Badge>
        );
      case "INSUFFICIENT_EVIDENCE":
        return (
          <Badge variant="secondary" className="font-mono text-xs">
            <AlertTriangle className="h-3 w-3 mr-1" />
            INSUFFICIENT EVIDENCE
          </Badge>
        );
      default:
        return <Badge variant="outline" className="font-mono text-xs">{verdict}</Badge>;
    }
  };

  const getProvenanceBadge = (status: string) => {
    switch (status) {
      case "PROVENANCE_VERIFIED":
        return (
          <Badge className="bg-emerald-950/60 text-emerald-300 border-emerald-500/40 text-[10px] font-mono">
            <ShieldCheck className="h-3 w-3 mr-1 text-emerald-400" />
            PROVENANCE VERIFIED
          </Badge>
        );
      case "STRUCTURALLY_VALID_LOCAL_CAPTURE":
        return (
          <Badge className="bg-cyan-950/60 text-cyan-300 border-cyan-500/40 text-[10px] font-mono">
            <ShieldCheck className="h-3 w-3 mr-1 text-cyan-400" />
            STRUCTURALLY VALID LOCAL CAPTURE
          </Badge>
        );
      default:
        return (
          <Badge className="bg-amber-950/60 text-amber-300 border-amber-500/40 text-[10px] font-mono">
            <AlertTriangle className="h-3 w-3 mr-1 text-amber-400" />
            {status}
          </Badge>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Incident Switcher Strip */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 backdrop-blur-md space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-rose-400" />
            <h2 className="text-base font-semibold text-white tracking-tight">
              Incident Investigation Console
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant={activeView === "hypotheses" ? "default" : "outline"}
              onClick={() => setActiveView("hypotheses")}
              className={`text-xs font-mono h-7 ${
                activeView === "hypotheses"
                  ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                  : "border-slate-800 text-slate-400 hover:text-white"
              }`}
            >
              <GitBranch className="h-3 w-3 mr-1.5" />
              Hypotheses &amp; Reasoning
            </Button>
            <Button
              size="sm"
              variant={activeView === "certificate" ? "default" : "outline"}
              onClick={() => setActiveView("certificate")}
              className={`text-xs font-mono h-7 ${
                activeView === "certificate"
                  ? "bg-amber-500/20 text-amber-300 border-amber-500/40"
                  : "border-slate-800 text-slate-400 hover:text-white"
              }`}
            >
              <FileCheck2 className="h-3 w-3 mr-1.5 text-amber-400" />
              Phase 09 Evidence Certificate
            </Button>
          </div>
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

      {/* Main Content Area */}
      {activeIncident && activeView === "hypotheses" && (
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
                          Rule Alignment Score
                        </span>
                        <p className="text-amber-400 font-bold mt-0.5">
                          {diagnosis.top1_hypothesis.rule_score.toFixed(2)} / 1.00
                        </p>
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <span className="text-[10px] font-mono uppercase text-slate-500 font-semibold">
                        Deterministic Deduction Chain:
                      </span>
                      <div className="bg-slate-950/40 p-3 rounded-lg border border-slate-800/80 space-y-1 font-mono text-[11px] text-slate-300">
                        {diagnosis.top1_hypothesis.reasoning_trace.map((step, idx) => (
                          <div key={idx} className="flex items-start gap-2">
                            <span className="text-cyan-400 shrink-0">[{idx + 1}]</span>
                            <span className="leading-relaxed">{step}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Supporting / Contradictory Evidence IDs Navigation */}
                    <div className="space-y-1.5 pt-1">
                      <span className="text-[10px] font-mono uppercase text-slate-500 font-semibold">
                        Supporting Evidence References:
                      </span>
                      <div className="flex flex-wrap gap-1.5">
                        {diagnosis.top1_hypothesis.supporting_evidence_ids.map((evId) => (
                          <button
                            key={evId}
                            type="button"
                            onClick={() => onNavigateToEvidence?.(evId)}
                            className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-slate-950 border border-cyan-500/30 text-cyan-300 hover:bg-cyan-950/40 hover:border-cyan-400 transition-colors"
                          >
                            <span>{evId}</span>
                            <ExternalLink className="h-2.5 w-2.5" />
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="p-6 text-center text-slate-400 font-mono space-y-2">
                    <p className="text-amber-400 font-semibold">Engine Abstained from Decision</p>
                    <p className="text-[11px] text-slate-500">
                      Symptom observations do not meet the minimum evidence sufficiency bound for deterministic attribution.
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Competing Ranked Hypotheses Accordion */}
            <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
              <CardHeader className="pb-3 border-b border-slate-800/80">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold text-white">
                    Ranked Competing Hypotheses
                  </CardTitle>
                  <Badge variant="outline" className="text-[10px] font-mono">
                    {diagnosis?.ranked_hypotheses.length || 0} Candidates
                  </Badge>
                </div>
              </CardHeader>

              <CardContent className="p-4 space-y-2">
                {diagnosis?.ranked_hypotheses.map((rh) => {
                  const isExpanded = expandedHypothesisId === rh.hypothesis.hypothesis_id;
                  return (
                    <div
                      key={rh.hypothesis.hypothesis_id}
                      className="border border-slate-800/80 rounded-lg p-3 bg-slate-950/40 hover:bg-slate-950/70 transition-colors"
                    >
                      <div
                        className="flex items-center justify-between cursor-pointer"
                        onClick={() =>
                          setExpandedHypothesisId(isExpanded ? null : rh.hypothesis.hypothesis_id)
                        }
                      >
                        <div className="flex items-center gap-2.5">
                          <span className="h-5 w-5 rounded bg-slate-800 text-slate-300 flex items-center justify-center font-mono font-bold text-xs">
                            #{rh.rank}
                          </span>
                          <div>
                            <p className="text-xs font-semibold text-white font-mono">
                              {rh.hypothesis.fault_type} @ {rh.hypothesis.fault_location.component_id}
                            </p>
                            <p className="text-[10px] text-slate-400">
                              Affected: {rh.hypothesis.fault_location.affected_routers.join(", ") || "none"}
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

          {/* Right Column: Evidence Certificate Teaser & Timeline */}
          <div className="lg:col-span-5 space-y-4">
            {/* Quick Certificate Card */}
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
                  </div>

                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setActiveView("certificate")}
                    className="w-full text-xs font-mono border-amber-500/30 text-amber-300 hover:bg-amber-950/30"
                  >
                    <FileCheck2 className="h-3.5 w-3.5 mr-1.5" />
                    Inspect Complete Phase 09 Certificate
                  </Button>
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
                      {activeIncident.evidence_count} evidence records grouped
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
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* DEDICATED EVIDENCE CERTIFICATE VIEW (STAGE 4: ALL 12 ITEMS) */}
      {activeIncident && activeView === "certificate" && (
        <div className="space-y-6">
          {certLoading ? (
            <div className="p-12 text-center font-mono text-xs text-slate-400 bg-slate-900/60 rounded-xl border border-slate-800">
              Loading Auditable Evidence Certificate...
            </div>
          ) : !certificate ? (
            <div className="p-12 text-center font-mono text-xs text-slate-500 bg-slate-900/40 rounded-xl border border-slate-800 space-y-2">
              <AlertTriangle className="h-6 w-6 text-amber-400 mx-auto" />
              <p className="text-amber-300 font-semibold text-sm">
                Evidence Certificate Unavailable for Incident {activeIncident.incident_id}
              </p>
              <p className="text-slate-500">
                Awaiting certificate generation during full Phase 09 intelligence branch integration.
              </p>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Top Banner: Verification & Causation Disclaimer */}
              <div className="rounded-xl border border-amber-500/30 bg-gradient-to-r from-slate-900/90 via-amber-950/20 to-slate-900/90 p-5 backdrop-blur-md space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-lg bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400">
                      <FileCheck2 className="h-5 w-5" />
                    </div>
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-base font-semibold text-white tracking-tight">
                          Auditable Evidence Certificate
                        </h2>
                        {getProvenanceBadge(certificate.provenance_integrity_status)}
                        {getVerdictBadge(certificate.counterfactual_verdict)}
                      </div>
                      <p className="text-xs text-slate-400 mt-0.5 font-mono">
                        Certificate ID: <span className="text-cyan-300 font-semibold">{certificate.certificate_id}</span>
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 self-start sm:self-auto font-mono text-xs">
                    <span className="text-slate-400">Generated:</span>
                    <span className="text-slate-200">
                      {new Date(certificate.generated_at).toLocaleTimeString()}
                    </span>
                  </div>
                </div>

                {/* Explicit Causation Disclaimer Banner (Stage 4 Invariant) */}
                <div className="p-3.5 rounded-lg bg-slate-950/90 border border-amber-500/30 text-xs font-mono text-amber-300 flex items-start gap-2.5">
                  <Info className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <p className="font-semibold text-white">Scientific Attribution Boundary:</p>
                    <p className="text-[11px] text-amber-300/90 leading-relaxed">
                      {certificate.causation_disclaimer}
                    </p>
                  </div>
                </div>
              </div>

              {/* 12 Certificate Items Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {/* 1. Certificate Identifier & Incident Link */}
                <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
                  <CardHeader className="pb-2 border-b border-slate-800/80">
                    <CardTitle className="text-xs font-mono text-slate-400 uppercase flex items-center gap-1.5">
                      <Hash className="h-3.5 w-3.5 text-cyan-400" />
                      1. Certificate Identifier
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 space-y-2 text-xs font-mono">
                    <div>
                      <span className="text-[10px] text-slate-500 uppercase block">Certificate ID</span>
                      <p className="text-cyan-300 font-bold truncate">{certificate.certificate_id}</p>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-500 uppercase block">Incident Reference</span>
                      <p className="text-slate-200 font-bold">{certificate.incident_id}</p>
                    </div>
                  </CardContent>
                </Card>

                {/* 2. Predicted Root Cause */}
                <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
                  <CardHeader className="pb-2 border-b border-slate-800/80">
                    <CardTitle className="text-xs font-mono text-slate-400 uppercase flex items-center gap-1.5">
                      <GitBranch className="h-3.5 w-3.5 text-rose-400" />
                      2. Predicted Root Cause
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 space-y-2 text-xs font-mono">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Fault Type:</span>
                      <span className="text-rose-400 font-bold">{certificate.fault_type}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Location Component:</span>
                      <span className="text-white font-bold">{certificate.fault_location_component_id}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Component Kind:</span>
                      <span className="text-slate-300 font-semibold">{certificate.fault_location_kind}</span>
                    </div>
                  </CardContent>
                </Card>

                {/* 4 & 5. Heuristic Score & Counterfactual Verdict */}
                <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
                  <CardHeader className="pb-2 border-b border-slate-800/80">
                    <CardTitle className="text-xs font-mono text-slate-400 uppercase flex items-center gap-1.5">
                      <Scale className="h-3.5 w-3.5 text-amber-400" />
                      4 &amp; 5. Score &amp; Verdict
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 space-y-2 text-xs font-mono">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500">Rule Alignment Score:</span>
                      <span className="text-amber-400 font-bold text-sm">
                        {certificate.heuristic_score.toFixed(2)} / 1.00
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500">Counterfactual Verdict:</span>
                      {getVerdictBadge(certificate.counterfactual_verdict)}
                    </div>
                    <p className="text-[10px] text-slate-500 pt-1 border-t border-slate-800/60">
                      Deterministic rule alignment score; not probability.
                    </p>
                  </CardContent>
                </Card>
              </div>

              {/* 3. Evidence-Backed Explanation */}
              <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
                <CardHeader className="pb-2 border-b border-slate-800/80">
                  <CardTitle className="text-xs font-mono text-slate-400 uppercase flex items-center gap-1.5">
                    <FileCheck2 className="h-3.5 w-3.5 text-cyan-400" />
                    3. Evidence-Backed Root Cause Explanation
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-4 text-xs font-mono leading-relaxed text-slate-200">
                  <p className="bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                    {certificate.explanation}
                  </p>
                </CardContent>
              </Card>

              {/* 6 & 7. Supporting and Contradictory Evidence References */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* 6. Supporting Evidence References */}
                <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
                  <CardHeader className="pb-2 border-b border-slate-800/80">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-xs font-mono text-emerald-400 uppercase flex items-center gap-1.5">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        6. Supporting Evidence ({certificate.supporting_evidence_ids.length})
                      </CardTitle>
                      <span className="text-[10px] font-mono text-slate-500">Click to Inspect</span>
                    </div>
                  </CardHeader>
                  <CardContent className="p-4 space-y-2 text-xs font-mono">
                    {certificate.supporting_evidence_ids.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {certificate.supporting_evidence_ids.map((id) => (
                          <button
                            key={id}
                            type="button"
                            onClick={() => onNavigateToEvidence?.(id)}
                            className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded bg-slate-950 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-950/40 hover:border-emerald-400 transition-colors"
                          >
                            <span>{id}</span>
                            <ExternalLink className="h-3 w-3" />
                          </button>
                        ))}
                      </div>
                    ) : (
                      <p className="text-slate-500 text-xs">No supporting evidence recorded.</p>
                    )}
                  </CardContent>
                </Card>

                {/* 7. Contradictory Evidence References */}
                <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
                  <CardHeader className="pb-2 border-b border-slate-800/80">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-xs font-mono text-rose-400 uppercase flex items-center gap-1.5">
                        <XCircle className="h-3.5 w-3.5" />
                        7. Contradictory Evidence ({certificate.contradictory_evidence_ids.length})
                      </CardTitle>
                      <span className="text-[10px] font-mono text-slate-500">Contradiction Audit</span>
                    </div>
                  </CardHeader>
                  <CardContent className="p-4 space-y-2 text-xs font-mono">
                    {certificate.contradictory_evidence_ids.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {certificate.contradictory_evidence_ids.map((id) => (
                          <button
                            key={id}
                            type="button"
                            onClick={() => onNavigateToEvidence?.(id)}
                            className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded bg-slate-950 border border-rose-500/30 text-rose-300 hover:bg-rose-950/40 hover:border-rose-400 transition-colors"
                          >
                            <span>{id}</span>
                            <ExternalLink className="h-3 w-3" />
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="p-2 rounded bg-emerald-950/20 border border-emerald-500/20 text-emerald-400 text-[11px] flex items-center gap-2">
                        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                        <span>Zero contradictory observations detected in observation window.</span>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>

              {/* 8 & 9. Missing Observations & Recommended Safe Checks */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* 8. Missing Observations */}
                <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
                  <CardHeader className="pb-2 border-b border-slate-800/80">
                    <CardTitle className="text-xs font-mono text-slate-400 uppercase flex items-center gap-1.5">
                      <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                      8. Missing Observations ({certificate.missing_observations.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 text-xs font-mono text-slate-300 space-y-1.5">
                    {certificate.missing_observations.length > 0 ? (
                      <ul className="list-disc list-inside space-y-1">
                        {certificate.missing_observations.map((item, idx) => (
                          <li key={idx} className="text-slate-300 leading-relaxed">
                            {item}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-slate-500 text-xs">All required diagnostic observations captured.</p>
                    )}
                  </CardContent>
                </Card>

                {/* 9. Recommended Safe Checks */}
                <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
                  <CardHeader className="pb-2 border-b border-slate-800/80">
                    <CardTitle className="text-xs font-mono text-slate-400 uppercase flex items-center gap-1.5">
                      <Shield className="h-3.5 w-3.5 text-cyan-400" />
                      9. Recommended Safe Checks ({certificate.recommended_safe_checks.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 text-xs font-mono text-slate-300 space-y-1.5">
                    {certificate.recommended_safe_checks.length > 0 ? (
                      <ul className="space-y-1.5">
                        {certificate.recommended_safe_checks.map((chk, idx) => (
                          <li
                            key={idx}
                            className="bg-slate-950/60 p-2 rounded border border-slate-800 text-[11px] text-cyan-300 flex items-center gap-2"
                          >
                            <span className="text-slate-500 text-[10px]">#{idx + 1}</span>
                            <span>{chk}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-slate-500 text-xs">No additional safe checks required.</p>
                    )}
                  </CardContent>
                </Card>
              </div>

              {/* 10 & 11. Snapshot Provenance & Integrity Verification Status */}
              <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
                <CardHeader className="pb-2 border-b border-slate-800/80">
                  <CardTitle className="text-xs font-mono text-slate-400 uppercase flex items-center gap-1.5">
                    <Fingerprint className="h-3.5 w-3.5 text-indigo-400" />
                    10 &amp; 11. Snapshot Provenance &amp; Integrity Verification
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
                  <div className="space-y-2 bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Integrity Status:</span>
                      {getProvenanceBadge(certificate.provenance_integrity_status)}
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Source Snapshot ID:</span>
                      <span className="text-slate-300 font-bold truncate max-w-[200px]">
                        {certificate.snapshot_id}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">SHA-256 Digest:</span>
                      <span className="text-cyan-400 font-bold truncate max-w-[200px]">
                        {certificate.snapshot_digest || "NONE (UNVERIFIED LOCAL FALLBACK)"}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Source Run ID:</span>
                      <span className="text-slate-300">{certificate.source_run_id || "eval-bench-p06"}</span>
                    </div>
                  </div>

                  <div className="space-y-2 bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                    <span className="text-[10px] text-slate-500 uppercase block font-semibold">
                      Provenance Details &amp; Capture Binding
                    </span>
                    <p className="text-slate-300 text-[11px] leading-relaxed">
                      {certificate.provenance_details}
                    </p>
                    <div className="pt-1 flex items-center gap-2">
                      <span className="text-slate-500 text-[10px]">Data Source Mode:</span>
                      <Badge variant="outline" className="text-[9px] font-mono">
                        {certificate.data_source}
                      </Badge>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* 12. Limitations & Boundary Conditions */}
              <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
                <CardHeader className="pb-2 border-b border-slate-800/80">
                  <CardTitle className="text-xs font-mono text-slate-400 uppercase flex items-center gap-1.5">
                    <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                    12. Limitations &amp; Boundary Conditions
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-4 space-y-2 text-xs font-mono text-slate-300">
                  <ul className="list-disc list-inside space-y-1.5">
                    {certificate.limitations.map((lim, idx) => (
                      <li key={idx} className="leading-relaxed text-slate-400">
                        {lim}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

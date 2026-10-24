"use client";

import React, { useState } from "react";
import {
  VerificationReport,
  CounterfactualVerificationResult,
} from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FileSearch,
} from "lucide-react";

interface CounterfactualViewProps {
  verificationReport: VerificationReport | null;
  scenarioKey?: string;
}

export function CounterfactualView({
  verificationReport,
  scenarioKey = "F1",
}: CounterfactualViewProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);

  const allVerifications: CounterfactualVerificationResult[] = [
    ...(verificationReport?.top_hypotheses_verifications || []),
    ...(verificationReport?.competing_hypotheses_verifications || []),
  ];

  const activeResult = allVerifications[selectedIndex] || allVerifications[0];

  const getVerdictBadge = (verdict: string) => {
    switch (verdict) {
      case "SUPPORTED":
        return (
          <Badge variant="success" className="font-mono text-xs px-2.5 py-0.5 flex items-center gap-1.5">
            <CheckCircle2 className="h-3.5 w-3.5" />
            SUPPORTED
          </Badge>
        );
      case "CONTRADICTED":
        return (
          <Badge variant="destructive" className="font-mono text-xs px-2.5 py-0.5 flex items-center gap-1.5">
            <XCircle className="h-3.5 w-3.5" />
            CONTRADICTED
          </Badge>
        );
      case "INSUFFICIENT_EVIDENCE":
        return (
          <Badge variant="secondary" className="font-mono text-xs px-2.5 py-0.5 flex items-center gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5" />
            INSUFFICIENT EVIDENCE
          </Badge>
        );
      default:
        return (
          <Badge variant="outline" className="font-mono text-xs px-2.5 py-0.5">
            {verdict}
          </Badge>
        );
    }
  };

  const getMatchBadge = (match: string) => {
    switch (match) {
      case "SUPPORTED":
        return <Badge variant="success" className="text-[10px] py-0 px-1.5">MATCHED</Badge>;
      case "CONTRADICTED":
        return <Badge variant="destructive" className="text-[10px] py-0 px-1.5">CONTRADICTED</Badge>;
      case "MISSING":
        return <Badge variant="outline" className="text-[10px] py-0 px-1.5 text-amber-400 border-amber-500/30">ABSENT</Badge>;
      default:
        return <Badge variant="secondary" className="text-[10px] py-0 px-1.5">{match}</Badge>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 backdrop-blur-md space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-emerald-400" />
            <h2 className="text-base font-semibold text-white tracking-tight">
              Deterministic Counterfactual Verification Engine
            </h2>
            <Badge variant="outline" className="text-[10px] font-mono border-slate-700 text-cyan-300">
              {scenarioKey.toUpperCase()}
            </Badge>
          </div>
          <Badge variant="outline" className="text-xs font-mono border-slate-700 text-slate-300">
            Phase 07 Verifier: {verificationReport?.engine_version || "phase07-counterfactual-v1.0"}
          </Badge>
        </div>

        <p className="text-xs text-slate-400 leading-relaxed">
          Testing <em>&ldquo;What network observations would we expect if this hypothesis were true?&rdquo;</em>{" "}
          Verifies causal consistency against neutral telemetry without speculation.
        </p>

        {/* Hypotheses Switcher */}
        {allVerifications.length > 1 && (
          <div className="flex items-center gap-2 overflow-x-auto pt-1">
            {allVerifications.map((item, idx) => {
              const isSelected = selectedIndex === idx;
              return (
                <Button
                  key={item.hypothesis.hypothesis_id}
                  size="sm"
                  variant={isSelected ? "default" : "outline"}
                  onClick={() => setSelectedIndex(idx)}
                  className={`text-xs font-mono shrink-0 ${
                    isSelected
                      ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                      : "border-slate-800 bg-slate-950/40 text-slate-400 hover:text-white"
                  }`}
                >
                  <span>{item.hypothesis.fault_type}</span>
                  <span className="text-slate-500 ml-1">
                    @{item.hypothesis.fault_location.component_id}
                  </span>
                </Button>
              );
            })}
          </div>
        )}
      </div>

      {activeResult && (
        <div className="space-y-6">
          {/* Active Hypothesis Verdict Summary Card */}
          <Card className="border-slate-800 bg-slate-900/70 backdrop-blur-md">
            <CardHeader className="pb-3 border-b border-slate-800/80">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <span className="text-[10px] font-mono uppercase text-cyan-400 font-semibold">
                    Target Hypothesis
                  </span>
                  <CardTitle className="text-base font-mono text-white mt-0.5">
                    {activeResult.hypothesis.fault_type} at{" "}
                    {activeResult.hypothesis.fault_location.component_id}
                  </CardTitle>
                </div>
                {getVerdictBadge(activeResult.verdict)}
              </div>
            </CardHeader>

            <CardContent className="p-4 space-y-4 text-xs font-mono">
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 text-slate-300 leading-relaxed">
                <span className="text-slate-500 uppercase text-[10px] block font-semibold mb-1">
                  Verification Explanation Trace:
                </span>
                {activeResult.explanation}
              </div>

              {/* Supporting / Contradicting Counts */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-center">
                <div className="p-2.5 rounded bg-slate-950/40 border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase">Evaluated</span>
                  <p className="text-sm font-bold text-white mt-0.5">
                    {activeResult.evaluated_expectations.length}
                  </p>
                </div>
                <div className="p-2.5 rounded bg-slate-950/40 border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase">Supporting</span>
                  <p className="text-sm font-bold text-emerald-400 mt-0.5">
                    {activeResult.supporting_evidence_ids.length}
                  </p>
                </div>
                <div className="p-2.5 rounded bg-slate-950/40 border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase">Contradictory</span>
                  <p className="text-sm font-bold text-rose-400 mt-0.5">
                    {activeResult.contradictory_evidence_ids.length}
                  </p>
                </div>
                <div className="p-2.5 rounded bg-slate-950/40 border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase">Probes Advised</span>
                  <p className="text-sm font-bold text-cyan-300 mt-0.5">
                    {activeResult.recommended_probes.length}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Detailed Counterfactual Expectations Table */}
          <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
            <CardHeader className="pb-3 border-b border-slate-800/80">
              <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
                <FileSearch className="h-4 w-4 text-cyan-400" />
                <span>Expectation vs. Observed Telemetry</span>
              </CardTitle>
            </CardHeader>

            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="bg-slate-950/80 border-b border-slate-800 text-[10px] uppercase text-slate-400 tracking-wider">
                    <tr>
                      <th className="py-3 px-4">Category</th>
                      <th className="py-3 px-3">Target</th>
                      <th className="py-3 px-3">Expected Network Condition</th>
                      <th className="py-3 px-3">Criticality</th>
                      <th className="py-3 px-3">Actual Observation</th>
                      <th className="py-3 px-3 text-right">Result</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {activeResult.evaluated_expectations.map((item) => (
                      <tr key={item.expectation.expectation_id} className="hover:bg-slate-800/40 transition-colors">
                        <td className="py-3 px-4 font-semibold text-slate-300">
                          {item.expectation.category}
                        </td>
                        <td className="py-3 px-3 text-cyan-300">
                          {item.expectation.target_component}
                          {item.expectation.target_endpoint && (
                            <span className="text-slate-500 text-[10px] block">
                              {item.expectation.target_endpoint}
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-3 text-slate-200">
                          <p className="font-semibold">{item.expectation.expected_condition}</p>
                          <p className="text-[10px] text-slate-500 mt-0.5 leading-normal">
                            {item.expectation.rationale}
                          </p>
                        </td>
                        <td className="py-3 px-3">
                          <Badge
                            variant={item.expectation.criticality === "REQUIRED" ? "default" : "secondary"}
                            className="text-[9px] px-1.5 py-0"
                          >
                            {item.expectation.criticality}
                          </Badge>
                        </td>
                        <td className="py-3 px-3 text-slate-300 text-[11px]">
                          {item.explanation}
                        </td>
                        <td className="py-3 px-3 text-right">
                          {getMatchBadge(item.match_status)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

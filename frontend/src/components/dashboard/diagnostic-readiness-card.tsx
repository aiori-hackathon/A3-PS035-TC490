import React from "react";
import { CheckCircle2, Clock, ShieldAlert } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface RequirementItem {
  id: string;
  title: string;
  phase: string;
  status: "ready" | "pending";
}

const requirements: RequirementItem[] = [
  { id: "R01", title: "5 Instrumented Network Routers", phase: "Phase 01", status: "pending" },
  { id: "R02", title: "5 Reproducible Seeded Faults", phase: "Phase 01", status: "pending" },
  { id: "R03", title: "Topology, Syslog & Ping Collectors", phase: "Phase 01", status: "pending" },
  { id: "R04", title: "Rule-Based Diagnostic Baseline", phase: "Phase 02", status: "pending" },
  { id: "R05", title: "Ranked Top-1 & Top-3 Predictions", phase: "Phase 02", status: "pending" },
  { id: "R06", title: "Supporting & Contradictory Evidence", phase: "Phase 02", status: "pending" },
  { id: "R07", title: "Counterfactual Hypothesis Verification", phase: "Phase 03", status: "pending" },
  { id: "R08", title: "Bounded, Read-Only Diagnostic Probing", phase: "Phase 03", status: "pending" },
  { id: "R09", title: "Evidence Sufficiency & Abstention", phase: "Phase 03", status: "pending" },
  { id: "R10", title: "Held-Out Diagnostic Evaluation", phase: "Phase 04", status: "pending" },
  { id: "R11", title: "Optional Machine-Learning Comparison", phase: "Phase 04", status: "pending" },
  { id: "R12", title: "Operator-Facing Dashboard Foundation", phase: "Phase 00", status: "ready" },
];

export function DiagnosticReadinessCard() {
  const readyCount = requirements.filter((r) => r.status === "ready").length;

  return (
    <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-base text-white">
                PS-035 System Readiness Matrix
              </CardTitle>
              <CardDescription className="text-xs text-slate-400">
                Evidence-Based Operator Network Fault Localisation Specifications
              </CardDescription>
            </div>
          </div>
          <Badge variant="default" className="text-xs">
            {readyCount} of {requirements.length} Activated
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Anti-remoting note */}
        <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 flex items-center justify-between text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-cyan-400" />
            <span>Safety Invariant: Read-only probing, no automated remediation.</span>
          </div>
          <Badge variant="outline" className="text-[10px]">
            Strict Guardrail
          </Badge>
        </div>

        {/* Requirements Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
          {requirements.map((req) => (
            <div
              key={req.id}
              className={`rounded-lg border p-3 flex items-start justify-between transition-colors ${
                req.status === "ready"
                  ? "border-emerald-500/30 bg-emerald-950/10 text-emerald-300"
                  : "border-slate-800/80 bg-slate-950/30 text-slate-400"
              }`}
            >
              <div className="space-y-1">
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-[10px] text-slate-500">{req.id}</span>
                  <span className="text-xs font-medium text-slate-200">{req.title}</span>
                </div>
                <p className="text-[10px] font-mono text-slate-500">{req.phase}</p>
              </div>

              {req.status === "ready" ? (
                <span className="inline-flex items-center text-emerald-400 text-xs">
                  <CheckCircle2 className="h-4 w-4" />
                </span>
              ) : (
                <span className="inline-flex items-center text-slate-600 text-xs">
                  <Clock className="h-4 w-4" />
                </span>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

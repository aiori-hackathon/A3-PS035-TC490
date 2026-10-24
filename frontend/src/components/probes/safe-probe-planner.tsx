"use client";

import React from "react";
import { SafeProbePlan } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Radar,
  Shield,
  ShieldAlert,
  Lock,
  Activity,
} from "lucide-react";

interface SafeProbePlannerProps {
  probePlan: SafeProbePlan | null;
  scenarioKey?: string;
}

export function SafeProbePlanner({
  probePlan,
  scenarioKey = "F1",
}: SafeProbePlannerProps) {
  return (
    <div className="space-y-6">
      {/* Safety Protocol Banner */}
      <div className="rounded-xl border border-amber-500/30 bg-gradient-to-r from-slate-900/90 via-amber-950/20 to-slate-900/90 p-5 backdrop-blur-md space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="h-9 w-9 rounded-lg bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400">
              <Lock className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-white tracking-tight">
                  Bounded Safe Diagnostic Probe Planner
                </h2>
                <Badge variant="warning" className="text-[10px] py-0 px-1.5 font-mono">
                  READ-ONLY GUARDED
                </Badge>
                <Badge variant="outline" className="text-[10px] py-0 px-1.5 font-mono border-amber-500/30 text-amber-300">
                  {scenarioKey.toUpperCase()}
                </Badge>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Strict safety protocol: Active probe recommendations are presented in preview mode only.
              </p>
            </div>
          </div>

          <Badge
            variant="outline"
            className="border-amber-500/40 text-amber-300 font-mono text-xs px-2.5 py-1 self-start sm:self-auto"
          >
            Execution Permission: DISABLED
          </Badge>
        </div>

        {/* Safety Guarantees Notice */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2 font-mono text-[11px]">
          <div className="p-2.5 rounded bg-slate-950/60 border border-slate-800 flex items-start gap-2">
            <Shield className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
            <span className="text-slate-300">
              Zero Network Mutations: Configuration changes and interface downs are hard-forbidden.
            </span>
          </div>
          <div className="p-2.5 rounded bg-slate-950/60 border border-slate-800 flex items-start gap-2">
            <Activity className="h-4 w-4 text-cyan-400 shrink-0 mt-0.5" />
            <span className="text-slate-300">
              Strict Timeout Bounds: Every probe is constrained to a 5-second maximum timeout.
            </span>
          </div>
          <div className="p-2.5 rounded bg-slate-950/60 border border-slate-800 flex items-start gap-2">
            <ShieldAlert className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
            <span className="text-slate-300">
              Human-in-the-Loop Required: Real execution blocked until authorized backend controller exists.
            </span>
          </div>
        </div>
      </div>

      {/* Recommended Probes Table */}
      <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
        <CardHeader className="pb-3 border-b border-slate-800/80">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Radar className="h-4 w-4 text-cyan-400" />
              <CardTitle className="text-sm font-semibold text-white">
                Recommended Next Probes (Plan Preview)
              </CardTitle>
            </div>
            <Badge variant="outline" className="font-mono text-xs">
              {probePlan?.recommendations.length || 0} Actions Planned
            </Badge>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-slate-950/80 border-b border-slate-800 text-[10px] uppercase text-slate-400 tracking-wider">
                <tr>
                  <th className="py-3 px-4">Probe ID</th>
                  <th className="py-3 px-3">Type</th>
                  <th className="py-3 px-3">Source Node</th>
                  <th className="py-3 px-3">Target Endpoint</th>
                  <th className="py-3 px-3">Timeout</th>
                  <th className="py-3 px-3">Selection Reason & Expected Gain</th>
                  <th className="py-3 px-3 text-right">State</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {probePlan?.recommendations.map((probe) => (
                  <tr key={probe.probe_id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3 px-4 font-semibold text-slate-200">
                      {probe.probe_id}
                    </td>
                    <td className="py-3 px-3">
                      <Badge variant="outline" className="text-[10px] border-cyan-500/30 text-cyan-300">
                        {probe.probe_type}
                      </Badge>
                    </td>
                    <td className="py-3 px-3 font-semibold text-white">
                      {probe.source_router}
                    </td>
                    <td className="py-3 px-3 text-slate-300">
                      {probe.target_address ||
                        probe.target_interface ||
                        probe.target_router ||
                        probe.target_prefix ||
                        "---"}
                    </td>
                    <td className="py-3 px-3 text-slate-400">{probe.timeout_s}s</td>
                    <td className="py-3 px-3 text-slate-300 text-[11px] leading-relaxed max-w-sm">
                      {probe.selection_reason}
                    </td>
                    <td className="py-3 px-3 text-right">
                      <Badge variant="secondary" className="text-[10px] py-0 px-1.5 font-mono">
                        PLANNED (READ-ONLY)
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {(!probePlan || probePlan.recommendations.length === 0) && (
            <div className="p-8 text-center text-slate-500 text-xs font-mono">
              No active diagnostic probes currently recommended for this incident state.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

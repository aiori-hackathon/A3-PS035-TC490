"use client";

import React, { useState } from "react";
import { SnapshotSummary } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Play,
  Film,
  AlertOctagon,
  Radio,
  Lock,
  Layers,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";

interface ScenarioReplayerProps {
  scenarios: SnapshotSummary[];
  activeScenarioKey: string;
  onSelectScenario: (scenarioKey: string) => void;
}

export function ScenarioReplayer({
  scenarios,
  activeScenarioKey,
  onSelectScenario,
}: ScenarioReplayerProps) {
  const [activeCatalogTab, setActiveCatalogTab] = useState<"certified" | "benchmark">("certified");

  const certifiedScenarios = scenarios.filter(
    (s) =>
      s.category === "CERTIFIED_LIVE_EXPERIMENT" ||
      s.scenario_key.startsWith("F")
  );

  const benchmarkScenarios = scenarios.filter(
    (s) =>
      s.category === "BENCHMARK_EVALUATION" ||
      s.scenario_key.startsWith("BENCH") ||
      s.scenario_key === "baseline"
  );

  return (
    <div className="space-y-6">
      {/* Live vs Replay Mode Indicator Banner */}
      <div className="rounded-xl border border-indigo-500/30 bg-gradient-to-r from-slate-900/90 via-indigo-950/20 to-slate-900/90 p-5 backdrop-blur-md space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
              <Film className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-white tracking-tight">
                  Telemetry Snapshot &amp; Replay Catalog
                </h2>
                <Badge
                  variant="default"
                  className="bg-indigo-500/20 border-indigo-500/40 text-indigo-300 font-mono text-[10px]"
                >
                  SOURCE ISOLATION ACTIVE
                </Badge>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Clear architectural distinction between certified live experiments and historical
                benchmark data.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="px-3 py-1.5 rounded-lg bg-slate-950/80 border border-slate-800 text-xs font-mono text-slate-300 flex items-center gap-2">
              <Radio className="h-3 w-3 text-cyan-400 animate-pulse" />
              <span>Active Selection:</span>
              <strong className="text-cyan-300 uppercase">{activeScenarioKey}</strong>
            </div>
          </div>
        </div>

        {/* Clear Distinction Notice */}
        <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80 text-[11px] font-mono text-slate-400 flex items-start gap-2.5">
          <AlertOctagon className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="text-slate-200 font-semibold">Strict Data Lineage Policy:</p>
            <p className="leading-relaxed">
              <strong>Certified Live Experiments (F1–F5):</strong> Represent the 5 formal NEXORA
              laboratory fault scenarios. Only F1 has contemporaneous live capture bindings (Phase 06.4).
              F2–F5 remain in pending capture status until executed in the Containerlab lab by Track A.
              Uncaptured live telemetry is never synthesized or fabricated.
            </p>
            <p className="leading-relaxed text-slate-400">
              <strong>Phase 06 Benchmark Dataset:</strong> Contains historical cross-run evaluation
              telemetry (manifest schema v2.0). These are historical evaluation records and are never
              misrepresented as certified live runs.
            </p>
          </div>
        </div>

        {/* Catalog Category Switcher */}
        <div className="flex items-center gap-2 pt-2 border-t border-slate-800/60">
          <Button
            size="sm"
            variant={activeCatalogTab === "certified" ? "default" : "outline"}
            onClick={() => setActiveCatalogTab("certified")}
            className={`text-xs font-mono ${
              activeCatalogTab === "certified"
                ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                : "border-slate-800 text-slate-400 hover:text-white"
            }`}
          >
            <CheckCircle2 className="h-3.5 w-3.5 mr-1.5 text-cyan-400" />
            Certified Live Experiments (F1–F5)
          </Button>

          <Button
            size="sm"
            variant={activeCatalogTab === "benchmark" ? "default" : "outline"}
            onClick={() => setActiveCatalogTab("benchmark")}
            className={`text-xs font-mono ${
              activeCatalogTab === "benchmark"
                ? "bg-indigo-500/20 text-indigo-300 border-indigo-500/40"
                : "border-slate-800 text-slate-400 hover:text-white"
            }`}
          >
            <Layers className="h-3.5 w-3.5 mr-1.5 text-indigo-400" />
            Phase 06 Benchmark Dataset (Historical)
          </Button>
        </div>
      </div>

      {/* Catalog Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {(activeCatalogTab === "certified" ? certifiedScenarios : benchmarkScenarios).map((sc) => {
          const isSelected = activeScenarioKey.toLowerCase() === sc.scenario_key.toLowerCase();
          const isAvailable = sc.availability !== "UNAVAILABLE_PENDING_CAPTURE";

          return (
            <Card
              key={sc.snapshot_id}
              className={`border transition-all ${
                isSelected
                  ? "border-cyan-500/50 bg-cyan-950/15 shadow-lg shadow-cyan-950/30 ring-1 ring-cyan-500/30"
                  : isAvailable
                  ? "border-slate-800 bg-slate-900/60 hover:border-slate-700"
                  : "border-slate-800/50 bg-slate-950/40 opacity-80"
              }`}
            >
              <CardHeader className="pb-3 border-b border-slate-800/60">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-6 w-6 rounded flex items-center justify-center font-mono font-bold text-xs ${
                        sc.category === "CERTIFIED_LIVE_EXPERIMENT"
                          ? isAvailable
                            ? "bg-cyan-500/20 text-cyan-400 border border-cyan-500/30"
                            : "bg-slate-800 text-slate-500 border border-slate-700"
                          : "bg-indigo-500/20 text-indigo-400 border border-indigo-500/30"
                      }`}
                    >
                      {sc.certified_fault_id ? sc.certified_fault_id.split("_")[0] : "B"}
                    </span>
                    <CardTitle className="text-sm font-semibold text-white">
                      {sc.name}
                    </CardTitle>
                  </div>

                  {isSelected && (
                    <Badge variant="success" className="text-[10px] py-0 px-1.5 font-mono">
                      ACTIVE
                    </Badge>
                  )}
                  {!isAvailable && (
                    <Badge variant="outline" className="text-[9px] py-0 px-1.5 font-mono border-amber-500/30 text-amber-400">
                      CAPTURE PENDING
                    </Badge>
                  )}
                </div>
              </CardHeader>

              <CardContent className="p-4 space-y-3 text-xs">
                <p className="text-slate-400 text-[11px] leading-relaxed min-h-[38px]">
                  {sc.description}
                </p>

                {/* Target / Availability Metadata */}
                <div className="space-y-1.5 pt-2 border-t border-slate-800/60 font-mono text-[10px] text-slate-500">
                  {sc.target_component && (
                    <div className="flex justify-between">
                      <span>Target Component:</span>
                      <span className="text-white font-semibold">{sc.target_component}</span>
                    </div>
                  )}

                  <div className="flex justify-between">
                    <span>Data Lineage:</span>
                    <Badge
                      variant="secondary"
                      className="text-[9px] py-0 px-1 font-mono bg-slate-950 text-slate-400 border border-slate-800"
                    >
                      {sc.data_source}
                    </Badge>
                  </div>

                  <div className="flex justify-between">
                    <span>Records:</span>
                    <span className="text-cyan-300 font-semibold">
                      {isAvailable ? `${sc.record_count} observations` : "Awaiting lab run"}
                    </span>
                  </div>

                  {sc.captured_at && (
                    <div className="flex justify-between">
                      <span>Capture Date:</span>
                      <span className="text-slate-400">
                        {new Date(sc.captured_at).toLocaleDateString()}
                      </span>
                    </div>
                  )}
                </div>

                {/* Unavailability Notice */}
                {!isAvailable && sc.unavailable_reason && (
                  <div className="p-2 rounded bg-amber-950/20 border border-amber-500/20 text-[10px] font-mono text-amber-300/80 flex items-start gap-1.5">
                    <AlertCircle className="h-3.5 w-3.5 text-amber-400 shrink-0 mt-0.5" />
                    <span>{sc.unavailable_reason}</span>
                  </div>
                )}

                {/* Action Button */}
                {isAvailable ? (
                  <Button
                    variant={isSelected ? "default" : "outline"}
                    size="sm"
                    onClick={() => onSelectScenario(sc.scenario_key)}
                    className={`w-full text-xs font-mono mt-2 ${
                      isSelected
                        ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                        : "border-slate-800 bg-slate-950/60 text-slate-300 hover:text-white"
                    }`}
                  >
                    <Play className="h-3 w-3 mr-1.5" />
                    {isSelected ? "Replaying Now" : "Load Scenario"}
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled
                    className="w-full text-xs font-mono mt-2 border-slate-800 bg-slate-950/40 text-slate-600 cursor-not-allowed"
                  >
                    <Lock className="h-3 w-3 mr-1.5 text-slate-600" />
                    Capture Pending in Lab
                  </Button>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

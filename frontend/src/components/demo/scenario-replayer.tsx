"use client";

import React from "react";
import { SnapshotSummary } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Play,
  Film,
  AlertOctagon,
  Radio,
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
                  Deterministic Evaluation Scenario Replay
                </h2>
                <Badge
                  variant="default"
                  className="bg-indigo-500/20 border-indigo-500/40 text-indigo-300 font-mono text-[10px]"
                >
                  DEMO REPLAY ARCHIVE
                </Badge>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Replaying verified FRRouting telemetry snapshots from held-out evaluation datasets.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="px-3 py-1.5 rounded-lg bg-slate-950/80 border border-slate-800 text-xs font-mono text-slate-300 flex items-center gap-2">
              <Radio className="h-3 w-3 text-indigo-400 animate-pulse" />
              <span>Current Replay:</span>
              <strong className="text-cyan-300 uppercase">{activeScenarioKey}</strong>
            </div>
          </div>
        </div>

        {/* Clear Distinction Notice */}
        <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80 text-[11px] font-mono text-slate-400 flex items-start gap-2">
          <AlertOctagon className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
          <span>
            <strong className="text-slate-200">Strict Source-of-Truth Separation:</strong>{" "}
            All displayed metrics, topology states, and diagnostic evidence in this mode originate from verified evaluation fixtures. They are never conflated with live lab execution.
          </span>
        </div>
      </div>

      {/* Available Scenario Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {scenarios.map((sc) => {
          const isSelected = activeScenarioKey.toLowerCase() === sc.scenario_key.toLowerCase();
          const isBaseline = sc.scenario_key.toLowerCase() === "baseline";

          return (
            <Card
              key={sc.snapshot_id}
              className={`border transition-all cursor-pointer ${
                isSelected
                  ? "border-cyan-500/50 bg-cyan-950/10 shadow-lg shadow-cyan-950/20"
                  : "border-slate-800 bg-slate-900/60 hover:border-slate-700"
              }`}
              onClick={() => onSelectScenario(sc.scenario_key)}
            >
              <CardHeader className="pb-3 border-b border-slate-800/60">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-6 w-6 rounded flex items-center justify-center font-mono font-bold text-xs ${
                        isBaseline
                          ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                          : "bg-rose-500/20 text-rose-400 border border-rose-500/30"
                      }`}
                    >
                      {sc.scenario_key.toUpperCase()}
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
                </div>
              </CardHeader>

              <CardContent className="p-4 space-y-3 text-xs">
                <p className="text-slate-400 text-[11px] leading-relaxed min-h-[34px]">
                  {sc.description}
                </p>

                <div className="space-y-1.5 pt-2 border-t border-slate-800/60 font-mono text-[10px] text-slate-500">
                  <div className="flex justify-between">
                    <span>Snapshot ID:</span>
                    <span className="text-slate-400 truncate max-w-[150px]">
                      {sc.snapshot_id}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Evidence Records:</span>
                    <span className="text-cyan-300 font-semibold">
                      {sc.record_count} items
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Capture Date:</span>
                    <span className="text-slate-400">
                      {new Date(sc.captured_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>

                <Button
                  variant={isSelected ? "default" : "outline"}
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectScenario(sc.scenario_key);
                  }}
                  className={`w-full text-xs font-mono mt-2 ${
                    isSelected
                      ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                      : "border-slate-800 bg-slate-950/60 text-slate-300 hover:text-white"
                  }`}
                >
                  <Play className="h-3 w-3 mr-1.5" />
                  {isSelected ? "Replaying Now" : "Replay Scenario"}
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

import React from "react";
import { AlertTriangle, ServerCrash, Cpu, Network, Layers } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function NetworkLabCard() {
  return (
    <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400">
              <Network className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-base text-white">
                5-Node Router Topology
              </CardTitle>
              <CardDescription className="text-xs text-slate-400">
                FRRouting / OSPFv2 Containerlab Network Laboratory
              </CardDescription>
            </div>
          </div>
          <Badge variant="warning" className="text-xs">
            Standby
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Explicit Required Notice */}
        <div className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-4 flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <h4 className="text-sm font-semibold text-amber-200">
              Network lab not configured.
            </h4>
            <p className="text-xs text-amber-300/80 leading-relaxed">
              No live router telemetry or Containerlab topology instance is currently active.
              Phase 00 establishes the verified software architecture and API contracts.
              The five FRRouting OSPFv2 router containers and Linux netem fault injection harness
              will be initialized in Phase 01.
            </p>
          </div>
        </div>

        {/* Planned Router Specification Table */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-400 px-1">
            <span className="font-medium">Planned Laboratory Routers (PS-035)</span>
            <span className="font-mono text-[11px] text-slate-500">5 Nodes Scheduled</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-5 gap-2">
            {[
              { id: "R1", role: "Core Gateway", as: "AS65001" },
              { id: "R2", role: "Aggregation-A", as: "AS65001" },
              { id: "R3", role: "Aggregation-B", as: "AS65001" },
              { id: "R4", role: "Edge Router", as: "AS65001" },
              { id: "R5", role: "Peer / Transit", as: "AS65001" },
            ].map((node) => (
              <div
                key={node.id}
                className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 flex flex-col justify-between"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-slate-200 text-sm">
                    {node.id}
                  </span>
                  <span className="h-1.5 w-1.5 rounded-full bg-slate-600" />
                </div>
                <div className="mt-2">
                  <p className="text-[11px] text-slate-400 truncate">{node.role}</p>
                  <p className="text-[10px] font-mono text-slate-500">{node.as}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Specification Metadata */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2 text-xs">
          <div className="rounded-lg border border-slate-800/80 bg-slate-950/30 p-2.5 flex items-center gap-2 text-slate-400">
            <Cpu className="h-4 w-4 text-cyan-400 shrink-0" />
            <div>
              <p className="text-slate-300 font-medium text-[11px]">Control Plane</p>
              <p className="text-[10px] text-slate-500">FRR OSPFv2 Routing</p>
            </div>
          </div>
          <div className="rounded-lg border border-slate-800/80 bg-slate-950/30 p-2.5 flex items-center gap-2 text-slate-400">
            <Layers className="h-4 w-4 text-emerald-400 shrink-0" />
            <div>
              <p className="text-slate-300 font-medium text-[11px]">Fault Harness</p>
              <p className="text-[10px] text-slate-500">Linux tc/netem Emulation</p>
            </div>
          </div>
          <div className="rounded-lg border border-slate-800/80 bg-slate-950/30 p-2.5 flex items-center gap-2 text-slate-400">
            <ServerCrash className="h-4 w-4 text-indigo-400 shrink-0" />
            <div>
              <p className="text-slate-300 font-medium text-[11px]">Isolation Level</p>
              <p className="text-[10px] text-slate-500">Strict Label Isolation</p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

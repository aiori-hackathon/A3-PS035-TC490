"use client";

import React, { useState, useMemo } from "react";
import { EvidenceRecord } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Search,
  FileText,
  Terminal,
  X,
} from "lucide-react";

interface EvidenceExplorerProps {
  evidenceItems: EvidenceRecord[];
  activeScenarioKey?: string;
  initialSearchQuery?: string | null;
}

export function EvidenceExplorer({
  evidenceItems,
  activeScenarioKey = "F1",
  initialSearchQuery = null,
}: EvidenceExplorerProps) {
  const [userQuery, setUserQuery] = useState<string | null>(null);
  const [prevInitial, setPrevInitial] = useState(initialSearchQuery);
  if (initialSearchQuery !== prevInitial) {
    setPrevInitial(initialSearchQuery);
    setUserQuery(null);
  }
  const searchQuery = userQuery !== null ? userQuery : (initialSearchQuery || "");

  const [selectedRouter, setSelectedRouter] = useState<string>("ALL");
  const [selectedSourceType, setSelectedSourceType] = useState<string>("ALL");
  const [inspectingRecord, setInspectingRecord] = useState<EvidenceRecord | null>(null);

  // Available unique routers and source types
  const routerOptions = ["ALL", "R1", "R2", "R3", "R4", "R5"];
  const sourceTypes = useMemo(() => {
    const set = new Set<string>();
    evidenceItems.forEach((it) => {
      if (it.source_type) set.add(it.source_type);
    });
    return ["ALL", ...Array.from(set)];
  }, [evidenceItems]);

  const filteredItems = useMemo(() => {
    return evidenceItems.filter((item) => {
      if (selectedRouter !== "ALL" && item.source_router !== selectedRouter) {
        return false;
      }
      if (selectedSourceType !== "ALL" && item.source_type !== selectedSourceType) {
        return false;
      }
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        const matchId = item.evidence_id.toLowerCase().includes(query);
        const matchEvent = item.event_type.toLowerCase().includes(query);
        const matchRef = item.raw_reference?.toLowerCase().includes(query);
        if (!matchId && !matchEvent && !matchRef) return false;
      }
      return true;
    });
  }, [evidenceItems, selectedRouter, selectedSourceType, searchQuery]);

  return (
    <div className="space-y-6">
      {/* Header and Controls */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 backdrop-blur-md space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-cyan-400" />
            <h2 className="text-base font-semibold text-white tracking-tight">
              Evidence Explorer & Provenance Log
            </h2>
          </div>
          <Badge variant="outline" className="text-xs font-mono border-slate-700 text-slate-300">
            Scenario: <span className="text-cyan-400 font-semibold ml-1 uppercase">{activeScenarioKey}</span> • {evidenceItems.length} Records
          </Badge>
        </div>

        {/* Filter Bar */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-3 pt-2">
          {/* Search Box */}
          <div className="md:col-span-5 relative">
            <Search className="h-4 w-4 absolute left-3 top-2.5 text-slate-500" />
            <input
              type="text"
              placeholder="Search evidence ID, event, command..."
              value={searchQuery}
              onChange={(e) => setUserQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 rounded-lg bg-slate-950/70 border border-slate-800 text-xs font-mono text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
            />
          </div>

          {/* Router Filter */}
          <div className="md:col-span-3 flex items-center gap-1.5 overflow-x-auto">
            <span className="text-[11px] text-slate-500 font-mono">Node:</span>
            {routerOptions.map((rid) => (
              <Button
                key={rid}
                size="sm"
                variant={selectedRouter === rid ? "default" : "outline"}
                onClick={() => setSelectedRouter(rid)}
                className={`text-[11px] font-mono px-2 h-7 ${
                  selectedRouter === rid
                    ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                    : "border-slate-800 bg-slate-950/40 text-slate-400 hover:text-white"
                }`}
              >
                {rid}
              </Button>
            ))}
          </div>

          {/* Source Type Filter */}
          <div className="md:col-span-4 flex items-center gap-1.5 overflow-x-auto">
            <span className="text-[11px] text-slate-500 font-mono">Type:</span>
            <select
              value={selectedSourceType}
              onChange={(e) => setSelectedSourceType(e.target.value)}
              className="bg-slate-950/70 border border-slate-800 text-xs font-mono text-slate-300 rounded px-2.5 py-1 focus:outline-none focus:border-cyan-500/50"
            >
              {sourceTypes.map((st) => (
                <option key={st} value={st}>
                  {st}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Main Table & Detail View */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className={inspectingRecord ? "lg:col-span-7" : "lg:col-span-12"}>
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden backdrop-blur-md">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-950/80 border-b border-slate-800 text-[10px] uppercase text-slate-400 tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Evidence ID</th>
                    <th className="py-3 px-3">Node</th>
                    <th className="py-3 px-3">Origin</th>
                    <th className="py-3 px-3">Event Type</th>
                    <th className="py-3 px-3">Observed UTC</th>
                    <th className="py-3 px-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {filteredItems.slice(0, 30).map((record) => {
                    const isSelected = inspectingRecord?.evidence_id === record.evidence_id;
                    const isError =
                      record.event_type.includes("DOWN") ||
                      record.event_type.includes("UNREACHABLE") ||
                      record.event_type.includes("FAILURE");

                    return (
                      <tr
                        key={record.evidence_id}
                        className={`hover:bg-slate-800/40 transition-colors ${
                          isSelected ? "bg-cyan-950/20" : ""
                        }`}
                      >
                        <td className="py-2.5 px-4 font-semibold text-slate-200 truncate max-w-[200px]">
                          {record.evidence_id}
                        </td>
                        <td className="py-2.5 px-3">
                          <Badge variant="outline" className="text-[10px] py-0 px-1.5 border-slate-700 text-cyan-300">
                            {record.source_router}
                          </Badge>
                        </td>
                        <td className="py-2.5 px-3 text-slate-400 text-[11px]">
                          {record.source_type}
                        </td>
                        <td className="py-2.5 px-3">
                          <span
                            className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                              isError
                                ? "bg-rose-500/10 text-rose-400 border border-rose-500/30"
                                : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                            }`}
                          >
                            {record.event_type}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-slate-400 text-[11px]">
                          {new Date(record.observed_at).toLocaleTimeString()}
                        </td>
                        <td className="py-2.5 px-3 text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setInspectingRecord(record)}
                            className="h-6 text-[10px] px-2 text-slate-400 hover:text-white"
                          >
                            Inspect
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {filteredItems.length === 0 && (
              <div className="p-8 text-center text-slate-500 text-xs">
                No evidence records matched your search filters.
              </div>
            )}
          </div>
        </div>

        {/* Detail Inspection Modal/Drawer */}
        {inspectingRecord && (
          <div className="lg:col-span-5 space-y-4">
            <Card className="border-slate-800 bg-slate-900/80 backdrop-blur-md">
              <CardHeader className="pb-3 border-b border-slate-800 flex flex-row items-center justify-between">
                <div>
                  <span className="text-[10px] font-mono uppercase text-cyan-400 font-semibold">
                    Evidence Record Detail
                  </span>
                  <CardTitle className="text-sm font-mono text-white truncate max-w-[280px]">
                    {inspectingRecord.evidence_id}
                  </CardTitle>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setInspectingRecord(null)}
                  className="h-6 w-6 text-slate-400 hover:text-white"
                >
                  <X className="h-4 w-4" />
                </Button>
              </CardHeader>

              <CardContent className="p-4 space-y-3 text-xs font-mono">
                <div className="bg-slate-950/60 p-3 rounded-lg border border-slate-800 space-y-2">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Source Router:</span>
                    <span className="text-cyan-300 font-semibold">
                      {inspectingRecord.source_router}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Collector Type:</span>
                    <span className="text-slate-300">
                      {inspectingRecord.source_type}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Collection Method:</span>
                    <span className="text-slate-300">
                      {inspectingRecord.collection_method}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Observed Time:</span>
                    <span className="text-slate-300">
                      {inspectingRecord.observed_at}
                    </span>
                  </div>
                </div>

                {/* Raw Reference Command */}
                {inspectingRecord.raw_reference && (
                  <div className="space-y-1">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
                      Raw Query Command
                    </span>
                    <div className="p-2.5 rounded bg-slate-950 border border-slate-800 text-emerald-400 text-[11px] overflow-x-auto flex items-center gap-2">
                      <Terminal className="h-3.5 w-3.5 shrink-0 text-slate-500" />
                      <code>{inspectingRecord.raw_reference}</code>
                    </div>
                  </div>
                )}

                {/* Additional Properties */}
                <div className="space-y-1">
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
                    Captured Observations
                  </span>
                  <div className="bg-slate-950/40 p-2.5 rounded border border-slate-800 space-y-1.5 text-[11px]">
                    {inspectingRecord.source_interface && (
                      <p className="flex justify-between">
                        <span className="text-slate-400">Interface:</span>
                        <span className="text-white">{inspectingRecord.source_interface}</span>
                      </p>
                    )}
                    {inspectingRecord.observed_status && (
                      <p className="flex justify-between">
                        <span className="text-slate-400">Status:</span>
                        <span className="text-rose-400 font-semibold">{inspectingRecord.observed_status}</span>
                      </p>
                    )}
                    {inspectingRecord.neighbour_router_id && (
                      <p className="flex justify-between">
                        <span className="text-slate-400">Neighbour ID:</span>
                        <span className="text-cyan-300">{inspectingRecord.neighbour_router_id}</span>
                      </p>
                    )}
                    {inspectingRecord.target_address && (
                      <p className="flex justify-between">
                        <span className="text-slate-400">Target IP:</span>
                        <span className="text-white">{inspectingRecord.target_address}</span>
                      </p>
                    )}
                    {inspectingRecord.packet_loss_pct !== undefined && (
                      <p className="flex justify-between">
                        <span className="text-slate-400">Packet Loss:</span>
                        <span className="text-rose-400 font-bold">{inspectingRecord.packet_loss_pct}%</span>
                      </p>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}

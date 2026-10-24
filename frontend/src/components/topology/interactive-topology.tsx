"use client";

import React, { useState } from "react";
import {
  RouterInfo,
  NetworkLinkInfo,
  TopologyStatus,
} from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Server,
  Activity,
  Layers,
  Network,
  Info,
} from "lucide-react";

interface InteractiveTopologyProps {
  routers: RouterInfo[];
  links: NetworkLinkInfo[];
  topologyStatus: TopologyStatus | null;
  selectedRouterId?: string | null;
  selectedLinkId?: string | null;
  onSelectRouter?: (routerId: string) => void;
  onSelectLink?: (linkId: string) => void;
  scenarioKey?: string;
}

// Pentagonal coordinates for 500x500 SVG
const NODE_COORDINATES: Record<string, { x: number; y: number }> = {
  R1: { x: 250, y: 75 },
  R2: { x: 420, y: 195 },
  R3: { x: 355, y: 400 },
  R4: { x: 145, y: 400 },
  R5: { x: 80, y: 195 },
};

export function InteractiveTopology({
  routers,
  links,
  topologyStatus,
  selectedRouterId,
  selectedLinkId,
  onSelectRouter,
  onSelectLink,
  scenarioKey = "baseline",
}: InteractiveTopologyProps) {
  const [activeRouterId, setActiveRouterId] = useState<string | null>(
    selectedRouterId || "R1"
  );
  const [activeLinkId, setActiveLinkId] = useState<string | null>(
    selectedLinkId || null
  );

  const handleRouterClick = (rid: string) => {
    setActiveRouterId(rid);
    setActiveLinkId(null);
    onSelectRouter?.(rid);
  };

  const handleLinkClick = (lid: string) => {
    setActiveLinkId(lid);
    setActiveRouterId(null);
    onSelectLink?.(lid);
  };

  const activeRouter = routers.find((r) => r.router_id === activeRouterId);
  const activeLink = links.find((l) => l.link_id === activeLinkId);

  const getLinkStatus = (linkId: string) => {
    if (!topologyStatus) return "HEALTHY";
    return topologyStatus.link_statuses[linkId] || "HEALTHY";
  };

  const getRouterStatus = (routerId: string) => {
    if (!topologyStatus) return "UP";
    return topologyStatus.router_statuses[routerId] || "UP";
  };

  return (
    <div className="space-y-6">
      {/* Topology Header & Overview Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-900/60 border border-slate-800 rounded-xl p-4 backdrop-blur-md">
        <div>
          <div className="flex items-center gap-2">
            <Network className="h-5 w-5 text-cyan-400" />
            <h2 className="text-base font-semibold text-white tracking-tight">
              5-Node FRRouting / OSPFv2 Ring Topology
            </h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Real physical point-to-point links (10.0.X.0/30) with Area 0.0.0.0 OSPF adjacencies.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className="font-mono text-xs px-2.5 py-1 bg-slate-950/80 border-slate-700 text-slate-300"
          >
            Scenario:{" "}
            <span className="text-cyan-400 font-semibold ml-1 uppercase">
              {scenarioKey}
            </span>
          </Badge>
          <Badge
            variant="outline"
            className="text-xs px-2.5 py-1 bg-cyan-950/40 border-cyan-500/30 text-cyan-300 font-mono"
          >
            5 Routers • 5 Links
          </Badge>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* SVG Interactive Canvas */}
        <div className="lg:col-span-7 bg-slate-950/80 border border-slate-800 rounded-xl p-4 relative overflow-hidden flex flex-col items-center justify-center min-h-[480px]">
          {/* Subtle Grid Pattern */}
          <div className="absolute inset-0 bg-operations-grid opacity-30 pointer-events-none" />

          {/* Central Legend / Notice */}
          <div className="absolute top-3 left-3 z-10 text-[11px] font-mono text-slate-500 bg-slate-900/80 border border-slate-800/80 px-2.5 py-1 rounded">
            Click router or link to inspect
          </div>

          <svg
            viewBox="0 0 500 500"
            className="w-full max-w-[480px] h-auto select-none relative z-10"
          >
            {/* Draw Links First (Behind nodes) */}
            {links.map((lnk) => {
              const srcCoord = NODE_COORDINATES[lnk.router_a];
              const dstCoord = NODE_COORDINATES[lnk.router_b];
              if (!srcCoord || !dstCoord) return null;

              const status = getLinkStatus(lnk.link_id);
              const isSelected = activeLinkId === lnk.link_id;

              let strokeColor = "#10b981"; // Emerald healthy
              let strokeDash = "none";
              let animationClass = "";

              if (status === "DOWN") {
                strokeColor = "#f43f5e"; // Rose down
                strokeDash = "8 6";
                animationClass = "animate-pulse";
              } else if (status === "DEGRADED") {
                strokeColor = "#f59e0b"; // Amber degraded
                strokeDash = "6 4";
              }

              if (isSelected) {
                strokeColor = "#38bdf8"; // Cyan selected
              }

              // Calculate midpoint for link label
              const midX = (srcCoord.x + dstCoord.x) / 2;
              const midY = (srcCoord.y + dstCoord.y) / 2;

              return (
                <g
                  key={lnk.link_id}
                  className="cursor-pointer group"
                  onClick={() => handleLinkClick(lnk.link_id)}
                >
                  {/* Invisible thicker hit-box */}
                  <line
                    x1={srcCoord.x}
                    y1={srcCoord.y}
                    x2={dstCoord.x}
                    y2={dstCoord.y}
                    stroke="transparent"
                    strokeWidth="24"
                  />

                  {/* Main Link Line */}
                  <line
                    x1={srcCoord.x}
                    y1={srcCoord.y}
                    x2={dstCoord.x}
                    y2={dstCoord.y}
                    stroke={strokeColor}
                    strokeWidth={isSelected ? "4" : "2.5"}
                    strokeDasharray={strokeDash}
                    className={`transition-all duration-300 ${animationClass}`}
                  />

                  {/* Link Label Pill */}
                  <g transform={`translate(${midX}, ${midY})`}>
                    <rect
                      x="-22"
                      y="-10"
                      width="44"
                      height="20"
                      rx="4"
                      fill="#090d16"
                      stroke={isSelected ? "#38bdf8" : strokeColor}
                      strokeWidth="1.2"
                      className="group-hover:scale-110 transition-transform origin-center"
                    />
                    <text
                      textAnchor="middle"
                      dy="4"
                      fill="#f8fafc"
                      fontSize="9.5"
                      fontFamily="monospace"
                      fontWeight="bold"
                    >
                      {lnk.link_id}
                    </text>
                  </g>
                </g>
              );
            })}

            {/* Draw Routers (In front of links) */}
            {routers.map((r) => {
              const coord = NODE_COORDINATES[r.router_id];
              if (!coord) return null;

              const status = getRouterStatus(r.router_id);
              const isSelected = activeRouterId === r.router_id;

              let ringColor = "rgba(16, 185, 129, 0.4)";
              let centerBg = "#0f172a";
              let statusFill = "#10b981";

              if (status === "DOWN") {
                ringColor = "rgba(244, 63, 94, 0.6)";
                centerBg = "#270811";
                statusFill = "#f43f5e";
              }

              if (isSelected) {
                ringColor = "rgba(56, 189, 248, 0.8)";
              }

              return (
                <g
                  key={r.router_id}
                  transform={`translate(${coord.x}, ${coord.y})`}
                  className="cursor-pointer group"
                  onClick={() => handleRouterClick(r.router_id)}
                >
                  {/* Outer Pulse Halo on Hover or Selected */}
                  <circle
                    r={isSelected ? "34" : "30"}
                    fill={ringColor}
                    className="transition-all duration-300 group-hover:scale-110"
                  />

                  {/* Main Node Circle */}
                  <circle
                    r="24"
                    fill={centerBg}
                    stroke={isSelected ? "#38bdf8" : statusFill}
                    strokeWidth={isSelected ? "3" : "2"}
                  />

                  {/* Router ID Label */}
                  <text
                    textAnchor="middle"
                    dy="5"
                    fill="#f8fafc"
                    fontSize="13"
                    fontFamily="monospace"
                    fontWeight="bold"
                  >
                    {r.router_id}
                  </text>

                  {/* Status Indicator Dot */}
                  <circle
                    cx="16"
                    cy="-16"
                    r="5"
                    fill={statusFill}
                    stroke="#020617"
                    strokeWidth="1.5"
                  />

                  {/* IP Sub-Label under Node */}
                  <text
                    textAnchor="middle"
                    dy="40"
                    fill="#94a3b8"
                    fontSize="10"
                    fontFamily="monospace"
                  >
                    {r.loopback_address.replace("/32", "")}
                  </text>
                </g>
              );
            })}
          </svg>

          {/* Quick Legend Bar */}
          <div className="flex items-center gap-4 mt-2 text-[11px] font-mono text-slate-400 bg-slate-900/90 border border-slate-800 px-3 py-1.5 rounded-lg z-10">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-500" /> Healthy
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-amber-500" /> Degraded
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-rose-500" /> Down
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-cyan-400" /> Selected
            </span>
          </div>
        </div>

        {/* Detailed Component Inspector Drawer */}
        <div className="lg:col-span-5 space-y-4">
          {activeRouter && (
            <Card className="border-slate-800 bg-slate-900/70 backdrop-blur-md">
              <CardHeader className="pb-3 border-b border-slate-800/80">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="h-9 w-9 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
                      <Server className="h-4 w-4" />
                    </div>
                    <div>
                      <CardTitle className="text-base font-mono text-white">
                        Router {activeRouter.router_id}
                      </CardTitle>
                      <p className="text-xs text-slate-400">{activeRouter.role}</p>
                    </div>
                  </div>

                  <Badge
                    variant={
                      getRouterStatus(activeRouter.router_id) === "UP"
                        ? "success"
                        : "destructive"
                    }
                    className="font-mono text-[11px]"
                  >
                    {getRouterStatus(activeRouter.router_id)}
                  </Badge>
                </div>
              </CardHeader>

              <CardContent className="p-4 space-y-4 text-xs">
                {/* Protocol Identity */}
                <div className="grid grid-cols-2 gap-2 bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                  <div>
                    <span className="text-[10px] text-slate-500 font-mono uppercase">
                      OSPF Router-ID
                    </span>
                    <p className="font-mono text-cyan-300 font-semibold mt-0.5">
                      {activeRouter.ospf_router_id}
                    </p>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 font-mono uppercase">
                      Loopback IP
                    </span>
                    <p className="font-mono text-slate-200 font-semibold mt-0.5">
                      {activeRouter.loopback_address}
                    </p>
                  </div>
                </div>

                {/* Interfaces List */}
                <div className="space-y-2">
                  <span className="text-[11px] font-semibold text-slate-300 uppercase tracking-wider font-mono">
                    Configured Interfaces
                  </span>
                  <div className="space-y-1.5">
                    {activeRouter.interfaces.map((iface) => (
                      <div
                        key={iface.interface_name}
                        className="flex items-center justify-between p-2 rounded bg-slate-950/40 border border-slate-800/60 font-mono"
                      >
                        <div className="flex items-center gap-2">
                          <Layers className="h-3.5 w-3.5 text-slate-500" />
                          <span className="font-semibold text-slate-200">
                            {iface.interface_name}
                          </span>
                        </div>
                        <span className="text-slate-400">
                          {iface.ipv4_address || "unnumbered"}
                        </span>
                        <Badge
                          variant={iface.status === "UP" ? "success" : "destructive"}
                          className="text-[9px] px-1.5 py-0"
                        >
                          {iface.status}
                        </Badge>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Connected Ring Links */}
                <div className="space-y-2">
                  <span className="text-[11px] font-semibold text-slate-300 uppercase tracking-wider font-mono">
                    Connected Links
                  </span>
                  <div className="grid grid-cols-2 gap-2">
                    {links
                      .filter(
                        (lnk) =>
                          lnk.router_a === activeRouter.router_id ||
                          lnk.router_b === activeRouter.router_id
                      )
                      .map((lnk) => (
                        <Button
                          key={lnk.link_id}
                          variant="outline"
                          size="sm"
                          onClick={() => handleLinkClick(lnk.link_id)}
                          className="justify-between text-xs font-mono border-slate-800 bg-slate-950/40 hover:bg-slate-800 text-slate-300"
                        >
                          <span>{lnk.link_id}</span>
                          <span className="text-[10px] text-slate-500">
                            {lnk.router_a === activeRouter.router_id
                              ? `→ ${lnk.router_b}`
                              : `→ ${lnk.router_a}`}
                          </span>
                        </Button>
                      ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {activeLink && (
            <Card className="border-slate-800 bg-slate-900/70 backdrop-blur-md">
              <CardHeader className="pb-3 border-b border-slate-800/80">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="h-9 w-9 rounded-lg bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
                      <Activity className="h-4 w-4" />
                    </div>
                    <div>
                      <CardTitle className="text-base font-mono text-white">
                        Link {activeLink.link_id}
                      </CardTitle>
                      <p className="text-xs text-slate-400">
                        {activeLink.router_a} ↔ {activeLink.router_b} Point-to-Point
                      </p>
                    </div>
                  </div>

                  <Badge
                    variant={
                      getLinkStatus(activeLink.link_id) === "HEALTHY"
                        ? "success"
                        : getLinkStatus(activeLink.link_id) === "DEGRADED"
                        ? "warning"
                        : "destructive"
                    }
                    className="font-mono text-[11px]"
                  >
                    {getLinkStatus(activeLink.link_id)}
                  </Badge>
                </div>
              </CardHeader>

              <CardContent className="p-4 space-y-4 text-xs font-mono">
                {/* Subnet & Metric */}
                <div className="grid grid-cols-2 gap-2 bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase">Subnet</span>
                    <p className="text-cyan-300 font-semibold mt-0.5">
                      {activeLink.subnet}
                    </p>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase">OSPF Metric</span>
                    <p className="text-slate-200 font-semibold mt-0.5">
                      Cost {activeLink.ospf_cost}
                    </p>
                  </div>
                </div>

                {/* Endpoints Detail */}
                <div className="space-y-2">
                  <span className="text-[11px] font-semibold text-slate-300 uppercase tracking-wider">
                    Interface Endpoints
                  </span>
                  <div className="space-y-2">
                    <div className="p-2.5 rounded bg-slate-950/40 border border-slate-800/70 flex items-center justify-between">
                      <div>
                        <span className="text-cyan-400 font-semibold">
                          {activeLink.router_a}
                        </span>{" "}
                        <span className="text-slate-500">
                          ({activeLink.interface_a})
                        </span>
                      </div>
                      <span className="text-slate-300">{activeLink.address_a}</span>
                    </div>

                    <div className="p-2.5 rounded bg-slate-950/40 border border-slate-800/70 flex items-center justify-between">
                      <div>
                        <span className="text-cyan-400 font-semibold">
                          {activeLink.router_b}
                        </span>{" "}
                        <span className="text-slate-500">
                          ({activeLink.interface_b})
                        </span>
                      </div>
                      <span className="text-slate-300">{activeLink.address_b}</span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Quick Topology Metrics */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-2 text-xs">
            <div className="flex items-center gap-1.5 text-slate-300 font-semibold">
              <Info className="h-4 w-4 text-cyan-400" />
              <span>Topology Properties</span>
            </div>
            <ul className="text-slate-400 space-y-1 text-[11px] list-disc list-inside">
              <li>5-node full ring architecture with symmetric /30 link allocation.</li>
              <li>Single OSPF area (0.0.0.0) with point-to-point network type.</li>
              <li>Read-only inspection safely isolated from network mutations.</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

"use client";

import React from "react";
import {
  Activity,
  Network,
  GitBranch,
  ShieldCheck,
  Radar,
  FileCheck2,
  Film,
  Terminal,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";

export type DashboardTab =
  | "overview"
  | "topology"
  | "investigation"
  | "evidence"
  | "verification"
  | "probes"
  | "replay";

interface NavItem {
  id: DashboardTab;
  name: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
  badgeVariant?: "default" | "secondary" | "success" | "warning";
}

const navItems: NavItem[] = [
  {
    id: "overview",
    name: "Operations Center",
    icon: Activity,
    badge: "Live Hub",
  },
  {
    id: "topology",
    name: "5-Node Topology",
    icon: Network,
    badge: "Interactive",
  },
  {
    id: "investigation",
    name: "Incident Investigation",
    icon: GitBranch,
    badge: "Ranked",
  },
  {
    id: "evidence",
    name: "Evidence Explorer",
    icon: FileCheck2,
    badge: "Audit Log",
  },
  {
    id: "verification",
    name: "Counterfactuals",
    icon: ShieldCheck,
    badge: "Proof",
  },
  {
    id: "probes",
    name: "Safe Active Probes",
    icon: Radar,
    badge: "Guarded",
  },
  {
    id: "replay",
    name: "Scenario Replayer",
    icon: Film,
    badge: "F1–F5",
  },
];

interface SidebarProps {
  activeTab?: DashboardTab;
  onTabChange?: (tab: DashboardTab) => void;
  scenarioKey?: string;
}

export function Sidebar({
  activeTab = "overview",
  onTabChange,
  scenarioKey = "baseline",
}: SidebarProps) {
  return (
    <aside className="w-64 bg-slate-950/95 border-r border-slate-800 flex flex-col shrink-0 min-h-screen select-none">
      {/* Branding Header */}
      <div className="p-5 border-b border-slate-800/80">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 shadow-inner">
            <Terminal className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-base tracking-wider text-white">NEXORA</span>
              <Badge variant="default" className="text-[9px] px-1 py-0 font-mono">v0.1.0</Badge>
            </div>
            <p className="text-[11px] text-slate-400 font-mono">PS-035 Operations</p>
          </div>
        </div>

        <div className="mt-3 pt-2.5 border-t border-slate-800/60">
          <p className="text-[10px] font-mono text-cyan-400 uppercase tracking-wider">
            From Correlation to Verification
          </p>
        </div>
      </div>

      {/* Navigation Modules */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <p className="px-2 text-[10px] font-semibold tracking-wider text-slate-500 uppercase font-mono">
          Operations Modules
        </p>
        <div className="pt-2 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;

            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onTabChange?.(item.id)}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? "bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 shadow-sm"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-900/80 border border-transparent"
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <Icon
                    className={`h-4 w-4 ${
                      isActive ? "text-cyan-400" : "text-slate-500"
                    }`}
                  />
                  <span>{item.name}</span>
                </div>
                {item.badge && (
                  <Badge
                    variant="secondary"
                    className={`text-[9px] py-0 px-1.5 font-mono ${
                      isActive
                        ? "bg-cyan-950/60 text-cyan-300 border-cyan-500/30"
                        : "bg-slate-900 text-slate-500 border-slate-800"
                    }`}
                  >
                    {item.badge}
                  </Badge>
                )}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Active Replay Context Indicator */}
      <div className="px-3 pb-3">
        <div className="rounded-lg bg-slate-900/50 border border-slate-800/80 p-2.5 text-[11px] font-mono">
          <span className="text-[10px] text-slate-500 block">ACTIVE SCENARIO:</span>
          <span className="text-cyan-300 font-semibold uppercase">{scenarioKey}</span>
        </div>
      </div>

      {/* Team & System Footer */}
      <div className="p-3.5 border-t border-slate-800 bg-slate-950/80">
        <div className="rounded-lg bg-slate-900/60 border border-slate-800/80 p-2.5 space-y-1 text-[10px] font-mono text-slate-400">
          <div className="flex items-center justify-between">
            <span>Team Identifier</span>
            <span className="text-cyan-400 font-semibold">TC490</span>
          </div>
          <div className="flex items-center justify-between">
            <span>Track</span>
            <span className="text-slate-300 font-semibold">B (App/API)</span>
          </div>
          <div className="flex items-center justify-between">
            <span>Branch</span>
            <span className="text-emerald-400 truncate max-w-[110px]">
              feature/dashboard-api
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}

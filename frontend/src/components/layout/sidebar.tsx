"use client";

import React from "react";
import Link from "next/link";
import {
  Activity,
  Network,
  Cpu,
  GitBranch,
  ShieldCheck,
  Radar,
  FileCheck2,
  BarChart3,
  Terminal,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface NavItem {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  status?: string;
  badge?: string;
}

const navItems: NavItem[] = [
  {
    name: "Operations Center",
    href: "/",
    icon: Activity,
    status: "active",
  },
  {
    name: "5-Node Topology",
    href: "#",
    icon: Network,
    badge: "Phase 01",
  },
  {
    name: "Alarm Correlation",
    href: "#",
    icon: Cpu,
    badge: "Phase 02",
  },
  {
    name: "Diagnostic Engine",
    href: "#",
    icon: GitBranch,
    badge: "Phase 02",
  },
  {
    name: "Counterfactuals",
    href: "#",
    icon: ShieldCheck,
    badge: "Phase 03",
  },
  {
    name: "Active Probes",
    href: "#",
    icon: Radar,
    badge: "Phase 03",
  },
  {
    name: "Evidence Certificates",
    href: "#",
    icon: FileCheck2,
    badge: "Phase 04",
  },
  {
    name: "Benchmark Evaluation",
    href: "#",
    icon: BarChart3,
    badge: "Phase 04",
  },
];

export function Sidebar() {
  return (
    <aside className="w-72 bg-slate-950/90 border-r border-slate-800 flex flex-col shrink-0 min-h-screen">
      {/* Branding Header */}
      <div className="p-6 border-b border-slate-800/80">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 shadow-inner">
            <Terminal className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-lg tracking-wider text-white">NEXORA</span>
              <Badge variant="default" className="text-[10px] px-1.5 py-0">v0.1.0</Badge>
            </div>
            <p className="text-xs text-slate-400 font-mono">PS-035 System</p>
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-slate-800/60">
          <p className="text-[11px] font-mono text-cyan-400 uppercase tracking-wider">
            From Correlation to Verification
          </p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-4 py-5 space-y-1 overflow-y-auto">
        <p className="px-2 text-[10px] font-semibold tracking-wider text-slate-500 uppercase">
          Navigation Modules
        </p>
        <div className="pt-2 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = item.status === "active";
            return (
              <Link
                key={item.name}
                href={item.href}
                className={`flex items-center justify-between px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? "bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 shadow-sm"
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
                  <Badge variant="secondary" className="text-[10px] py-0 px-1.5 bg-slate-800/80 text-slate-400 border border-slate-700/50">
                    {item.badge}
                  </Badge>
                )}
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Team & System Footer */}
      <div className="p-4 border-t border-slate-800 bg-slate-950/60">
        <div className="rounded-lg bg-slate-900/60 border border-slate-800/80 p-3">
          <div className="flex items-center justify-between text-[11px] text-slate-400">
            <span>Team Identifier</span>
            <span className="font-mono text-cyan-400 font-semibold">TC490</span>
          </div>
          <div className="flex items-center justify-between text-[11px] text-slate-400 mt-1">
            <span>Hackathon</span>
            <span className="text-slate-300 font-mono">AIORI 3</span>
          </div>
          <div className="flex items-center justify-between text-[11px] text-slate-400 mt-1">
            <span>Branch</span>
            <span className="text-emerald-400 font-mono text-[10px] truncate max-w-[130px]">
              phase-00-scaffold
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}

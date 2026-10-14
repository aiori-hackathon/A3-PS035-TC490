"use client";

import React, { useState } from "react";
import { Sidebar } from "@/components/layout/sidebar";
import { Header } from "@/components/layout/header";
import { SystemStatusBanner } from "@/components/dashboard/system-status-banner";
import { NetworkLabCard } from "@/components/dashboard/network-lab-card";
import { DiagnosticReadinessCard } from "@/components/dashboard/diagnostic-readiness-card";
import { BackendStatus } from "@/lib/api-client";
import { Terminal, Shield, FileCheck, GitFork } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

export default function OperationsDashboard() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>({
    isHealthy: false,
    serviceName: "connecting...",
    latencyMs: null,
    lastChecked: null,
    errorMessage: null,
  });

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      {/* Navigation Sidebar */}
      <Sidebar />

      {/* Main Operations Area */}
      <div className="flex-1 flex flex-col min-w-0 bg-operations-grid">
        <Header onStatusUpdate={setBackendStatus} />

        <main className="flex-1 p-6 space-y-6 max-w-7xl mx-auto w-full">
          {/* Welcome / Phase Status Banner */}
          <div className="rounded-xl border border-cyan-500/20 bg-gradient-to-r from-slate-900/90 via-cyan-950/20 to-slate-900/90 p-6 backdrop-blur-md">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="space-y-1.5">
                <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 text-xs font-mono">
                  <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
                  PHASE 00: ARCHITECTURAL FOUNDATION ACTIVE
                </div>
                <h2 className="text-xl md:text-2xl font-bold tracking-tight text-white">
                  Evidence-Based Operator Network Fault Localisation
                </h2>
                <p className="text-xs md:text-sm text-slate-400 max-w-2xl leading-relaxed">
                  Welcome to NEXORA. Moving operator network diagnostics from noisy correlation to
                  mathematically sound, counterfactually verified root-cause localization.
                </p>
              </div>

              <div className="flex items-center gap-3 self-start md:self-auto">
                <div className="text-right">
                  <p className="text-[11px] text-slate-500 font-mono">PROBLEM STATEMENT</p>
                  <p className="text-xs font-mono font-semibold text-cyan-300">PS-035 (AIORI-3)</p>
                </div>
              </div>
            </div>
          </div>

          {/* Real-time System Metrics & Status */}
          <SystemStatusBanner status={backendStatus} />

          {/* Core Dashboard Grid */}
          <div className="grid grid-cols-1 gap-6">
            {/* 5-Node Laboratory Status (Explicitly showing unconfigured state) */}
            <NetworkLabCard />

            {/* PS-035 Requirements Readiness Matrix */}
            <DiagnosticReadinessCard />
          </div>

          {/* Architecture Pillars Preview */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <Card className="border-slate-800/80 bg-slate-900/40">
              <CardContent className="p-4 space-y-2">
                <div className="flex items-center gap-2 text-cyan-400">
                  <Terminal className="h-4 w-4" />
                  <span className="text-xs font-semibold">1. Real 5-Node Lab</span>
                </div>
                <p className="text-[11px] text-slate-400 leading-normal">
                  Containerlab running FRRouting OSPFv2 with Linux netem fault injection.
                </p>
              </CardContent>
            </Card>

            <Card className="border-slate-800/80 bg-slate-900/40">
              <CardContent className="p-4 space-y-2">
                <div className="flex items-center gap-2 text-indigo-400">
                  <GitFork className="h-4 w-4" />
                  <span className="text-xs font-semibold">2. Diagnostic Graph</span>
                </div>
                <p className="text-[11px] text-slate-400 leading-normal">
                  Deterministic fault graph reasoning with ranked Top-1/Top-3 hypotheses.
                </p>
              </CardContent>
            </Card>

            <Card className="border-slate-800/80 bg-slate-900/40">
              <CardContent className="p-4 space-y-2">
                <div className="flex items-center gap-2 text-emerald-400">
                  <Shield className="h-4 w-4" />
                  <span className="text-xs font-semibold">3. Counterfactual Probing</span>
                </div>
                <p className="text-[11px] text-slate-400 leading-normal">
                  Bounded, read-only diagnostic ping probes with strict safety guardrails.
                </p>
              </CardContent>
            </Card>

            <Card className="border-slate-800/80 bg-slate-900/40">
              <CardContent className="p-4 space-y-2">
                <div className="flex items-center gap-2 text-amber-400">
                  <FileCheck className="h-4 w-4" />
                  <span className="text-xs font-semibold">4. Audit Certificates</span>
                </div>
                <p className="text-[11px] text-slate-400 leading-normal">
                  Auditable diagnostic certificates with explicit sufficiency bounds.
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Footer Information */}
          <footer className="pt-4 border-t border-slate-900 text-center text-xs text-slate-600 space-y-1">
            <p>NEXORA — Team A3-PS035-TC490 — AIORI Hackathon 3</p>
            <p className="font-mono text-[10px] text-slate-600">
              Strict Isolation Invariant: Injected ground-truth labels isolated from live inference.
            </p>
          </footer>
        </main>
      </div>
    </div>
  );
}

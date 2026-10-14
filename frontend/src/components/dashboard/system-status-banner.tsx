import React from "react";
import { Server, Activity, ShieldCheck, Zap } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BackendStatus } from "@/lib/api-client";

interface SystemStatusBannerProps {
  status: BackendStatus;
}

export function SystemStatusBanner({ status }: SystemStatusBannerProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
      {/* Backend API Service */}
      <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
        <CardContent className="p-4 flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-[11px] font-medium text-slate-400">Backend Core</p>
            <p className="text-sm font-semibold font-mono text-white">
              {status.serviceName}
            </p>
            <p className="text-[10px] text-slate-500 font-mono">
              {status.lastChecked
                ? `Last: ${status.lastChecked.toLocaleTimeString()}`
                : "Awaiting poll"}
            </p>
          </div>
          <div className="p-2.5 rounded-lg bg-slate-800/80 border border-slate-700/50">
            <Server className={`h-5 w-5 ${status.isHealthy ? "text-emerald-400" : "text-rose-400"}`} />
          </div>
        </CardContent>
      </Card>

      {/* Latency */}
      <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
        <CardContent className="p-4 flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-[11px] font-medium text-slate-400">API Latency</p>
            <p className="text-sm font-semibold font-mono text-white">
              {status.latencyMs !== null ? `${status.latencyMs} ms` : "---"}
            </p>
            <p className="text-[10px] text-slate-500 font-mono">
              Target: http://localhost:8000
            </p>
          </div>
          <div className="p-2.5 rounded-lg bg-slate-800/80 border border-slate-700/50">
            <Activity className="h-5 w-5 text-cyan-400" />
          </div>
        </CardContent>
      </Card>

      {/* Diagnostic Engine Status */}
      <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
        <CardContent className="p-4 flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-[11px] font-medium text-slate-400">Diagnostic Engine</p>
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-semibold text-white">Standby</span>
              <Badge variant="outline" className="text-[9px] py-0 px-1 border-slate-700 text-slate-400">
                Phase 00
              </Badge>
            </div>
            <p className="text-[10px] text-slate-500">Deterministic Reasoning</p>
          </div>
          <div className="p-2.5 rounded-lg bg-slate-800/80 border border-slate-700/50">
            <Zap className="h-5 w-5 text-amber-400" />
          </div>
        </CardContent>
      </Card>

      {/* Isolation Guardrail */}
      <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
        <CardContent className="p-4 flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-[11px] font-medium text-slate-400">Evidence Guardrail</p>
            <p className="text-sm font-semibold text-white">Strict Isolation</p>
            <p className="text-[10px] text-slate-500">Labels Isolated from Engine</p>
          </div>
          <div className="p-2.5 rounded-lg bg-slate-800/80 border border-slate-700/50">
            <ShieldCheck className="h-5 w-5 text-emerald-400" />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

"use client";

import React, { useEffect, useState, useCallback } from "react";
import { RefreshCw, Server, WifiOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchHealth, BackendStatus } from "@/lib/api-client";

interface HeaderProps {
  onStatusUpdate?: (status: BackendStatus) => void;
}

export function Header({ onStatusUpdate }: HeaderProps) {
  const [status, setStatus] = useState<BackendStatus>({
    isHealthy: false,
    serviceName: "checking...",
    latencyMs: null,
    lastChecked: null,
    errorMessage: null,
  });
  const [isChecking, setIsChecking] = useState(false);
  const [currentTime, setCurrentTime] = useState<string>("");
  const onStatusUpdateRef = React.useRef(onStatusUpdate);

  useEffect(() => {
    onStatusUpdateRef.current = onStatusUpdate;
  }, [onStatusUpdate]);

  const checkBackend = useCallback(async (manual = false) => {
    if (manual) setIsChecking(true);
    const result = await fetchHealth();
    const newStatus: BackendStatus = {
      isHealthy: result.ok,
      serviceName: result.data?.service || "unavailable",
      latencyMs: result.latencyMs,
      lastChecked: new Date(),
      errorMessage: result.error || null,
    };
    setStatus(newStatus);
    if (manual) setIsChecking(false);
    onStatusUpdateRef.current?.(newStatus);
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      void checkBackend(false);
    }, 0);
    const interval = setInterval(() => {
      void checkBackend(false);
    }, 15000);
    return () => {
      clearTimeout(timer);
      clearInterval(interval);
    };
  }, [checkBackend]);

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setCurrentTime(now.toUTCString().replace("GMT", "UTC"));
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <header className="h-16 border-b border-slate-800 bg-slate-950/70 backdrop-blur-md px-6 flex items-center justify-between z-10 sticky top-0">
      {/* Title & Status */}
      <div className="flex items-center gap-4">
        <div>
          <h1 className="text-base font-semibold text-white tracking-tight">
            Network Operations Console
          </h1>
          <p className="text-[11px] text-slate-400">
            PS-035 Evidence-Based Operator Network Fault Localisation
          </p>
        </div>
      </div>

      {/* Right Controls */}
      <div className="flex items-center gap-3">
        {/* UTC Clock */}
        <div className="hidden md:flex items-center gap-1.5 px-3 py-1 rounded-md bg-slate-900 border border-slate-800 text-[11px] font-mono text-slate-400">
          <span>{currentTime || "UTC Synchronizing..."}</span>
        </div>

        {/* Backend Status Indicator */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-800">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              {status.isHealthy ? (
                <>
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </>
              ) : (
                <span className="relative inline-flex rounded-full h-2 w-2 bg-rose-500"></span>
              )}
            </span>

            <div className="flex items-center gap-1.5">
              <Server className="h-3.5 w-3.5 text-slate-400" />
              <span className="text-xs font-mono text-slate-300">
                {status.isHealthy ? status.serviceName : "Backend Disconnected"}
              </span>
            </div>
          </div>

          {status.isHealthy ? (
            <Badge variant="success" className="text-[10px] py-0 px-1.5">
              {status.latencyMs}ms
            </Badge>
          ) : (
            <Badge variant="destructive" className="text-[10px] py-0 px-1.5 flex items-center gap-1">
              <WifiOff className="h-2.5 w-2.5" />
              Offline
            </Badge>
          )}

          <Button
            variant="ghost"
            size="icon"
            onClick={() => void checkBackend(true)}
            disabled={isChecking}
            title="Refresh backend status"
            className="h-6 w-6 text-slate-400 hover:text-white"
          >
            <RefreshCw className={`h-3 w-3 ${isChecking ? "animate-spin text-cyan-400" : ""}`} />
          </Button>
        </div>
      </div>
    </header>
  );
}

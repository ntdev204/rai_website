"use client";

import { MetricCard } from "@/components/ui/MetricCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { fetchWithAuth } from "@/lib/api";
import { Activity, AlertTriangle, Battery, Gauge, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface Snapshot {
  id: number;
  connected: boolean;
  navigation_mode?: string | null;
  voltage?: number | null;
  battery_percent?: number | null;
  pos_x?: number | null;
  pos_y?: number | null;
  yaw?: number | null;
  speed?: number | null;
  ai_mode?: string | null;
  ai_fps?: number | null;
  ai_persons?: number | null;
  ai_obstacles?: number | null;
  created_at: string;
}

interface AnalyticsSummary {
  collector: {
    running: boolean;
    interval_sec: number;
    retention_hours: number;
  };
  current: Snapshot | null;
  window: {
    hours: number;
    samples: number;
    avg_voltage?: number | null;
    min_voltage?: number | null;
    avg_battery_percent?: number | null;
    avg_speed?: number | null;
    max_speed?: number | null;
    avg_ai_fps?: number | null;
    person_observations: number;
    obstacle_observations: number;
    navigation_modes: Record<string, number>;
  };
  logs: {
    by_severity: Record<string, number>;
    by_source: Record<string, number>;
    recent_alerts: Array<{
      id: number;
      severity: string;
      source: string;
      event_type: string;
      message: string;
      created_at: string;
    }>;
  };
}

function formatNumber(value: number | null | undefined, suffix = "") {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${Number(value).toFixed(1)}${suffix}`;
}

export default function AnalyticsPage() {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [series, setSeries] = useState<Snapshot[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const loadAnalytics = useCallback(async () => {
    try {
      const [summaryRes, seriesRes] = await Promise.all([
        fetchWithAuth("/api/analytics/summary?hours=24"),
        fetchWithAuth("/api/analytics/timeseries?hours=6&limit=240"),
      ]);
      setSummary((await summaryRes.json()) as AnalyticsSummary);
      setSeries((await seriesRes.json()) as Snapshot[]);
      setLastUpdated(new Date());
    } catch {
      setSummary(null);
      setSeries([]);
    }
  }, []);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void loadAnalytics(), 0);
    const interval = window.setInterval(loadAnalytics, 5000);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(interval);
    };
  }, [loadAnalytics]);

  const chartData = useMemo(
    () =>
      series.map((item) => ({
        ...item,
        time: new Date(item.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        voltage: item.voltage ?? null,
        speed: item.speed ?? null,
        ai_fps: item.ai_fps ?? null,
        detections: (item.ai_persons ?? 0) + (item.ai_obstacles ?? 0),
      })),
    [series]
  );

  const current = summary?.current;
  const windowStats = summary?.window;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Analytics & Reports</h2>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-500">
            <StatusBadge status={summary?.collector.running ? "success" : "warning"}>
              {summary?.collector.running ? "collector running" : "collector offline"}
            </StatusBadge>
            {lastUpdated && <span>Updated {lastUpdated.toLocaleTimeString()}</span>}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
        <MetricCard
          title="ROS2 Telemetry"
          value={current?.connected ? "Online" : "Offline"}
          icon={<Activity className="w-5 h-5" />}
        />
        <MetricCard
          title="Battery"
          value={formatNumber(current?.battery_percent, "%")}
          icon={<Battery className="w-5 h-5" />}
          trend={current?.voltage ? { value: `${current.voltage.toFixed(1)}V`, isPositive: current.voltage >= 22.5 } : undefined}
        />
        <MetricCard
          title="Speed"
          value={formatNumber(current?.speed, " m/s")}
          icon={<Gauge className="w-5 h-5" />}
          trend={windowStats?.max_speed ? { value: `max ${windowStats.max_speed.toFixed(1)}`, isPositive: true } : undefined}
        />
        <MetricCard
          title="Robot Position"
          value={
            current?.pos_x !== null && current?.pos_x !== undefined && current?.pos_y !== null && current?.pos_y !== undefined
              ? `${current.pos_x.toFixed(2)}, ${current.pos_y.toFixed(2)}`
              : "-"
          }
          icon={<Activity className="w-5 h-5" />}
          trend={
            current?.yaw !== null && current?.yaw !== undefined
              ? { value: `yaw ${current.yaw.toFixed(2)}`, isPositive: true }
              : undefined
          }
        />
        <MetricCard
          title="AI Detections"
          value={(windowStats?.person_observations ?? 0) + (windowStats?.obstacle_observations ?? 0)}
          icon={<Users className="w-5 h-5" />}
          trend={windowStats?.avg_ai_fps ? { value: `${windowStats.avg_ai_fps.toFixed(1)} FPS`, isPositive: true } : undefined}
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
          <h3 className="font-semibold text-slate-800 mb-4">Robot Telemetry</h3>
          <div className="h-[300px]">
            {chartData.length === 0 ? (
              <div className="h-full border border-dashed border-slate-200 rounded-lg flex items-center justify-center text-slate-400">
                Waiting for analytics snapshots.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="time" stroke="#64748b" fontSize={12} tickLine={false} />
                  <YAxis stroke="#64748b" fontSize={12} tickLine={false} width={42} />
                  <Tooltip />
                  <Line type="monotone" dataKey="voltage" name="Voltage" stroke="#0f766e" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="speed" name="Speed" stroke="#2563eb" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
          <h3 className="font-semibold text-slate-800 mb-4">Context-Aware AI</h3>
          <div className="h-[300px]">
            {chartData.length === 0 ? (
              <div className="h-full border border-dashed border-slate-200 rounded-lg flex items-center justify-center text-slate-400">
                Waiting for AI metrics.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="time" stroke="#64748b" fontSize={12} tickLine={false} />
                  <YAxis stroke="#64748b" fontSize={12} tickLine={false} width={42} />
                  <Tooltip />
                  <Area type="monotone" dataKey="ai_fps" name="AI FPS" stroke="#7c3aed" fill="#ede9fe" strokeWidth={2} />
                  <Area type="monotone" dataKey="detections" name="Detections" stroke="#ea580c" fill="#ffedd5" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
          <h3 className="font-semibold text-slate-800 mb-4">24h Summary</h3>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div className="rounded-lg border border-slate-200 p-4">
              <div className="text-slate-500">Samples</div>
              <div className="mt-1 text-2xl font-bold text-slate-900">{windowStats?.samples ?? 0}</div>
            </div>
            <div className="rounded-lg border border-slate-200 p-4">
              <div className="text-slate-500">Avg Voltage</div>
              <div className="mt-1 text-2xl font-bold text-slate-900">{formatNumber(windowStats?.avg_voltage, "V")}</div>
            </div>
            <div className="rounded-lg border border-slate-200 p-4">
              <div className="text-slate-500">Avg Speed</div>
              <div className="mt-1 text-2xl font-bold text-slate-900">{formatNumber(windowStats?.avg_speed, " m/s")}</div>
            </div>
            <div className="rounded-lg border border-slate-200 p-4">
              <div className="text-slate-500">Mode</div>
              <div className="mt-1 text-2xl font-bold text-slate-900">{current?.navigation_mode ?? "-"}</div>
            </div>
            <div className="rounded-lg border border-slate-200 p-4">
              <div className="text-slate-500">Current X</div>
              <div className="mt-1 text-2xl font-bold text-slate-900">{formatNumber(current?.pos_x, " m")}</div>
            </div>
            <div className="rounded-lg border border-slate-200 p-4">
              <div className="text-slate-500">Current Y</div>
              <div className="mt-1 text-2xl font-bold text-slate-900">{formatNumber(current?.pos_y, " m")}</div>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
          <h3 className="font-semibold text-slate-800 mb-4 flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-500" />
            Recent Alerts
          </h3>
          <div className="space-y-3">
            {summary?.logs.recent_alerts.length ? (
              summary.logs.recent_alerts.map((alert) => (
                <div key={alert.id} className="rounded-lg border border-slate-200 p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={alert.severity === "WARNING" ? "warning" : "error"}>{alert.severity}</StatusBadge>
                    <span className="font-medium text-slate-700">{alert.source}</span>
                    <span className="text-slate-400">{new Date(alert.created_at).toLocaleTimeString()}</span>
                  </div>
                  <div className="mt-2 text-slate-600">{alert.message}</div>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-slate-400">
                No warning or error logs in the selected window.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

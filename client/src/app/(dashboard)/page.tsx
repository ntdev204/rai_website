"use client";

import { MetricCard } from "@/components/ui/MetricCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { fetchWithAuth } from "@/lib/api";
import { useWebSocket } from "@/hooks/useWebSocket";
import { Activity, Battery, Video, Users } from "lucide-react";
import { useEffect, useState } from "react";

interface RobotTelemetry {
  connected?: boolean;
  battery_percent?: number | null;
  pos_x?: number | null;
  pos_y?: number | null;
  yaw?: number | null;
  map_pose?: {
    x?: number | null;
    y?: number | null;
    yaw?: number | null;
  } | null;
}

interface AiMetrics {
  fps?: number;
  mode?: string;
  persons?: number;
  obstacles?: number;
}

interface TelemetryPayload {
  robot?: RobotTelemetry;
  ai?: AiMetrics;
}

interface EventLog {
  id: number;
  severity: string;
  source: string;
  message: string;
  created_at: string;
}

const formatNumber = (value: number | null | undefined, digits = 1) =>
  typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "-";

export default function Dashboard() {
  const [telemetry, setTelemetry] = useState<TelemetryPayload>({});
  const [logs, setLogs] = useState<EventLog[]>([]);

  const { isConnected } = useWebSocket("/ws/telemetry", {
    onMessage: (msg) => {
      try {
        setTelemetry(JSON.parse(msg.data) as TelemetryPayload);
      } catch {
        setTelemetry({});
      }
    },
  });

  useEffect(() => {
    fetchWithAuth("/api/logs/?limit=5")
      .then((res) => res.json())
      .then((data: EventLog[]) => setLogs(data))
      .catch(() => setLogs([]));
  }, []);

  const robot = telemetry.robot ?? {};
  const ai = telemetry.ai ?? {};
  const robotOnline = isConnected && robot.connected !== false;
  const robotPose = {
    x: robot.map_pose?.x ?? robot.pos_x ?? null,
    y: robot.map_pose?.y ?? robot.pos_y ?? null,
    yaw: robot.map_pose?.yaw ?? robot.yaw ?? null,
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Overview</h2>
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-slate-500">Robot Status:</span>
          <StatusBadge status={robotOnline ? "success" : "error"}>
            {robotOnline ? "ONLINE" : "OFFLINE"}
          </StatusBadge>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Current Mode"
          value={ai.mode ?? "-"}
          icon={<Activity className="w-5 h-5 text-blue-500" />}
        />
        <MetricCard
          title="Battery"
          value={
            typeof robot.battery_percent === "number"
              ? `${robot.battery_percent.toFixed(1)}%`
              : "-"
          }
          icon={<Battery className="w-5 h-5 text-emerald-500" />}
        />
        <MetricCard
          title="Stream FPS"
          value={formatNumber(ai.fps)}
          icon={<Video className="w-5 h-5 text-purple-500" />}
        />
        <MetricCard
          title="Tracked Persons"
          value={typeof ai.persons === "number" ? ai.persons : "-"}
          icon={<Users className="w-5 h-5 text-amber-500" />}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 p-6 shadow-sm min-h-[400px] flex flex-col">
          <h3 className="text-lg font-semibold text-slate-800 mb-4">Live Position</h3>
          <div className="flex-1 bg-slate-100 rounded-lg border border-slate-200 flex items-center justify-center">
            {robotOnline ? (
              <div className="grid grid-cols-3 gap-6 text-center">
                <div>
                  <p className="text-xs uppercase text-slate-400 font-semibold">X</p>
                  <p className="text-2xl font-bold text-slate-800">{formatNumber(robotPose.x, 3)}</p>
                </div>
                <div>
                  <p className="text-xs uppercase text-slate-400 font-semibold">Y</p>
                  <p className="text-2xl font-bold text-slate-800">{formatNumber(robotPose.y, 3)}</p>
                </div>
                <div>
                  <p className="text-xs uppercase text-slate-400 font-semibold">Yaw</p>
                  <p className="text-2xl font-bold text-slate-800">{formatNumber(robotPose.yaw, 3)}</p>
                </div>
              </div>
            ) : (
              <span className="text-slate-400 font-medium">No robot telemetry received.</span>
            )}
          </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm min-h-[400px] flex flex-col">
          <h3 className="text-lg font-semibold text-slate-800 mb-4">Recent Events</h3>
          <div className="flex-1 overflow-auto space-y-4">
            {logs.length === 0 ? (
              <p className="text-sm text-slate-400">No events recorded in database.</p>
            ) : (
              logs.map((log) => (
                <div key={log.id} className="flex gap-3 text-sm">
                  <span className="text-slate-400 font-medium whitespace-nowrap">
                    {new Date(log.created_at).toLocaleTimeString()}
                  </span>
                  <p className="text-slate-700">
                    <span className="font-semibold text-slate-900">{log.source}</span>: {log.message}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

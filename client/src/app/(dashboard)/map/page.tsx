"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useWebSocket } from "@/hooks/useWebSocket";
import { fetchWithAuth } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Crosshair,
  LocateFixed,
  Map as MapIcon,
  Navigation,
  Play,
  Radar,
  RefreshCw,
  Save,
  Square,
  Trash2,
  Waypoints,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type NavMode = "nav2" | "slam";

interface MapRecord {
  id: number;
  name: string;
  slug: string;
  description?: string | null;
  resolution: number;
  width: number;
  height: number;
  origin_x: number;
  origin_y: number;
  source?: string | null;
  is_active?: boolean;
  created_at: string;
}

interface MapInfo {
  resolution: number;
  width: number;
  height: number;
  origin?: {
    x?: number;
    y?: number;
  };
}

interface Point2D {
  x: number;
  y: number;
}

interface RobotPose extends Point2D {
  yaw?: number;
}

interface RobotTelemetry {
  connected?: boolean;
  navigation_mode?: string | null;
  map_info?: MapInfo | null;
  map_pose?: RobotPose | null;
  pos_x?: number | null;
  pos_y?: number | null;
  yaw?: number | null;
  plan?: Point2D[];
  local_plan?: Point2D[];
}

const MODE_LABELS: Record<NavMode, string> = {
  nav2: "Nav2",
  slam: "SLAM",
};

function mapRecordToInfo(map: MapRecord | null): MapInfo | null {
  if (!map) return null;
  return {
    resolution: map.resolution,
    width: map.width,
    height: map.height,
    origin: { x: map.origin_x, y: map.origin_y },
  };
}

function worldToPixel(point: Point2D, info: MapInfo): Point2D {
  const originX = info.origin?.x ?? 0;
  const originY = info.origin?.y ?? 0;
  return {
    x: (point.x - originX) / info.resolution,
    y: info.height - (point.y - originY) / info.resolution,
  };
}

function pixelToWorld(point: Point2D, info: MapInfo): Point2D {
  const originX = info.origin?.x ?? 0;
  const originY = info.origin?.y ?? 0;
  return {
    x: originX + point.x * info.resolution,
    y: originY + (info.height - point.y) * info.resolution,
  };
}

export default function MapPage() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const [maps, setMaps] = useState<MapRecord[]>([]);
  const [activeMap, setActiveMap] = useState<MapRecord | null>(null);
  const [mode, setMode] = useState<NavMode>("nav2");
  const [telemetry, setTelemetry] = useState<RobotTelemetry | null>(null);
  const [mapImage, setMapImage] = useState<HTMLImageElement | null>(null);
  const [mapName, setMapName] = useState("");
  const [status, setStatus] = useState("Ready");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [lastGoal, setLastGoal] = useState<Point2D | null>(null);
  const [slamStarted, setSlamStarted] = useState(false);
  const [nav2Started, setNav2Started] = useState(false);

  useWebSocket(
    "/ws/telemetry",
    useMemo(
      () => ({
        onMessage: (event: MessageEvent) => {
          try {
            const payload = JSON.parse(String(event.data));
            setTelemetry(payload.robot ?? null);
          } catch {
            setTelemetry(null);
          }
        },
      }),
      []
    )
  );

  const loadMaps = useCallback(async () => {
    try {
      const response = await fetchWithAuth("/api/maps/");
      const data: MapRecord[] = await response.json();
      setMaps(data);
      setActiveMap((current) => {
        const currentFresh = current ? data.find((item) => item.id === current.id) : null;
        return currentFresh ?? data.find((item) => item.is_active) ?? data[0] ?? null;
      });
    } catch {
      setMaps([]);
      setActiveMap(null);
    }
  }, []);

  const loadMapImage = useCallback(async () => {
    const slamScanAvailable = slamStarted || telemetry?.navigation_mode?.toLowerCase() === "slam";
    const endpoint =
      mode === "slam"
        ? slamScanAvailable
          ? `/api/maps/live/image?ts=${Date.now()}`
          : null
        : activeMap
          ? `/api/maps/${activeMap.id}/image?ts=${Date.now()}`
          : null;

    if (!endpoint) {
      setMapImage(null);
      return;
    }

    try {
      const response = await fetchWithAuth(endpoint);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const image = new window.Image();
      image.onload = () => {
        if (objectUrlRef.current) {
          URL.revokeObjectURL(objectUrlRef.current);
        }
        objectUrlRef.current = url;
        setMapImage(image);
      };
      image.onerror = () => {
        URL.revokeObjectURL(url);
        setMapImage(null);
      };
      image.src = url;
    } catch {
      setMapImage(null);
    }
  }, [activeMap, mode, slamStarted, telemetry?.navigation_mode]);

  const mapInfo = useMemo(() => {
    if (mode === "slam") {
      return telemetry?.map_info ?? null;
    }
    return mapRecordToInfo(activeMap);
  }, [activeMap, mode, telemetry?.map_info]);

  const drawMap = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const width = Math.max(1, Math.round(mapInfo?.width || mapImage?.naturalWidth || 640));
    const height = Math.max(1, Math.round(mapInfo?.height || mapImage?.naturalHeight || 480));
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#e2e8f0";
    ctx.fillRect(0, 0, width, height);

    if (mapImage) {
      ctx.drawImage(mapImage, 0, 0, width, height);
    } else {
      ctx.strokeStyle = "#cbd5e1";
      ctx.lineWidth = 1;
      for (let x = 0; x < width; x += 32) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      for (let y = 0; y < height; y += 32) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }
    }

    if (!mapInfo || !mapInfo.resolution) return;

    const drawPath = (points: Point2D[] | undefined, color: string, lineWidth: number) => {
      if (!points || points.length < 2) return;
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = lineWidth;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.beginPath();
      points.forEach((point, index) => {
        const px = worldToPixel(point, mapInfo);
        if (index === 0) {
          ctx.moveTo(px.x, px.y);
        } else {
          ctx.lineTo(px.x, px.y);
        }
      });
      ctx.stroke();
      ctx.restore();
    };

    drawPath(telemetry?.plan, "#2563eb", 3);
    drawPath(telemetry?.local_plan, "#f97316", 2);

    if (lastGoal) {
      const goal = worldToPixel(lastGoal, mapInfo);
      ctx.save();
      ctx.strokeStyle = "#dc2626";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(goal.x, goal.y, 9, 0, Math.PI * 2);
      ctx.moveTo(goal.x - 14, goal.y);
      ctx.lineTo(goal.x + 14, goal.y);
      ctx.moveTo(goal.x, goal.y - 14);
      ctx.lineTo(goal.x, goal.y + 14);
      ctx.stroke();
      ctx.restore();
    }

    const pose = telemetry?.map_pose;
    if (pose && Number.isFinite(pose.x) && Number.isFinite(pose.y)) {
      const robot = worldToPixel(pose, mapInfo);
      ctx.save();
      ctx.translate(robot.x, robot.y);
      ctx.rotate(-(pose.yaw ?? 0));
      ctx.fillStyle = "#16a34a";
      ctx.strokeStyle = "#052e16";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(14, 0);
      ctx.lineTo(-10, 8);
      ctx.lineTo(-10, -8);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    }
  }, [lastGoal, mapImage, mapInfo, telemetry?.local_plan, telemetry?.map_pose, telemetry?.plan]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadMaps();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadMaps]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadMapImage();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadMapImage]);

  useEffect(() => {
    if (mode !== "slam") return;
    const timer = window.setInterval(() => {
      void loadMapImage();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [loadMapImage, mode]);

  useEffect(() => {
    drawMap();
  }, [drawMap]);

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
      }
    };
  }, []);

  async function switchMode(nextMode: NavMode) {
    if (nextMode === "nav2" && !activeMap) {
      setStatus("Nav2 requires a saved map");
      return;
    }

    if (nextMode === "nav2") {
      const robotAlreadyNav2 = telemetry?.navigation_mode?.toLowerCase() === "nav2";
      setMode("nav2");
      setNav2Started(robotAlreadyNav2);
      setSlamStarted(false);
      setLastGoal(null);
      setStatus(robotAlreadyNav2 ? "Nav2 is already running" : "Nav2 ready. Press Start to run.");
      return;
    }

    if (nextMode === "slam") {
      const robotAlreadySlam = telemetry?.navigation_mode?.toLowerCase() === "slam";
      setMode("slam");
      setSlamStarted(robotAlreadySlam);
      setMapImage(null);
      setLastGoal(null);
      setStatus(robotAlreadySlam ? "SLAM is already scanning" : "SLAM ready. Press Start to scan.");
      return;
    }

    setMode(nextMode);
  }

  async function startSlamScan() {
    setBusyAction("slam:start");
    try {
      await fetchWithAuth("/api/maps/slam/start", { method: "POST" });
      setMode("slam");
      setSlamStarted(true);
      setNav2Started(false);
      setMapImage(null);
      setLastGoal(null);
      setStatus("SLAM scan started");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Start SLAM failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function startNav2() {
    if (!activeMap) {
      setStatus("Nav2 requires a saved map");
      return;
    }

    setBusyAction("nav2:start");
    try {
      const response = await fetchWithAuth("/api/maps/nav2/start", {
        method: "POST",
        body: JSON.stringify({ map_id: activeMap.id }),
      });
      const data: { map?: MapRecord | null } = await response.json();
      setMode("nav2");
      setNav2Started(true);
      setSlamStarted(false);
      if (data.map) {
        setActiveMap(data.map);
        setMaps((current) => current.map((map) => ({ ...map, is_active: map.id === data.map?.id })));
      }
      setStatus(`Nav2 started: ${data.map?.name ?? activeMap.name}`);
      await loadMapImage();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Start Nav2 failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function stopNav2() {
    setBusyAction("nav2:stop");
    try {
      await fetchWithAuth("/api/maps/nav2/stop", { method: "POST" });
      setNav2Started(false);
      setLastGoal(null);
      setStatus("Nav2 stopped");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Stop Nav2 failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function saveMap() {
    const name = mapName.trim();
    if (!name) {
      setStatus("Map name is required");
      return;
    }

    setBusyAction("save");
    try {
      const response = await fetchWithAuth("/api/maps/save", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      const data = await response.json();
      setMapName("");
      await loadMaps();
      if (data.map) {
        setActiveMap(data.map);
      }
      setStatus(`Saved ${data.map?.name ?? name}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Save map failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function selectMap(item: MapRecord) {
    setBusyAction(`map:${item.id}`);
    setActiveMap(item);
    try {
      const response = await fetchWithAuth(`/api/maps/${item.id}/activate`, { method: "POST" });
      const updated: MapRecord = await response.json();
      setActiveMap(updated);
      setMaps((current) => current.map((map) => ({ ...map, is_active: map.id === updated.id })));
      if (mode === "nav2" && nav2Active) {
        await fetchWithAuth("/api/maps/nav2/start", {
          method: "POST",
          body: JSON.stringify({ map_id: updated.id }),
        });
        setNav2Started(true);
      }
      setStatus(nav2Active ? `Nav2 restarted: ${updated.name}` : `Map selected: ${updated.name}`);
      await loadMapImage();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Map selection failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function deleteMap(item: MapRecord) {
    const confirmed = window.confirm(`Delete map "${item.name}"?`);
    if (!confirmed) return;

    setBusyAction(`delete:${item.id}`);
    try {
      const response = await fetchWithAuth(`/api/maps/${item.id}`, { method: "DELETE" });
      const data: { active_map?: MapRecord | null } = await response.json();
      setMaps((current) => current.filter((map) => map.id !== item.id));
      if (activeMap?.id === item.id) {
        setActiveMap(data.active_map ?? null);
        setMapImage(null);
        setLastGoal(null);
      }
      await loadMaps();
      setStatus(`Deleted map: ${item.name}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Delete map failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function refreshLiveMap() {
    setBusyAction("refresh");
    try {
      if (mode === "slam") {
        await fetchWithAuth("/api/maps/slam/reset", { method: "POST" });
        setSlamStarted(true);
        setMapImage(null);
        setLastGoal(null);
        setStatus("SLAM map cleared; scan restarted");
        window.setTimeout(() => void loadMapImage(), 1000);
        return;
      }
      await loadMapImage();
      setStatus("Map refreshed");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Refresh failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCanvasClick(event: React.MouseEvent<HTMLCanvasElement>) {
    if (mode !== "nav2" || !mapInfo) return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const pixel = {
      x: ((event.clientX - rect.left) / rect.width) * canvas.width,
      y: ((event.clientY - rect.top) / rect.height) * canvas.height,
    };
    const goal = pixelToWorld(pixel, mapInfo);
    setLastGoal(goal);
    setBusyAction("goal");

    try {
      await fetchWithAuth("/api/maps/goal", {
        method: "POST",
        body: JSON.stringify({ x: goal.x, y: goal.y, theta: 0 }),
      });
      setStatus(`Goal ${goal.x.toFixed(2)}, ${goal.y.toFixed(2)}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Goal send failed");
    } finally {
      setBusyAction(null);
    }
  }

  const robotPose =
    telemetry?.map_pose && Number.isFinite(telemetry.map_pose.x) && Number.isFinite(telemetry.map_pose.y)
      ? telemetry.map_pose
      : telemetry?.pos_x !== null &&
          telemetry?.pos_x !== undefined &&
          telemetry?.pos_y !== null &&
          telemetry?.pos_y !== undefined
        ? {
            x: telemetry.pos_x,
            y: telemetry.pos_y,
            yaw: telemetry.yaw ?? 0,
          }
        : null;
  const remoteMode = telemetry?.navigation_mode;
  const robotMode = remoteMode?.toLowerCase();
  const slamScanReady = mode === "slam" && (slamStarted || robotMode === "slam");
  const nav2Active = mode === "nav2" && (nav2Started || robotMode === "nav2");
  const canvasCursor = mode === "nav2" && mapInfo ? "cursor-crosshair" : "cursor-default";

  return (
    <div className="space-y-5 h-full flex flex-col">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Map & Navigation</h2>
          <p className="text-sm text-slate-500">Mode: {MODE_LABELS[mode]}{remoteMode ? ` / robot ${remoteMode}` : ""}</p>
        </div>
        <div className="inline-flex rounded-lg border border-slate-200 bg-white p-1 shadow-sm">
          {(["nav2", "slam"] as NavMode[]).map((item) => (
            <Button
              key={item}
              type="button"
              variant={mode === item ? "default" : "ghost"}
              size="sm"
              className="gap-2"
              disabled={busyAction !== null}
              onClick={() => void switchMode(item)}
            >
              {item === "nav2" ? <Navigation className="size-4" /> : <Radar className="size-4" />}
              {MODE_LABELS[item]}
            </Button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] gap-5 flex-1 min-h-0">
        <section className="bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden flex flex-col min-h-[520px]">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <MapIcon className="size-4 text-blue-600" />
              <span className="font-medium text-slate-800">
                {mode === "slam" ? "Live SLAM map" : activeMap?.name ?? "No map selected"}
              </span>
              {mapInfo ? (
                <span className="text-slate-400">
                  {mapInfo.width}x{mapInfo.height} @ {mapInfo.resolution}m
                </span>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-2"
                disabled={busyAction !== null}
                onClick={() => void refreshLiveMap()}
              >
                <RefreshCw className="size-4" />
                Refresh
              </Button>
            </div>
          </div>

          <div className="flex-1 overflow-auto bg-slate-100 p-4">
            <div className="min-h-full flex items-center justify-center">
              <canvas
                ref={canvasRef}
                onClick={(event) => void handleCanvasClick(event)}
                className={cn(
                  "max-w-full max-h-[calc(100vh-290px)] rounded-md border border-slate-300 bg-slate-200 shadow-sm",
                  canvasCursor
                )}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 border-t border-slate-200 px-4 py-3 text-sm text-slate-600 md:grid-cols-3">
            <div className="flex items-center gap-2">
              <LocateFixed className="size-4 text-emerald-600" />
              <span>
                Robot{" "}
                {robotPose ? `${robotPose.x.toFixed(2)}, ${robotPose.y.toFixed(2)}` : "unknown"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Waypoints className="size-4 text-blue-600" />
              <span>Plan {telemetry?.plan?.length ?? 0} / Local {telemetry?.local_plan?.length ?? 0}</span>
            </div>
            <div className="flex items-center gap-2">
              <Crosshair className="size-4 text-red-600" />
              <span>{lastGoal ? `${lastGoal.x.toFixed(2)}, ${lastGoal.y.toFixed(2)}` : status}</span>
            </div>
          </div>
        </section>

        <aside className="space-y-4 overflow-y-auto">
          <section className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
            <h3 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3">Nav2</h3>
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                variant="outline"
                className="gap-2"
                disabled={busyAction !== null || mode !== "nav2" || !activeMap || nav2Active}
                onClick={() => void startNav2()}
              >
                <Play className="size-4" />
                Start
              </Button>
              <Button
                type="button"
                variant="outline"
                className="gap-2"
                disabled={busyAction !== null || mode !== "nav2" || !nav2Active}
                onClick={() => void stopNav2()}
              >
                <Square className="size-4" />
                Stop
              </Button>
            </div>
            <p className="mt-3 text-sm text-slate-500">
              {activeMap ? `Map: ${activeMap.name}` : "Nav2 requires a saved map"}
            </p>
          </section>

          <section className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
            <h3 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3">SLAM</h3>
            <Button
              type="button"
              variant="outline"
              className="mb-3 w-full gap-2"
              disabled={busyAction !== null || mode !== "slam" || slamScanReady}
              onClick={() => void startSlamScan()}
            >
              <Play className="size-4" />
              Start
            </Button>
            <div className="flex gap-2">
              <Input
                value={mapName}
                onChange={(event) => setMapName(event.target.value)}
                placeholder="Map name"
                disabled={busyAction !== null}
              />
              <Button
                type="button"
                size="icon"
                disabled={busyAction !== null || !slamScanReady}
                onClick={() => void saveMap()}
                title="Save map"
              >
                <Save className="size-4" />
              </Button>
            </div>
            <p className="mt-3 text-sm text-slate-500">{status}</p>
          </section>

          <section className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
            <h3 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3">Saved Maps</h3>
            {maps.length === 0 ? (
              <p className="text-slate-500 text-sm">No map records found.</p>
            ) : (
              <div className="space-y-2">
                {maps.map((item) => (
                  <div
                    key={item.id}
                    className={cn(
                      "rounded-md border p-3 transition-colors",
                      activeMap?.id === item.id
                        ? "border-blue-500 bg-blue-50"
                        : "border-slate-200 bg-white hover:bg-slate-50"
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <button
                        type="button"
                        disabled={busyAction !== null}
                        onClick={() => void selectMap(item)}
                        className="min-w-0 flex-1 text-left"
                      >
                        <div className="flex items-center gap-2">
                          <span className="truncate font-semibold text-slate-800">{item.name}</span>
                          {item.is_active ? (
                            <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                              Active
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-1 truncate text-xs text-slate-500">{item.slug}</p>
                        <p className="mt-1 text-xs text-slate-400">
                          {item.width}x{item.height} @ {item.resolution}m
                        </p>
                      </button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        disabled={busyAction !== null}
                        onClick={() => void deleteMap(item)}
                        title="Delete map"
                        className="size-8 shrink-0 text-slate-400 hover:bg-red-50 hover:text-red-600"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}

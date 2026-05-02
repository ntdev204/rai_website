"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getValidAccessToken } from "@/lib/api";

function getWebSocketBaseUrl() {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  if (typeof window !== "undefined") {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.hostname}:8000`;
  }
  return "ws://localhost:8000";
}

const WS_URL = getWebSocketBaseUrl();

interface UseWebSocketOptions {
  binaryType?: "blob" | "arraybuffer";
  autoReconnect?: boolean;
  onMessage?: (event: MessageEvent) => void;
}

export function useWebSocket(path: string, options: UseWebSocketOptions = {}) {
  const { binaryType = "blob", autoReconnect = true, onMessage } = options;
  const [isConnected, setIsConnected] = useState(false);
  const [serverOffline, setServerOffline] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectCount = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMounted = useRef(true);
  const onMessageRef = useRef(onMessage);
  const connectRef = useRef<() => void>(() => {});
  const maxReconnects = 3;

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    connectRef.current = () => {
      if (!isMounted.current) return;
      void (async () => {
        const token = await getValidAccessToken();
        const url = new URL(`${WS_URL}${path}`);
        if (token) {
          url.searchParams.append("token", token);
        }

        const ws = new WebSocket(url.toString());
        ws.binaryType = binaryType;
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isMounted.current) {
            ws.close();
            return;
          }
          setIsConnected(true);
          setServerOffline(false);
          reconnectCount.current = 0;
        };

        ws.onclose = () => {
          if (!isMounted.current) return;
          setIsConnected(false);
          if (autoReconnect && reconnectCount.current < maxReconnects) {
            reconnectCount.current += 1;
            const delay = Math.min(1000 * Math.pow(2, reconnectCount.current), 10000);
            reconnectTimer.current = setTimeout(() => connectRef.current(), delay);
          } else if (reconnectCount.current >= maxReconnects) {
            setServerOffline(true);
          }
        };

        ws.onerror = () => {
          ws.close();
        };

        ws.onmessage = (event) => {
          onMessageRef.current?.(event);
        };
      })();
    };
  }, [path, binaryType, autoReconnect]);

  useEffect(() => {
    isMounted.current = true;
    connectRef.current();

    return () => {
      isMounted.current = false;
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
      const ws = wsRef.current;
      if (ws && ws.readyState !== WebSocket.CLOSED) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, [path, binaryType, autoReconnect]);

  const sendMessage = useCallback((data: string | ArrayBuffer | Blob) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  return { isConnected, serverOffline, sendMessage };
}

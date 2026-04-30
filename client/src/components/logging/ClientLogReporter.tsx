"use client";

import { useEffect } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function serializeArg(value: unknown): string {
  if (value instanceof Error) return value.stack || value.message;
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function postClientLog(event_type: string, severity: string, message: string, metadata_json?: Record<string, unknown>) {
  void fetch(`${API_URL}/api/logs/client`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_type,
      severity,
      message: message.slice(0, 4000),
      metadata_json: {
        href: window.location.href,
        user_agent: navigator.userAgent,
        ...metadata_json,
      },
    }),
    keepalive: true,
  }).catch(() => undefined);
}

export function ClientLogReporter() {
  useEffect(() => {
    postClientLog("client_ready", "info", "Website client mounted");

    const onError = (event: ErrorEvent) => {
      postClientLog("client_error", "error", event.message, {
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
        stack: event.error instanceof Error ? event.error.stack : undefined,
      });
    };

    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      postClientLog("client_unhandled_rejection", "error", serializeArg(event.reason));
    };

    const originalConsoleError = console.error;
    console.error = (...args: unknown[]) => {
      postClientLog("client_console_error", "error", args.map(serializeArg).join(" "));
      originalConsoleError(...args);
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onUnhandledRejection);

    return () => {
      console.error = originalConsoleError;
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
    };
  }, []);

  return null;
}

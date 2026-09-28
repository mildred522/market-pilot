"use client";

import { useEffect, useState } from "react";
import DashboardShell from "@/components/DashboardShell";
import { getDashboardOverview } from "@/lib/api";
import type { DashboardOverview } from "@/lib/types";

export function DashboardLoader() {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void getDashboardOverview()
      .then(setOverview)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "无法读取工作区"));
  }, []);

  if (error) return <main className="auth-loading" role="alert">{error}</main>;
  if (!overview) return <main className="auth-loading" aria-live="polite">正在加载工作区...</main>;
  return <DashboardShell initialOverview={overview} />;
}

"use client";

import BMapLoader from "@baidumap/jsapi-loader";
import { useEffect, useRef, useState } from "react";
import type { LocationCandidate } from "@/lib/types";

type Props = {
  candidates: LocationCandidate[];
  degraded: boolean;
  radiusMeters: number;
  selectedIndex: number;
  onSelect: (index: number) => void;
};

export function CandidateMap({ candidates, degraded, radiusMeters, selectedIndex, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<BMap.Map | null>(null);
  const namespaceRef = useRef<typeof BMap | null>(null);
  const fittedCandidatesRef = useRef("");
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const ak = process.env.NEXT_PUBLIC_BAIDU_MAP_BROWSER_AK;

  useEffect(() => {
    setReady(false);
    setError("");
    if (candidates.length === 0) {
      setError("当前没有可定位的候选区域。");
      return;
    }
    if (!ak) {
      setError("地图尚未配置，候选列表仍可正常使用。");
      return;
    }

    let active = true;
    BMapLoader.load({ ak, version: "4.0", protocol: "https", timeout: 12000 })
      .then((BMapApi: typeof BMap) => {
        if (!active || !containerRef.current) return;
        namespaceRef.current = BMapApi;
        mapRef.current = new BMapApi.Map(containerRef.current, {
          enableKeyboard: true,
          enableRotate: false,
          enableTilt: false,
          enableWheelZoom: true,
          minZoom: 9,
          maxZoom: 19
        });
        setReady(true);
      })
      .catch(() => {
        if (active) setError("地图加载失败，请检查浏览器端 AK 和域名白名单。");
      });

    return () => {
      active = false;
      mapRef.current?.destroy();
      mapRef.current = null;
      namespaceRef.current = null;
    };
  }, [ak, candidates.length]);

  useEffect(() => {
    const map = mapRef.current;
    const BMapApi = namespaceRef.current;
    if (!ready || !map || !BMapApi || candidates.length === 0) return;

    map.clearOverlays();
    const points = candidates.map((candidate) => new BMapApi.Point(
      candidate.transition_coordinates.longitude,
      candidate.transition_coordinates.latitude
    ));
    const selectedPoint = points[Math.min(selectedIndex, points.length - 1)];
    const tone = degraded ? "#a16207" : "#184b3f";

    map.addOverlay(new BMapApi.Circle(selectedPoint, radiusMeters, {
      strokeColor: tone,
      fillColor: degraded ? "#f8d991" : "#7fae9f",
      strokeOpacity: 0.8,
      fillOpacity: 0.16,
      strokeStyle: degraded ? "dashed" : "solid",
      enableClicking: false
    }));

    points.forEach((point, index) => {
      const selected = index === selectedIndex;
      const label = new BMapApi.Label(String(index + 1), {
        position: point,
        offset: new BMapApi.Size(-18, -36),
        enableClicking: true,
        styles: {
          alignItems: "center",
          background: selected ? tone : "#ffffff",
          border: `2px solid ${tone}`,
          borderRadius: "50% 50% 50% 8px",
          boxShadow: selected ? "0 5px 14px rgba(23, 33, 28, .25)" : "0 2px 8px rgba(23, 33, 28, .16)",
          color: selected ? "#ffffff" : tone,
          cursor: "pointer",
          display: "flex",
          fontSize: "13px",
          fontWeight: "800",
          height: selected ? "38px" : "34px",
          justifyContent: "center",
          lineHeight: selected ? "38px" : "34px",
          padding: "0",
          width: selected ? "38px" : "34px"
        }
      });
      label.setTitle(`候选 ${index + 1}：${candidates[index].name}`);
      label.addEventListener("click", () => onSelect(index));
      map.addOverlay(label);
    });

    const candidateKey = points.map((point) => `${point.lng},${point.lat}`).join("|");
    if (candidateKey !== fittedCandidatesRef.current) {
      fittedCandidatesRef.current = candidateKey;
      points.length === 1
        ? map.centerAndZoom(points[0], 15)
        : map.setViewport(points, { margins: [64, 64, 64, 64], zoomFactor: -1 });
    } else {
      map.panTo(selectedPoint);
    }
  }, [candidates, degraded, onSelect, radiusMeters, ready, selectedIndex]);

  return (
    <div className="candidate-map-shell">
      <div ref={containerRef} className="candidate-map" role="region" aria-label="候选商圈地图" tabIndex={0} />
      {!ready ? <div className="candidate-map-state" role={error ? "alert" : "status"}>{error || "正在加载候选地图..."}</div> : null}
      <div className="candidate-map-legend" aria-hidden="true"><span className={degraded ? "legend-degraded" : ""} />候选区域 · BD-09</div>
    </div>
  );
}

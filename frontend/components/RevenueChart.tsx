"use client";

import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RevenuePoint } from "@/lib/types";

export function RevenueChart({ data }: { data: RevenuePoint[] }) {
  const hasTrendWindow = data.length >= 4;
  const chartProps = {
    data,
    margin: { top: 8, right: 12, left: -12, bottom: 0 }
  };
  const axes = (
    <>
      <CartesianGrid stroke="#e2e8e5" strokeDasharray="3 4" vertical={false} />
      <XAxis dataKey="date" tick={{ fill: "#68736e", fontSize: 11 }} tickLine={false} />
      <YAxis tick={{ fill: "#68736e", fontSize: 11 }} tickFormatter={(value) => `¥${value}`} tickLine={false} />
      <Tooltip formatter={(value) => [`¥${Number(value).toLocaleString("zh-CN")}`, "营收"]} />
    </>
  );

  return (
    <section className="report-section revenue-section">
      <div className="section-heading">
        <div>
          <p className="kicker">Revenue pulse</p>
          <h2>{hasTrendWindow ? "营收趋势" : "每日营收"}</h2>
        </div>
        <p>{hasTrendWindow ? "按营业日观察增长方向与异常波动。" : `当前仅有 ${data.length} 个营业日，展示离散值而不推断长期趋势。`}</p>
      </div>
      <div className="chart-box" role="img" aria-label={`共 ${data.length} 个营业日的营收数据`}>
        <ResponsiveContainer height="100%" width="100%">
          {hasTrendWindow ? (
            <LineChart {...chartProps}>
              {axes}
              <Line activeDot={{ r: 5 }} dataKey="revenue" dot={{ r: 3 }} name="营收" stroke="#176b4b" strokeWidth={2.5} type="monotone" />
            </LineChart>
          ) : (
            <BarChart {...chartProps}>
              {axes}
              <Bar dataKey="revenue" fill="#176b4b" name="营收" radius={[3, 3, 0, 0]} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </section>
  );
}

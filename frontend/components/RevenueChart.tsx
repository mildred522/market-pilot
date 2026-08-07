"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RevenuePoint } from "@/lib/types";

export function RevenueChart({ data }: { data: RevenuePoint[] }) {
  return (
    <section className="report-section">
      <div className="section-heading">
        <h2>营收趋势</h2>
        <p>按天查看营收和订单变化。</p>
      </div>
      <div className="chart-box">
        <ResponsiveContainer height={260} width="100%">
          <BarChart data={data}>
            <CartesianGrid stroke="#e7e1d7" vertical={false} />
            <XAxis dataKey="date" tickLine={false} />
            <YAxis tickLine={false} />
            <Tooltip />
            <Bar dataKey="revenue" fill="#2f6f5e" name="营收" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

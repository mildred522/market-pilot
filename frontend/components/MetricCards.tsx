type Metric = {
  label: string;
  value: string | number;
  hint?: string;
};

export function MetricCards({ metrics }: { metrics: Metric[] }) {
  return (
    <section className="metric-strip" aria-label="核心指标">
      {metrics.map((metric) => (
        <div className="metric-item" key={metric.label}>
          <span>{metric.label}</span>
          <strong>{metric.value}</strong>
          {metric.hint ? <em>{metric.hint}</em> : null}
        </div>
      ))}
    </section>
  );
}

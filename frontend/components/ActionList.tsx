export function ActionList({ actions }: { actions: string[] }) {
  return (
    <section className="report-section">
      <div className="section-heading">
        <h2>行动清单</h2>
        <p>下一轮经营动作。</p>
      </div>
      <ol className="action-list">
        {actions.map((action) => (
          <li key={action}>{action}</li>
        ))}
      </ol>
    </section>
  );
}

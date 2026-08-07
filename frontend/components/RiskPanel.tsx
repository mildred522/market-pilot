export function RiskPanel({ risks }: { risks: string[] }) {
  return (
    <section className="report-section">
      <div className="section-heading">
        <h2>风险</h2>
        <p>需要优先核验或处理的问题。</p>
      </div>
      <ul className="report-list">
        {risks.length ? risks.map((risk) => <li key={risk}>{risk}</li>) : <li>暂无明显风险。</li>}
      </ul>
    </section>
  );
}

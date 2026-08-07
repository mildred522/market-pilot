export function EvidencePanel({ evidence }: { evidence: string[] }) {
  return (
    <section className="report-section">
      <div className="section-heading">
        <h2>证据</h2>
        <p>结论对应的数据依据。</p>
      </div>
      <ul className="report-list">
        {evidence.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

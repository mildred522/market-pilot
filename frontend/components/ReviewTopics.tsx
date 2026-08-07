export function ReviewTopics({ topics }: { topics: Record<string, number> }) {
  const entries = Object.entries(topics)
    .filter(([, value]) => value > 0)
    .sort((a, b) => b[1] - a[1]);

  return (
    <section className="report-section">
      <div className="section-heading">
        <h2>评论主题</h2>
        <p>从评论中提取高频体验问题。</p>
      </div>
      <div className="topic-list">
        {entries.map(([topic, count]) => (
          <div key={topic}>
            <span>{topic}</span>
            <strong>{count}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

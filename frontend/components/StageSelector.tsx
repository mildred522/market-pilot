import Link from "next/link";

export function StageSelector() {
  return (
    <nav className="stage-tabs" aria-label="业务模块">
      <Link href="/pre-open">开店前潜力分析</Link>
      <Link href="/operating">开店后经营诊断</Link>
    </nav>
  );
}

import { PreOpenForm } from "@/components/PreOpenForm";
import { LocationAnalysis } from "@/components/LocationAnalysis";
import { StageSelector } from "@/components/StageSelector";

export default function PreOpenPage() {
  return (
    <main className="shell">
      <StageSelector />
      <section className="page-header">
        <p className="kicker">Pre-open analysis</p>
        <h1>开店前潜力分析</h1>
        <p>用外部商圈证据判断位置，再结合财务假设评估具体铺位。</p>
      </section>
      <LocationAnalysis />
      <PreOpenForm />
    </main>
  );
}

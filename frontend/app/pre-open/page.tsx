import { PreOpenForm } from "@/components/PreOpenForm";
import { StageSelector } from "@/components/StageSelector";

export default function PreOpenPage() {
  return (
    <main className="shell">
      <StageSelector />
      <section className="page-header">
        <p className="kicker">Pre-open analysis</p>
        <h1>开店前潜力分析</h1>
        <p>录入预算、租金、竞品和加盟信息，先算项目能不能活。</p>
      </section>
      <PreOpenForm />
    </main>
  );
}

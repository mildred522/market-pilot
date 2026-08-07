import { ColumnMapper } from "@/components/ColumnMapper";
import { CsvUploader } from "@/components/CsvUploader";
import { StageSelector } from "@/components/StageSelector";

export default function OperatingPage() {
  return (
    <main className="shell">
      <StageSelector />
      <section className="page-header">
        <p className="kicker">Operating diagnosis</p>
        <h1>开店后经营诊断</h1>
        <p>上传订单、菜品成本和评论 CSV，为营收拆解和 Agent 诊断准备数据。</p>
      </section>
      <CsvUploader />
      <ColumnMapper />
    </main>
  );
}

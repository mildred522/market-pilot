import { AgentReport } from "@/components/AgentReport";
import { getAnalysis } from "@/lib/api";

type AnalysisPageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function AnalysisPage({ params }: AnalysisPageProps) {
  const { id } = await params;
  const report = await getAnalysis(Number(id));

  return (
    <main className="shell">
      <AgentReport report={report} />
    </main>
  );
}

import { AnalysisLoader } from "@/components/AnalysisLoader";

type AnalysisPageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function AnalysisPage({ params }: AnalysisPageProps) {
  const { id } = await params;
  return <AnalysisLoader analysisId={Number(id)} />;
}

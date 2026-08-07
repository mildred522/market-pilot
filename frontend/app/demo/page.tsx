import Link from "next/link";
import { StageSelector } from "@/components/StageSelector";

const demoSteps = [
  {
    title: "开店前：加盟奶茶店风险排雷",
    description: "使用默认问卷数据，提交后查看投资、租金、竞品和加盟风险。",
    href: "/pre-open"
  },
  {
    title: "开店后：面馆经营诊断",
    description: "进入经营诊断页，点击生成样例经营诊断，查看营收图、菜品矩阵和行动清单。",
    href: "/operating"
  }
];

export default function DemoPage() {
  return (
    <main className="shell">
      <StageSelector />
      <section className="page-header">
        <p className="kicker">Demo flow</p>
        <h1>面试演示路径</h1>
        <p>按两个业务模块演示：先讲开店前风险判断，再讲开店后经营诊断。</p>
      </section>
      <section className="demo-list">
        {demoSteps.map((step, index) => (
          <Link className="demo-row" href={step.href} key={step.href}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div>
              <h2>{step.title}</h2>
              <p>{step.description}</p>
            </div>
            <strong>开始</strong>
          </Link>
        ))}
      </section>
    </main>
  );
}

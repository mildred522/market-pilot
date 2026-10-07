import Link from "next/link";

const demoSteps = [
  {
    title: "电商：商品经营 Benchmark",
    description: "选择 Olist 历史快照，演示商品/SKU 粒度、热点、趋势、Talk 与管理员 Plan 审批边界。",
    href: "/commerce"
  },
  {
    title: "开店前：加盟奶茶店风险排雷",
    description: "使用默认问卷数据，提交后查看投资、租金、竞品和加盟风险。",
    href: "/pre-open#feasibility"
  },
  {
    title: "开店后：面馆经营诊断",
    description: "进入经营诊断页，点击生成样例经营诊断，查看营收图、菜品矩阵和行动清单。",
    href: "/operating#diagnosis"
  }
];

export default function DemoPage() {
  return (
    <main className="shell">
      <section className="page-header">
        <p className="kicker">Demo flow</p>
        <h1>面试演示路径</h1>
        <p>先演示电商历史数据链路，再回看餐饮 legacy 能力；两条路径的事实和权限边界分别说明。</p>
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

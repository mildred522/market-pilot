type ModuleEntry = {
  title: string;
  eyebrow: string;
  description: string;
  href: string;
  metrics: string[];
};

const modules: ModuleEntry[] = [
  {
    title: "开店前潜力分析",
    eyebrow: "Pre-open",
    description: "录入投资预算、租金、商圈和加盟信息，判断项目能不能开、风险在哪里。",
    href: "/pre-open",
    metrics: ["保本营业额", "投资压力", "商圈匹配", "加盟风险"]
  },
  {
    title: "开店后经营诊断",
    eyebrow: "Operating",
    description: "上传订单、菜品成本和评论数据，分析为什么不赚钱以及下周该改什么。",
    href: "/operating",
    metrics: ["营收拆解", "菜品矩阵", "差评主题", "行动清单"]
  }
];

export default function HomePage() {
  return (
    <main className="shell">
      <section className="intro" aria-labelledby="product-title">
        <div>
          <p className="kicker">Restaurant Agent MVP</p>
          <h1 id="product-title">餐饮门店分析 Agent</h1>
        </div>
        <p className="intro-copy">
          用确定性指标计算经营事实，再由 Agent 归因、校验证据并生成可执行建议。
        </p>
      </section>

      <section className="module-grid" aria-label="业务模块">
        {modules.map((module) => (
          <a className="module-link" href={module.href} key={module.href}>
            <span className="module-eyebrow">{module.eyebrow}</span>
            <h2>{module.title}</h2>
            <p>{module.description}</p>
            <ul>
              {module.metrics.map((metric) => (
                <li key={metric}>{metric}</li>
              ))}
            </ul>
            <span className="module-action">进入分析</span>
          </a>
        ))}
      </section>
    </main>
  );
}

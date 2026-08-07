import type { MenuMatrixItem } from "@/lib/types";

const labels = {
  star: "明星菜品",
  traffic: "引流菜品",
  profit: "利润菜品",
  problem: "问题菜品"
};

export function MenuMatrix({ items }: { items: MenuMatrixItem[] }) {
  return (
    <section className="report-section">
      <div className="section-heading">
        <h2>菜品矩阵</h2>
        <p>按销量和毛利贡献判断菜品角色。</p>
      </div>
      <div className="matrix-grid">
        {items.map((item) => (
          <div className={`matrix-item quadrant-${item.quadrant}`} key={item.item_name}>
            <span>{labels[item.quadrant]}</span>
            <strong>{item.item_name}</strong>
            <p>
              销量 {item.quantity} / 毛利 {item.gross_profit}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

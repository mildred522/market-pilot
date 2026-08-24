import type { MenuMatrixItem } from "@/lib/types";

const labels = {
  star: "明星菜品",
  traffic: "引流菜品",
  profit: "利润菜品",
  problem: "问题菜品"
};

const descriptions = {
  star: "高销量 · 高毛利",
  traffic: "高销量 · 低毛利",
  profit: "低销量 · 高毛利",
  problem: "低销量 · 低毛利"
};

const quadrants = ["star", "traffic", "profit", "problem"] as const;

export function MenuMatrix({ items }: { items: MenuMatrixItem[] }) {
  return (
    <section className="report-section">
      <div className="section-heading">
        <h2>菜品矩阵</h2>
        <p>按销量和毛利贡献判断菜品角色。</p>
      </div>
      <div className="matrix-board">
        {quadrants.map((quadrant, index) => {
          const groupedItems = items.filter((item) => item.quadrant === quadrant);
          return (
          <div className={`matrix-quadrant quadrant-${quadrant}`} key={quadrant}>
            <header>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div><strong>{labels[quadrant]}</strong><small>{descriptions[quadrant]}</small></div>
              <b>{groupedItems.length}</b>
            </header>
            <ul>
              {groupedItems.length ? groupedItems.map((item) => (
                <li key={item.item_name}>
                  <div><strong>{item.item_name}</strong><small>{item.category}</small></div>
                  <div><span>{item.quantity} 份</span><b>毛利 {item.gross_profit.toLocaleString("zh-CN")}</b></div>
                </li>
              )) : <li className="matrix-empty">当前没有菜品落入该象限</li>}
            </ul>
          </div>
          );
        })}
      </div>
    </section>
  );
}

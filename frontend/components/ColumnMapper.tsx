import type { UploadedFileResult } from "@/lib/types";

const fieldLabels: Record<string, string> = {
  order_id: "订单编号",
  order_time: "下单时间",
  channel: "渠道",
  item_name: "菜品名称",
  quantity: "数量",
  actual_amount: "实收金额",
  category: "菜品分类",
  sale_price: "售价",
  unit_cost: "单位成本",
  review_time: "评论时间",
  rating: "评分",
  content: "评论内容"
};

const fileLabels: Record<string, string> = {
  orders: "订单字段",
  menu_items: "菜品成本字段",
  reviews: "评论字段"
};

type ColumnMapperProps = {
  uploads: UploadedFileResult[];
  mappings: Record<string, Record<string, string>>;
  onChange: (fileType: string, standardField: string, sourceColumn: string) => void;
};

export function ColumnMapper({ uploads, mappings, onChange }: ColumnMapperProps) {
  if (!uploads.length) return null;

  return (
    <section className="mapping-surface">
      <div className="section-heading">
        <div>
          <p className="kicker">Column mapping</p>
          <h2>确认字段对应关系</h2>
        </div>
        <p>系统已自动识别常见中文和英文表头；不准确时可手动修改。</p>
      </div>
      <div className="mapping-groups">
        {uploads.map((upload) => {
          const mapping = mappings[upload.file_type] ?? {};
          const complete = upload.required_columns.every((field) => Boolean(mapping[field]));
          return (
            <section className="mapping-group" key={upload.file_type}>
              <div className="mapping-heading">
                <div>
                  <h3>{fileLabels[upload.file_type] ?? upload.file_type}</h3>
                  <p>{upload.filename} · {upload.row_count} 行</p>
                </div>
                <span className={complete ? "mapping-ready" : "mapping-pending"}>
                  {complete ? "映射完整" : "需要补充"}
                </span>
              </div>
              <div className="mapping-fields">
                {upload.required_columns.map((field) => (
                  <label key={field}>
                    <span>{fieldLabels[field] ?? field}</span>
                    <select
                      value={mapping[field] ?? ""}
                      onChange={(event) => onChange(upload.file_type, field, event.target.value)}
                    >
                      <option value="">请选择 CSV 列</option>
                      {upload.columns.map((column) => (
                        <option key={column} value={column}>{column}</option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </section>
  );
}

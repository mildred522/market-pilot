# 电商分析快照与 DuckDB Artifact

> 状态：2026-09-29 已完成 M10-A 和 M10-B 的薄适配。当前只引入本地 DuckDB 分析快照，不替换 SQLite 控制面；卖家、评价、支付和履约分析仍未完成。

## 决策

电商数据采用双层存储：

- SQLite 继续保存用户、项目、权限、计划、审计和快照元数据。
- DuckDB 保存可复现的电商分析数据 artifact，包括快照元数据和当前四类 canonical 表。

DuckDB 以单文件、嵌入式、只读分析的方式接入，不部署独立服务，不让前端直接连接，也不允许 Web 请求并发写入。当前本地导入 CLI 负责生成 artifact；Olist adapter 会先写入 source-specific staging，再投影到 canonical 表。

## Artifact 边界

一个 artifact 对应一个不可变 `snapshot_id`，文件名为：

```text
<artifact_root>/<snapshot_id>.duckdb
```

文件包含：

- `snapshot_metadata`
- `products`
- `skus`
- `orders`
- `order_items`

Artifact 生成后只读使用；相同 `snapshot_id` 必须具有相同 `content_hash`，内容冲突直接拒绝。临时文件写完并校验后原子替换，避免生成半成品数据库。

当前 SQLite 中的 JSON Dataset 仍然保留，作为 M8 兼容路径。后续完成 Olist 多表分析和快照 artifact repository 后，再评估是否将 API 指标读取迁移到 DuckDB；不得在没有对账测试的情况下删除兼容路径。

## 销售事实层

Olist v2 artifact 在原始 staging 之上提供只读商品销售事实查询。查询先按订单商品行粒度连接订单和 canonical 金额，再按商品或 SKU 聚合，使用订单状态、购买时间、卖家数和运费字段；取消或未知状态不会进入成交销售额，但会计入窗口的排除订单数。

当前开放的接口为：

```text
GET /commerce/benchmarks/{snapshot_id}/sales?start=...&end=...&item_level=product|sku
```

该事实层只表达商品销售额、销量、订单数、平均单价、卖家数和可用运费，不推导净利润、卖家实收或因果效果。热点商品和选品建议应建立在这些可追溯聚合之上。

## 导入方式

现有标准四表导入命令会额外生成 DuckDB artifact：

```bash
python -m scripts.import_commerce_benchmark <数据目录>
```

可以通过 `--artifact-root` 或 `COMMERCE_ARTIFACT_ROOT` 指定输出目录。原始数据、生成的 artifact 和本地数据库均不提交仓库。

## Olist 接入路径

Olist 不直接伪装成标准四表。当前 `OlistSourceAdapter` 已完成第一阶段保真导入：原始支持文件进入 `olist_*_staging` 表，订单、订单商品行和商品再投影到 canonical sales 数据，并生成可复现的 Olist Snapshot。适配器显式记录商品标题缺失、数量按源行默认为 1 等口径警告。

后续完整路径仍按以下顺序扩展：

1. 原始文件进入受忽略的 Raw 区，并生成文件哈希 manifest。
2. 使用 DuckDB staging 表保留 Olist 原始语义、来源文件、行数和文件哈希；当前基础 staging 已完成。
3. 先按订单、订单商品行、支付和评价各自粒度聚合，再进行连接。
4. 生成平台无关 canonical projection，供现有商品销售能力复用。
5. 保留卖家、评价、支付和履约数据，支持后续卖家诊断，不把整单金额错误归因给每个卖家。

DuckDB 不是最终的多租户在线数据库；商家身份、权限和控制面仍由应用数据库负责。未来若进入高并发 ToB 场景，应基于真实负载重新评估 PostgreSQL、列式仓库或托管分析服务，而不是预先把当前原型升级成重型基础设施。

# 电商分析快照与 DuckDB Artifact

> 状态：2026-09-29 已完成 M10-A。当前只引入本地 DuckDB 分析快照，不替换 SQLite 控制面，也不代表 Olist 原始数据适配已经完成。

## 决策

电商数据采用双层存储：

- SQLite 继续保存用户、项目、权限、计划、审计和快照元数据。
- DuckDB 保存可复现的电商分析数据 artifact，包括快照元数据和当前四类 canonical 表。

DuckDB 以单文件、嵌入式、只读分析的方式接入，不部署独立服务，不让前端直接连接，也不允许 Web 请求并发写入。当前本地导入 CLI 负责生成 artifact；后续 Olist adapter 将先写入 source-specific staging，再投影到 canonical 表。

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

## 导入方式

现有标准四表导入命令会额外生成 DuckDB artifact：

```bash
python -m scripts.import_commerce_benchmark <数据目录>
```

可以通过 `--artifact-root` 或 `COMMERCE_ARTIFACT_ROOT` 指定输出目录。原始数据、生成的 artifact 和本地数据库均不提交仓库。

## 后续 Olist 路径

Olist 不直接伪装成标准四表。后续 adapter 应按以下顺序处理：

1. 原始文件进入受忽略的 Raw 区，并生成文件哈希 manifest。
2. 使用 DuckDB staging 表保留 Olist 原始语义和来源行号。
3. 先按订单、订单商品行、支付和评价各自粒度聚合，再进行连接。
4. 生成平台无关 canonical projection，供现有商品销售能力复用。
5. 保留卖家、评价、支付和履约数据，支持后续卖家诊断，不把整单金额错误归因给每个卖家。

DuckDB 不是最终的多租户在线数据库；商家身份、权限和控制面仍由应用数据库负责。未来若进入高并发 ToB 场景，应基于真实负载重新评估 PostgreSQL、列式仓库或托管分析服务，而不是预先把当前原型升级成重型基础设施。

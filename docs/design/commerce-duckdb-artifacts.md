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
GET /commerce/benchmarks/{snapshot_id}/category-sales?start=...&end=...
```

品类趋势接口使用同一组当前/基线窗口：

```text
GET /commerce/benchmarks/{snapshot_id}/category-trends
  ?start=...
  &end=...
  &baseline_start=...
  &baseline_end=...
```

返回平台无关的品类趋势报告，包含品类并集、两侧销售事实和变化率；销售额变化率要求两侧币种一致，销量和订单变化率是独立的计数指标。

该事实层只表达商品销售额、销量、订单数、平均单价、卖家数和可用运费，不推导净利润、卖家实收或因果效果。热点商品和选品建议应建立在这些可追溯聚合之上。
品类概览直接按同一订单商品事实聚合，返回品类内去重的商品、订单和卖家数，以及销量和销售额；未分类商品保留独立分组。同一订单或卖家可能跨品类，因此订单数、卖家数不能跨品类相加。该概览只描述历史窗口，不生成品类级选品结论。

电商工作台现在可选择当前账号有权访问的项目，使用当前快照与两段比较窗口发起 Talk，或由管理员创建、审批 Plan 草案。没有项目时，用户需明确点击创建演示项目；不会自动在既有餐饮项目中写入电商订单。Talk 当前是关键词路由到确定性商品销售、趋势和热点工具，**不是开放域 LLM 问答**；不匹配的问题，以及要求缺失的成本、库存、实时、预测等信息的问题，会返回不支持，而不是假装回答。页面只展示各工具的前五项和快照/项目引用，不能把这当作订单级证据。Plan 创建会持久化草案；管理员可按项目和快照分页查看历史计划、重新打开详情及审批。列表只返回轻量元数据，权限由后端校验；审批不会触发实际采购、投放或任何外部动作。

历史 Olist 无法提供真实行动或干预结果。因此已审批的 Benchmark Plan 仅开放 `GET/POST /commerce/plans/{plan_id}/practice`，按步骤追加 `scenario`（人工演练情景）和 `reflection`（离线反思）记录。复盘须先有对应步骤的演练情景；服务端校验计划归属、管理员权限、审批状态及步骤范围，并在返回值标记 `benchmark_simulation`。这些记录与快照事实分开存储，不回写指标、Plan 步骤或组织记忆；用户不能据此声称已执行、已产生效果或证明因果。真实商家行动追踪需等 Store 授权、持续数据与来源核验具备后另行设计。

Olist 工作台和本地评测共用 `GET /commerce/benchmarks/{snapshot_id}/comparison-windows` 推荐窗口。它按原始订单购买时间计算覆盖期，从完整月份中找最近一对连续且有效订单数均达到 `max(20, 完整月最高有效订单数的 25% 向上取整)` 的月份，再验证以后一月月末为终点的两段等长 28 天窗口也都达到门槛；稀疏尾部月份不会冒充最近趋势。窗口订单数仅计入可成交状态；覆盖期来自原始时间戳而非 DuckDB 时区转换后的快照元数据。若无法选出密集窗口，等分原始覆盖期并返回 `split_coverage` 和显式警告：此时只能验证链路，不能据此判断经营趋势。

当前热点候选接口为：

```text
GET /commerce/benchmarks/{snapshot_id}/hot-products
  ?start=...
  &end=...
  &baseline_start=...
  &baseline_end=...
  &item_level=product|sku
  &limit=...
```

未显式提供基线窗口时，服务端自动使用与当前窗口等长的前一窗口。热点不是黑盒综合分数：候选只基于可复核的 `volume_leader`、`revenue_leader`、`momentum` 和 `multi_seller` 标签，并返回对应证据、增长率与证据等级。接口保留 `confidence` 字段，但当前仅根据标签数量分档，并非统计置信度或预测概率。它不等价于利润、因果关系或确定性选品结论。
热点至少需要当前商品有 3 笔订单；动量额外要求基线也至少 3 笔，并同时满足销量与销售额增长至少 20%。仅提高价格不能算作增长动量。

商品趋势接口为：

```text
GET /commerce/benchmarks/{snapshot_id}/trends
  ?start=...
  &end=...
  &baseline_start=...
  &baseline_end=...
  &item_level=product|sku
```

趋势结果保留当前窗口和基线窗口的商品并集，因此新出现或当前窗口未成交的商品不会被静默丢弃；窗口必须等长，增长率在基线值为 0 或商品只存在于单侧窗口时返回 `null`。

选品建议接口为：

```text
GET /commerce/benchmarks/{snapshot_id}/selection-recommendations
  ?start=...
  &end=...
  &baseline_start=...
  &baseline_end=...
  &item_level=product|sku
  &limit=...
```

建议只把销售证据转成待验证动作：`verify_growth`、`validate_new_product`、`protect_winner` 和 `review_decline`。结果会同时返回证据和风险提示，不把销售额当作利润，也不替代库存、成本、流量和商品质量判断。
增长核验与下降复核要求两侧各至少 3 笔订单且销量、销售额同向变化至少 20%；新品验证需要当前至少 3 笔订单。低样本不强行输出动作。单窗增长仅触发 `verify_growth`，不再触发 `scale_test`；它既不预测下一期走势，也不建议扩大备货或投放。若未来补齐连续窗口、成本、库存和流量证据，可另行设计带预算、停止条件的受控试验。
当前销售事实不足以推断商业紧迫度，建议统一采用中优先级；排序以两窗之间已发生的销售额绝对变化为依据（缺失视为零），不为展示而配额凑齐不同建议类型。

Talk 和 Plan 通过 `CommerceFactProvider` 选择事实来源：标准 CSV 快照继续使用内存 Dataset，`olist-canonical-v2` 快照使用只读 DuckDB artifact。这样 API 工作台、Talk 工具和 Plan 草案不会各自实现一套商品销售口径；artifact 不可用时，调用会显式失败，不回退到不一致的空数据。

Talk 目前先落地轻量语义层：`backend/app/commerce/semantic.py` 注册 `commerce.product_sales`、`commerce.category_sales`、`commerce.category_trends`、`commerce.product_trends` 和 `commerce.hot_products` 五个指标代号，维护别名、版本、来源、时间字段、成交状态、粒度、可用维度、证据字段、币种策略和包含/排除项。问句先解析为冻结的 `CommerceQuerySpec`，再绑定请求项目、快照和两个时间窗，最后选择已有工具；模型不生成 SQL，成本、库存、实时和预测问题仍直接拒答。运行时门禁要求快照为 ready、请求快照与事实快照一致、来源受该指标支持、两个窗口不重叠且各不超过 366 天；趋势和热点必须使用等长窗口。品类趋势由两窗统一品类销售事实构成，按品类并集呈现；无基线或基线为零时不计算相应变化率，币种不一致时仅不计算销售额变化率，不推断未来走势。工具返回后还会校验集合结构、商品/SKU/品类粒度、核心数值字段和比较两侧，失败时拒绝把结果包装成完成状态。响应将代号、版本和口径展示给前端，便于人工审查；这不是完整数仓语义层，尚未覆盖租户级 SQL 编译、租户数据库权限或商家数据。

控制面读取与事实层解耦：SQLite 快照记录另存轻量 `snapshot_json`，列表、Olist 指标入口和 Olist Talk/Plan 只读取元数据，不再反序列化整份订单 JSON；标准四表快照仍按原有 Dataset 路径计算。启动时兼容迁移从旧记录的 `dataset_json` 一次性回填元数据，保留完整旧数据及导入幂等性。当前改造降低请求内存与延迟，**不缩减 SQLite 文件体积**；如需删除 Olist 的冗余 JSON，必须先验证 artifact 可恢复性和迁移/回滚路径。

导入真实 Olist 数据后，可以执行完整事实链评测：

```bash
cd backend
python -m scripts.evaluate_olist_benchmark <Olist数据目录> --currency BRL
```

该命令不提交原始数据，只输出快照指纹、质量警告、商品与品类销售汇总、趋势并集、热点标签和选品建议数量，适合保存为本地或 CI 的 benchmark 摘要。品类销量、销售额和窗口订单总数必须与商品事实对账一致，不一致时评测失败；品类内去重的订单数、卖家数不做跨品类相加对账。
评测还对最近至多四组连续密集的 28 天窗口做时间留出：只用前两窗生成建议，再看第三窗的自然成交是否存在、销量与销售额是否继续同向变化。只有当期有成交的 `verify_growth` / `review_decline` 参与方向统计；新品和已无当期成交的下降复核只统计后续有无成交，不充当方向失败。每窗订单数须达到最新密集窗口较小订单数的四分之一（至少 20 笔）；数据不足返回 `unavailable`，不输出伪精度。滚动折之间有重叠，结果用于暴露规则对短期波动的敏感性，不是建议执行效果、因果收益或未来市场预测。不能为了追高留出集命中率，反复针对同一份 Olist 数据调门槛；后续需要另一时期或数据源作独立验证。

DuckDB artifact 目前没有保存完整质量审计报告，且旧 `dataset_json` 仍是标准 CSV 的兼容路径。因此不得直接清空或压缩现有 SQLite Olist 记录来声称节省空间；执行此类迁移前需另行设计可验证的备份、恢复和回滚。

## 独立 Talk 案例门禁

`backend/evals/olist_talk_cases.json` 固定了两个历史时间片的 17 个 Talk 案例：商品/SKU 销售与趋势、品类销售与增长、商品热点，以及混合粒度、成本/库存/实时/预测/评价/跨项目等拒答边界。每个案例还给出 `review_focus`、允许声明和禁止声明，供人工审查使用；它不复用滚动留出集的建议阈值。审查量表见 `backend/evals/olist_talk_review_rubric.md`。先按上文导入相同 Olist 数据、生成 DuckDB artifact，再执行：

```bash
cd backend
python -m scripts.evaluate_olist_cases ../data/olist --currency BRL > ../outputs/evals/olist-cases-v3.json
```

命令根据输入文件哈希校验 artifact，只读运行 Talk，并独立扫描原始 Olist `orders` / `order_items` CSV，对商品与 SKU 销售逐粒度核对销量、销售额、去重订单数及窗口纳入/排除订单数；商品、SKU 与品类趋势核对两侧事实、并集和变化率；热点案例核对候选并集、标签、排序、置信度、当前事实和增长率。时间窗口按 Olist 原始文件的无时区钟面解释、右端不包含。失败时非零退出，不打印原始订单或顾客数据。输出仅在本地忽略的 `outputs/evals/` 下保存；不可提交原始数据、artifact 或个人评测结果。

**自动通过不等于人工验收。** 每个案例保留 `human_review: pending`，需独立审查人员核对证据表达、热点解释有无误导、是否暗示实时/利润/行动效果，并记录反例与审查日期；当前既没有完整的 50–100 例人工标注，也没有实商家结果。此脚本直接调用服务，不是 API 鉴权或跨租户渗透测试；跨项目关键词拒答只是防误解，真正隔离仍须运行时权限门禁。后续引入另一来源和更大冻结案例集，不应依据这 17 例反复调参后宣称泛化。

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

# 文档知识导入手册

本文说明如何将审核后的公开资料导入 Market Pilot 的知识索引。在线追问不会下载或解析
文档；导入是显式离线操作，失败时保留上一个活跃版本。

## 组成

- `backend/data/knowledge/seed-manifest.json`：五条审核来源及时间、地域、品类口径。
- `backend/app/knowledge/storage.py`：路径、大小、媒体类型、哈希和公网地址检查。
- `backend/app/knowledge/parser.py`：Markdown、HTML、文本型 PDF 和普通 DOCX 的轻量结构化解析，复杂文档可选 Docling。
- `backend/app/knowledge/admission.py`：来源业务路由与解析后正文质量门禁。
- `backend/app/knowledge/chunker.py`：按标题层级与文档类型确定性切分。
- `backend/app/knowledge/fact_extractor.py`：从审核来源中确定性抽取带时间、地域和原文块
  溯源的结构化事实。
- `backend/app/knowledge/ingestion.py`：版本注册、暂存、计数校验、激活和回滚。
- `backend/app/knowledge/qdrant_store.py`：Qdrant dense/BM25 命名向量集合。

## 本地验证

只验证项目内方法文档，不需要网络、Docling 或 Qdrant：

```powershell
cd backend
python -m scripts.ingest_knowledge `
  --manifest data/knowledge/seed-manifest.json `
  --source-key market-pilot-evidence-rules-v1 `
  --index memory `
  --database storage/knowledge-validation.db `
  --storage-root storage/knowledge
```

返回 `ingested` 表示完成。原文、解析器、切分器和 embedding 模型均未变化时，再次导入应
返回 `unchanged`；处理链版本升级会基于同一原文创建新文档版本并重建索引。内存索引仅
用于单进程验证，不用于在线检索。

## WSL 原生 Qdrant（默认开发方案）

项目不要求 Docker Desktop。当前开发机已有 WSL2 Ubuntu，可以在 WSL 的 Linux
文件系统中运行 Qdrant 官方 MUSL 二进制：

```bash
QDRANT_VERSION=1.19.0
mkdir -p ~/.local/bin ~/.local/share/market-pilot/qdrant/storage
curl -L \
  "https://github.com/qdrant/qdrant/releases/download/v${QDRANT_VERSION}/qdrant-x86_64-unknown-linux-musl.tar.gz" \
  -o /tmp/qdrant.tar.gz
tar -xzf /tmp/qdrant.tar.gz -C ~/.local/bin qdrant

mkdir -p ~/.config/systemd/user
cp /mnt/c/path/to/pagent/ops/qdrant/market-pilot-qdrant.service \
  ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now market-pilot-qdrant.service
curl -fsS http://127.0.0.1:6333/healthz
```

Qdrant 数据必须保存在 WSL 内部的 ext4 文件系统，不放在 `/mnt/c`。Windows 端确认
`http://localhost:6333` 可访问后，安装可选 Python 依赖并执行导入：

```powershell
cd backend
python -m pip install -r requirements-rag.txt
```

### WSL 生命周期

仅启用 systemd 用户服务不能保证 WSL 在最后一个 Windows 客户端退出后继续常驻。
`MarketPilotLauncher.exe` 在 `KNOWLEDGE_RAG_ENABLED=true` 时负责完整生命周期：

1. 查询 `http://127.0.0.1:6333/healthz`，健康时复用现有 Qdrant。
2. 不健康时在配置的 WSL 发行版中启动 `market-pilot-qdrant.service`。
3. 保持一个启动器自有的 WSL 前台会话，等待 Qdrant 健康后再启动后端。
4. 停止时先停止自己启动的 systemd 服务，再结束 keepalive；不会停止原本已运行的服务。

默认发行版是 `Ubuntu`。需要覆盖时，在启动器环境中设置：

```powershell
$env:MARKET_PILOT_WSL_DISTRO = "Ubuntu-24.04"
```

后端 `/health` 使用短超时检查正式 collection；Qdrant 不可达或 collection 缺失时
API 仍可提供确定性经营分析，但健康状态为 `degraded`，知识检索走已有降级策略。

确认 `.env` 中的 `QDRANT_URL`、`QDRANT_API_KEY` 和 `QDRANT_COLLECTION` 后执行：

```powershell
python -m scripts.ingest_knowledge `
  --manifest data/knowledge/seed-manifest.json `
  --index qdrant
```

在线检索只读取已缓存的 dense 模型，不会在用户请求中访问模型仓库。首次离线导入需要
下载 Qwen3 权重时显式追加 `--allow-model-download`；下载失败后可以使用
`--skip-dense` 验证 BM25 降级路径。

本机已将 `Qwen3-Embedding-0.6B` 缓存到 `E:/AI/Models/Qwen3-Embedding-0.6B`，并通过
`KNOWLEDGE_DENSE_MODEL` 指向该目录。模型不依赖 C 盘 Hugging Face 缓存。

若本机透明代理将公网域名解析到 Fake-IP 保留段 `198.18.0.0/15`，可在已人工审核清单后
显式追加 `--allow-proxy-fake-ip`。该开关只影响离线导入，localhost、局域网和重定向仍会
被拒绝；不要在来源未经审核的清单上启用。

单个官方文件超过默认 25MiB 时，在核对响应大小后追加 `--max-download-mb 50`；参数
上限为 100MiB，不能由清单自行放宽。

集合预先创建 1024 维 `dense` 和 IDF 修正的 `sparse` 命名向量。正式导入同时写入
Qwen3 dense 向量和 `qdrant/bm25` 多语分词向量。Qdrant 的
BM25 文档向量和多语 tokenizer 用法以
[官方全文检索文档](https://qdrant.tech/documentation/search/text-search/full-text-search/)
为准。

## 可选容器部署

`compose.rag.yml` 仅作为 Linux、CI 或服务器上的标准化部署资产，不是本地开发
前置条件。确需容器时，使用 WSL 内的 Docker Engine 或其他 Linux 容器运行时，并使用
Docker named volume；不使用 Docker Desktop，也不将 Qdrant 数据 bind mount 到
Windows 文件系统。

## 审核规则

1. 清单中的来源必须人工确认发布方、URL、发布日期、数据周期和事实状态。
2. 本地路径必须位于清单目录内；远程地址必须解析到公网 IP。
3. 重定向不会自动跟随。来源迁移后先更新并复核清单 URL。
4. 能取得稳定原文时填写 `expected_sha256`，上游正文变化会触发新版本。
5. Markdown、HTML、文本型 PDF 和普通 DOCX 使用轻量解析器。PDF 按页保留溯源，并将
   连续数值行单独标记为表格；DOCX 保留标题、段落、编号列表和表格。
6. 导入失败会将新版本和任务标为 `failed`，不会替换已有活跃版本。
7. 扫描 PDF 不自动运行 OCR；无文本层时返回 `pdf_requires_ocr_error`。图片、文本框、复杂
   跨页表格等版式需要先人工复核，再使用 Docling 或外部 OCR 生成文本层副本。

## 自动准入与路由

人工确认来源身份后，系统仍会在写入 Qdrant 前执行两次自动判断：

1. 下载前按 `source_type` 路由。地图、评论和招聘明细进入带 TTL 的实时 Tool；新闻只作
   线索发现；商户经营数据进入项目隔离的私有分析链路；未知类型要求人工补充策略。
2. 解析后检查正文长度、乱码比例和中文 PDF 文本保真度。空壳页、编码损坏或中文抽取
   严重丢失会返回 `rejected`，不会暂存向量。

允许写入 Qdrant 的主要路由如下：

| 来源类型 | 路由 | 额外处理 |
|---|---|---|
| 政府统计 | `rag_and_structured_fact` | 同时建议抽取带口径的结构化事实 |
| 法规、标准元数据 | `normative_rag` | 保留生效日期、效力层级和适用范围 |
| 交易所披露、协会、学术、地产、品牌 | `rag_document` | 保留利益相关性和样本限制 |
| 地图、评论、招聘平台 | `live_tool` | 不进入静态 RAG，必须设置查询时间和过期时间 |
| 新闻媒体 | `discovery_only` | 回溯原始统计或披露来源后再形成经营结论 |
| 商户经营数据 | `private_analytics` | 按项目隔离，不进入公共知识集合 |

常见拒绝码包括 `source_requires_live_tool`、`source_is_discovery_only`、
`insufficient_indexable_text` 和 `chinese_pdf_text_loss`。调用方应展示具体原因，不能把
所有拒绝统一降级成“数据不足”。

真实来源样本审计不会写入正式集合，可独立运行：

```powershell
python scripts/audit_knowledge_sources.py
```

结果保存在 `outputs/source-sample-audit/`，包括原始样本、逐份决策和渠道对比报告。

## 结构化事实审核

政府统计和商业地产资料通过准入后，会在写入向量索引的同一轮导入中抽取首批指标：

- 餐饮收入金额与同比增速；
- 社会消费品零售总额；
- 零售物业空置率与首层平均租金；
- 住宿、餐饮服务人员工资中位数。

抽取器只处理明确数值和单位，不让 LLM 猜测表格口径。每条事实记录
`document_version_id`、`source_chunk_id`、数据周期、地域和品类。重复导入同一文档版本时会
整体替换该版本的候选事实，避免重复记录。

默认导入的事实为 `pending`，在线 `ReviewedKnowledgeFactRepository` 不会返回它们。人工已
核对清单与候选值后，重新导入时显式批准：

```powershell
python -m scripts.ingest_knowledge `
  --manifest data/knowledge/seed-manifest.json `
  --index qdrant `
  --approve-deterministic-facts
```

命令输出的 `facts_extracted` 是本版本抽取数量。`--approve-deterministic-facts` 只适用于本次
导入选择的来源，不是全局自动放行开关；事实仍需来自 `active` 文档版本，预测数据也继续受
检索策略限制。

## 端到端追问验证

在已有经营报告和正式 Qdrant 集合上运行脚本化 Planner。Planner 只固定检索意图，
Provider、Qdrant、embedding、reranker、EvidencePack、声明校验和答案分区均使用真实链路：

```powershell
python -m scripts.evaluate_followup_rag `
  --output ../outputs/evals/followup-rag-e2e.json
```

当前基线会调用一次 `external_industry_context`，取得 8 个
`retrieval_mode=hybrid_reranked` 的知识事实，引用产品上新知识块，并将结论展示在
“外部行业证据”而非“基于门店数据”分区。该脚本不替代真实在线 LLM 评测；本机未配置
回答模型时，它用于确定性验证除 Planner/Composer 之外的完整 Agent 链路。

## 当前限制

- WSL2 Ubuntu 中已安装 Qdrant 1.19.0，并以回环地址用户服务运行；其他开发机仍需执行
  上述一次性安装步骤。
- Query Compiler、Qwen3 dense/reranker、BM25/RRF、SQLite 事实降级和在线 Agent
  Provider 接入均已实现。reranker 仅在外部知识检索被规划后运行，失败时保留 RRF 顺序。
- Qwen3-Embedding-0.6B 与 Qwen3-Reranker-0.6B 已从 ModelScope 下载到 E 盘；CUDA
  13.0 PyTorch 已确认在 RTX 4050 Laptop GPU 上同时运行，双模型常驻显存约 2.28GiB。
- 正式集合当前包含 15 个 dense + BM25 知识块。50 个标注问题中，reranked hybrid 的
  块级 Hit@5 为 100%、MRR@5 为 0.975、关键事实命中率为 100%，热查询平均约 954ms。
  其中 10 条业务化同义问题的 Hit@5/MRR@5 均为 100%。语料规模仍小，结果主要证明
  检索链路、降级和评估方法有效。
- 代理环境下 Meituan/CCFA HTML 和本地方法论已完成真实导入；成都市统计局与港交所
  PDF 的持续传输仍受本机代理阻塞，SAMR 页面对直接客户端返回 403。
- 种子清单中的公开页面可能发生迁移，批量导入前应重新复核 URL 和许可证。

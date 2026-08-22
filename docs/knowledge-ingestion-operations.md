# 文档知识导入手册

本文说明如何将审核后的公开资料导入 Market Pilot 的知识索引。在线追问不会下载或解析
文档；导入是显式离线操作，失败时保留上一个活跃版本。

## 组成

- `backend/data/knowledge/seed-manifest.json`：五条审核来源及时间、地域、品类口径。
- `backend/app/knowledge/storage.py`：路径、大小、媒体类型、哈希和公网地址检查。
- `backend/app/knowledge/parser.py`：Markdown 内置解析和 Docling 可选解析。
- `backend/app/knowledge/chunker.py`：按标题层级与文档类型确定性切分。
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

返回 `ingested` 表示完成，使用同一个持久化索引再次导入相同正文应返回
`unchanged`。内存索引仅用于单进程验证，不用于在线检索。

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
5. PDF、DOCX 和 HTML 需要 Docling；Markdown 与纯文本使用内置解析器。
6. 导入失败会将新版本和任务标为 `failed`，不会替换已有活跃版本。

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

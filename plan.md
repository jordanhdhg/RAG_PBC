# DDR RAG V1 执行计划

## 一、目标与当前状态

项目目录：

```text
D:\pcb\AI_PCB
```

目标流程：

```text
DDR PDF
→ 文档登记
→ Docling 解析和切分
→ Local BGE-M3 Embedding
→ Qdrant Local 索引
→ Dense + BM25 混合检索
→ 当前 Codex 对话回答 / 可选 API 自动回答
→ 输出文档、版本、章节和页码
```

当前已经确认：

- Python 3.12.5 已在项目内建立独立运行时：`D:\pcb\AI_PCB\.runtime\managed-python\cpython-3.12.5-windows-x86_64-none\python.exe`。
- 当前推荐环境为项目内 `D:\pcb\AI_PCB\.venv-d312`，`include-system-site-packages = false`；先 dot-source `scripts\use_d312_env.ps1`，再使用该环境的 `python.exe`。
- 历史 C 盘 Python 和旧 `.venv` 仅保留作回退，不再作为默认执行入口。
- 已安装 `docling 2.107.0`、`openai 2.44.0`、`pydantic 2.12.5`、`pydantic-settings 2.14.2`、`PyYAML 6.0.2`、`typer 0.24.1`、`rich 14.3.3`。
- 当前确认缺少 `qdrant-client`、`fastembed` 和 `pytest`。
- 回答采用“双模式”：当前 Codex 对话辅助回答，以及可选 API 自动回答。
- 本文件写入后暂不安装库或执行其他开发工作。

## 二、V1 范围

V1 包含：

- 可搜索文本 PDF 的登记、解析和切分；
- 本地 GPU Embedding；
- Qdrant Local 本地向量索引；
- Dense + BM25 混合检索；
- DDR 类型、芯片型号、文档状态和版本过滤；
- 可追溯至原 PDF 页码的引用；
- 命令行搜索；
- 当前 Codex 对话回答；
- 可选 API 自动回答；
- 基础测试和检索评估。

V1 不包含 OCR、扫描件、多格式文档、网页界面、Agent、MCP、EDA API、PCB 文件读取、自动 Layout 检查、图片理解、知识图谱或 Reranker。

## 三、技术选型

| 组件 | V1 选择 |
|---|---|
| Python | 现有 Python 3.12.5 |
| Python 环境 | 项目内 `.venv-d312`，由 D 盘托管 CPython 创建、无系统站点包；旧 `.venv --system-site-packages` 仅回退 |
| PDF 解析 | Docling |
| 文档切分 | Docling HybridChunker |
| Dense Embedding | 本地 `BAAI/bge-m3`（RTX 4060，dense 1024 维） |
| 关键词检索 | BM25 sparse retrieval |
| 向量数据库 | Qdrant Local Mode |
| 检索融合 | Dense + Sparse，RRF 融合 |
| 回答模型 | 用户可选，默认 `gpt-5.6-luna` |
| 用户入口 | Typer 命令行 CLI |
| 配置 | YAML + `.env` |
| 测试 | pytest + DDR 问题集 |

V1 不引入 LlamaIndex 或 LangChain，直接连接 Docling、Qdrant 和 OpenAI SDK，使解析、切分、检索、引用和回答各阶段都可以单独观察与调试。

## 四、双模式回答

### 模式一：当前 Codex 对话回答

```text
本地程序检索 DDR 知识库
→ 输出最相关原文和引用
→ Codex 读取检索结果
→ 在当前对话中回答
```

命令：

```powershell
.\.venv\Scripts\python.exe -m ddr_rag search `
  "DDR4 地址线与 CK 如何匹配？" `
  --memory-type DDR4 `
  --format json
```

然后在当前对话中要求：

```text
请根据本地 DDR RAG 的检索结果回答这个问题。
```

这种方式不产生回答模型或 Embedding API 费用；本地 BGE-M3 生成文档与查询向量，不需要 OpenAI API Key。

### 模式二：API 自动回答

```powershell
.\.venv\Scripts\python.exe -m ddr_rag ask `
  "DDR4 地址线与 CK 如何匹配？" `
  --memory-type DDR4 `
  --limit 6 `
  --format text
```

当前实现由 `config.yaml` 的 `generation` 段选择 DeepSeek 模型；API Key 仅从本地 `.env` 的 `DEEPSEEK_API_KEY` 读取。未配置 Key 时，`ask` 会明确提示，且本地 `search` 不受影响。

ChatGPT/Codex 订阅与 API 平台分别计费，订阅额度不能直接提供给本地 Python 程序：

[OpenAI 官方计费说明](https://help.openai.com/en/articles/9039756)

## 五、目录骨架

```text
D:\pcb\AI_PCB\
├─ plan.md
├─ README.md
├─ pyproject.toml
├─ .env.example
├─ .gitignore
├─ config.yaml
├─ data/
│  ├─ raw/
│  │  ├─ vendor/
│  │  ├─ standards/
│  │  ├─ company/
│  │  ├─ fab/
│  │  └─ experience/
│  ├─ catalog/
│  │  └─ documents.yaml
│  ├─ parsed/
│  │  ├─ JSON/
│  │  └─ Markdown/
│  ├─ chunks/
│  │  └─ chunks.jsonl
│  └─ index/
├─ src/
│  └─ ddr_rag/
│     ├─ __init__.py
│     ├─ __main__.py
│     ├─ config.py
│     ├─ schemas.py
│     ├─ catalog.py
│     ├─ parser.py
│     ├─ chunker.py
│     ├─ embedder.py
│     ├─ vector_store.py
│     ├─ ingest.py
│     ├─ retriever.py
│     ├─ answerer.py
│     ├─ citations.py
│     └─ cli.py
├─ prompts/
│  └─ answer_system.txt
├─ evals/
│  ├─ questions.yaml
│  ├─ expected_sources.yaml
│  └─ results/
├─ logs/
│  ├─ ingestion/
│  └─ queries/
└─ tests/
   ├─ test_catalog.py
   ├─ test_chunking.py
   ├─ test_retrieval.py
   └─ test_citations.py
```

## 六、执行任务表

| 状态 | 步骤 | 工作内容 | 完成标准 |
|---|---:|---|---|
| 已完成 | 1 | 在 `D:\pcb\AI_PCB` 写入最终 `plan.md` | 文件内容完整且未执行其他开发步骤 |
| 已完成 | 2 | 用现有 Python 创建 `.venv --system-site-packages` | 复用现有库，不重复安装大型依赖 |
| 已完成 | 3 | 记录安装前的包列表，安装 `qdrant-client[fastembed]` 和 `pytest` | 所需模块均能导入 |
| 已完成 | 4 | 比较安装前后的包列表并汇报 | 列出直接安装库、自动依赖、版本、升级和冲突 |
| 已完成 | 5 | 创建目录骨架、`pyproject.toml`、`.gitignore`、`.env.example` 和 `config.yaml` | 项目包能够正常导入 |
| 已完成 | 6 | 实现 YAML、环境变量和路径配置系统 | 模型、路径和检索参数均不散落在代码中 |
| 已完成 | 7 | 定义 Document、Chunk、SearchResult、Citation 和 Answer 数据结构 | 非法数据给出明确错误 |
| 已完成 | 8 | 创建 `documents.yaml` 模板，实现 `catalog validate` | 检查文件、ID、版本、状态和 SHA-256 |
| 已完成 | 9 | 使用 Docling 实现 PDF 解析 | 已完成首份文档的 JSON 与 Markdown 输出，保留章节、表格和页码 |
| 已完成 | 10 | 使用 HybridChunker 切分文档 | 795 块，初始上限600 Token，每块具有完整来源元数据 |
| 已完成 | 11 | 本地 BGE-M3 批量生成向量 | RTX 4060，795 × 1024 float32 向量，验证通过 |
| 已完成 | 12 | 使用 Qdrant Local Mode 建立索引 | 795 点、1024 维 Cosine，程序重启后仍可读取 |
| 已完成 | 13 | 实现 `ingest --doc-id`、`ingest --all` 和显式 `--replace` | 完整本地编排验证通过；已有派生产物必须显式 `--replace` |
| 已完成 | 14 | 实现 Dense 检索及元数据过滤 | 本地 BGE-M3 + Qdrant，带页码与 DDR 类型过滤 |
| 已完成 | 15 | 增加 BM25 Sparse 检索，使用 RRF 融合 | 15,072 词项；型号、信号名、数值与语义问题均可检索 |
| 已完成 | 16 | 实现 `search` 命令和 JSON 输出 | Dense/Sparse/Hybrid，展示原文、文档、版本、章节和页码 |
| 已完成 | 17 | 实现基于 Chunk ID 的引用系统 | `C1…Cn` 仅由当前检索 Chunk 生成，外部/篡改引用会被拒绝 |
| 已完成 | 18 | 实现可选的 `ask` API 模块 | Hybrid 检索后只发送限定证据给 DeepSeek；回答必须通过本地 `[C#]` 引用校验 |
| 已完成 | 19 | 建立30个可回答和10个不可回答的问题 | 40 题版本化 YAML；本地锚点验证覆盖中英、数值、型号、版本、比较与拒答 |
| 已完成 | 20 | 实现 `eval run` 并编写 README | 离线检索 93.3%、逐题回答引用 93.3%、拒答 90% 均达标；安装、使用、API 边界与限制文档已完成 |
| 已完成 | 21 | V1.1 离线 Hybrid 检索优化 | 查询侧双语术语、连字符信号名、空格单位与 JEDEC 合规短语扩展；30/30 all-anchor hit@5、31/31 anchor recall@5，零 API |
| 已完成 | 22 | R05 严格拒答输出保护与受控在线补测 | 无引用且非固定拒答时最多纠正重试一次；完整题集先校验再用 `--question-id` 筛选；`DDR_REFUSE_05` 1/1 通过、实际 1 次 DeepSeek 请求 |
| 已完成 | 23 | V1.1 全量在线回答基线 | 40 题完整评测：30/30 引用覆盖、10/10 拒答，36 次 DeepSeek 请求、0 错误；报告可本地重评分复现 |

## 七、模型配置

`config.yaml` 初始配置：

```yaml
embedding:
  provider: local_bge_m3
  model: BAAI/bge-m3
  device: cuda:0
  batch_size: 8
  max_length: 1024
  normalize_vectors: true

generation:
  enabled: true
  provider: deepseek
  model: deepseek-flash
  base_url: https://api.deepseek.com
  api_key_env: DEEPSEEK_API_KEY
  reasoning_effort: none
  max_output_tokens: 1200

retrieval:
  mode: hybrid
  dense_candidates: 20
  sparse_candidates: 20
  final_top_k: 6
  active_documents_only: true
```

当前 `ask` 适配器只支持 `generation.provider: deepseek`。`reasoning_effort: none` 会显式关闭 DeepSeek Flash 的默认思考模式，以稳定取得可引用的最终正文；配置为 `low`、`high` 或 `max` 时才启用思考模式。更换回答模型不需要重建本地索引，但需要确认提供方适配器支持该模型；更换 Embedding 模型必须重建全部向量。本地 BGE-M3 的模型、Hub/Xet 与临时缓存均固定在 D 盘项目目录。

参考：

- [OpenAI 模型列表](https://developers.openai.com/api/docs/models)
- [OpenAI text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small)
- [OpenAI Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)

## 八、CLI 接口

```powershell
.\.venv\Scripts\python.exe -m ddr_rag catalog validate

.\.venv\Scripts\python.exe -m ddr_rag parse --doc-id TI-AM62-HDG

.\.venv\Scripts\python.exe -m ddr_rag ingest --doc-id TI-AM62-HDG

.\.venv\Scripts\python.exe -m ddr_rag ingest --all

.\.venv\Scripts\python.exe -m ddr_rag search `
  "DDR4 时钟布线要求是什么？" `
  --memory-type DDR4

.\.venv\Scripts\python.exe -m ddr_rag ask `
  "DDR4 时钟布线要求是什么？" `
  --memory-type DDR4 `
  --limit 6 `
  --format text

.\.venv\Scripts\python.exe -m ddr_rag eval run
```

## 九、错误处理

- PDF 未登记：拒绝解析。
- 元数据不完整：拒绝入库。
- 文档解析失败：保留错误日志，不建立索引。
- API 暂时失败：有限次数指数退避重试。
- API Key 缺失：需要在线能力的命令给出明确提示。
- 文档哈希变化：要求显式 `--replace`。
- 没有可靠证据：回答“当前知识库不足以判断”。
- 多份文档冲突：并列展示来源，不自动裁决。
- 表格或图片无法可靠解析：引用相关页面并提示查看原 PDF。
- 模型不存在或无调用权限：返回明确错误，不自动换模型。
- Embedding 模型与索引不一致：拒绝查询并提示重建索引。

## 十、测试与验收

单元测试：

- 文档字段和状态校验；
- SHA-256 变化检测；
- Chunk ID 唯一性；
- 页码和章节元数据保留；
- 配置与 API Key 缺失提示；
- Citation 只能引用真实 Chunk；
- 重复入库不产生重复数据；
- 修改 `generation.model` 不会触发本地索引重建；不受当前 DeepSeek 适配器支持的 provider 会给出明确错误；
- 更换回答模型不会触发索引重建。

集成测试：

- 从一份文本 PDF 完成解析、切分、Embedding、索引、检索和回答；
- 中文问题检索英文资料；
- DDR4 过滤不会返回 LPDDR4 专用规则；
- `superseded` 文档不会默认参与回答；
- 精确型号、表号和信号名能被关键词检索命中；
- API 临时失败可以重试；
- 重启程序后 Qdrant 本地索引仍可使用；
- 两种回答模式使用相同检索证据。

V1 验收指标：

- 至少一份真实 DDR 文档跑通完整链路；
- `search` 可以独立展示 Top-K 证据；
- `ask` 的主要结论都有真实引用；
- 引用可追溯到原始 PDF 页面；
- 30个可回答问题中，正确资料进入 Top-5 的比例不低于90%；
- 10个不可回答问题中，至少9个明确拒答；
- API Key 不进入源代码、日志或测试结果；
- 原始 PDF 不被修改或覆盖。

## 十一、安装与安全约束

- 不重新安装 Python。
- 不全局重装已有库。
- 新库安装在项目 `.venv` 中。
- 安装前后保存包列表并计算差异。
- 安装完成后报告实际新增和更新的库。
- 不启用 Docker。
- 不批量删除任何文件或目录。
- 不修改原始 DDR PDF。
- 不把 API Key 写入源代码、配置模板或日志。
- 第一批资料必须是允许发送至在线 API 的公开或已授权资料。
- 开发期 API 预算建议设置为5～10美元。
- 本次只创建 `plan.md`，不执行其他步骤。

## 十二、V1.2 多格式与来源身份（已完成）

- `DocumentRecord`、Chunk、Qdrant payload 和 Citation 已贯通资料类别、来源身份、PDF/DOCX/PPTX 格式、适用型号、来源文件哈希、解析器版本及格式化原文位置。
- `ask` 的正文继续使用受控 `[C#]`；文本输出末尾只列出实际引用且验证通过的“答案来源”。未审核经验明确标注，提示词要求说明适用条件和来源冲突。
- Docling 入口已支持 PDF、DOCX、PPTX。PDF 使用页码；DOCX 使用标题路径、结构元素和原文短摘；PPTX 使用原始幻灯片号，并排除隐藏页、空白页、备注与批注。纯图片资料不生成可回答 Chunk。
- 同一芯片型号可对应多份活动资料，Dense 与 BM25 使用同一文档集合过滤；显式 `--doc-id` 仍优先。
- V1.2 独立产物位于 `data/chunks/v1.2` 与 `data/index/v1.2`，活动集合为 `ddr_knowledge_v1_2`；`config.v1.1.yaml` 和旧产物保留用于回退。
- 验收：782 个 PDF Chunk 的 ID、正文与页码保持不变；V1.2 元数据完整；真实 DOCX/PPTX 测试及损坏/纯图片边界通过；完整测试 58 项通过；离线 40 题为 30/30 all-anchor hit@5 和 31/31 expected-anchor recall@5。未运行在线回答评测。

## 十三、通用硬件 RAG V2（已批准，阶段 1–5 已完成）

- 项目范围从 DDR 专库升级为“共用平台、领域隔离、显式跨领域”的通用硬件 RAG；DDR V1.2 原始资料、配置、索引和评测基线必须完整保留。
- V2 将新增必填 `domains`、`topics` 与可选 `memory_types`，支持高速接口、电源管理、电气安规和信号完整性；目录级分类可由章节/Chunk 分类覆盖，避免把 SoC 文档的非 DDR 章节错误标为 DDR。
- 使用独立 `config.hardware-v2.yaml`、目录、Chunk、向量、Qdrant 集合和 BM25 产物；新增字段后必须重建 V2 派生产物，不能修改 V1.2 标签代替迁移。
- 查询默认仅检索一个可靠领域；`--domain` 可重复，供用户显式发起跨领域检索；歧义问题只要求澄清，不调用回答 API。
- 阶段 1 已完成：受控词表、统一模型、可选 `memory_types`、版本化章节分类映射及通用评测契约已实现；完整本地测试为 66 项，V1.2 正式目录、Chunk、配置和索引保持不变。
- 阶段 2 已完成：统一 `QueryScope`、只读 `route`、显式/自动单领域路由、重复 `--domain`、Dense/BM25 同范围、按领域 RRF 与轮转去重、通用 CLI/提示词/评测入口及临时 V2 fixture 已实现。完整本地测试为 77 项；V1.2 零 API 离线回归保持 30/30 all-anchor hit@5、31/31 anchor recall@5。
- 阶段 3 已完成并经用户确认：四份 PDF 已按来源身份哈希一致复制，旧 PPT 已非覆盖转换为 38 页 PPTX，结构/备注/几何与 38/38 张 PowerPoint 原生渲染均和原件一致；独立 V2 配置及 8 文档目录已创建并以 0 错误、0 警告通过校验，用户于 2026-09-29 明确确认“PPT 转换无误”。
- 阶段 4 已完成：独立 V2 解析、1,694 个 Chunk、1,694×1,024 BGE-M3 向量、`hardware_knowledge_v2` Qdrant 集合和 22,673 词项 BM25 索引均已构建。90 题由冻结 DDR 40 题和新增 V2 50 题组成；旧题回归为 30/30 all-anchor hit@5、31/31 expected-anchor recall@5，新增单资料题为 28/30（93.3%），跨领域为 6/6，歧义澄清为 4/4。完整回归 `82 passed in 44.66s`，阶段内零回答 API。
- 阶段 5 已完成：本地查询术语扩展后，V2 Top-6 达到 36/36 all-anchor、42/42 expected-anchor，完整测试为 86 项。经用户明确批准，新增 50 题的 DeepSeek 在线评测实际执行 46 次请求，另有 1 次单题预检，阶段合计 47 次；可回答题全部预期来源引用 35/36（97.2%），拒答 14/14（100%），歧义 4/4 零 API，逐题错误 0。人工复核为 29/36 题完整覆盖、7/36 部分覆盖、0 题明确矛盾或无依据硬编；详见 `evals/hardware-v2/stage5_acceptance.md`。
- 2026-10-06 增量接入已完成：仅新增高云 TN662 1.3.2 与 UG206 1.9.3，V2 现为 10 文档、1,825 个 Chunk/向量/Qdrant 点和 1,825 条 BM25 记录（24,530 词项）。原 8 文档 Chunk 哈希逐份不变；冻结 DDR 40 题仍为 30/30 与 31/31，冻结 V2 50 题 Top-6 为 35/36（97.2%）、单资料 30/30、跨领域 6/6、歧义 4/4。唯一精确锚点变化来自新增且相关的 TN662 PDN 证据，详见 `evals/hardware-v2/post_gowin_ingest_acceptance.md`；本次零回答 API。

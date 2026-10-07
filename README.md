# 通用硬件 RAG（V1.2 默认基线 / V2 阶段 5 已完成）

面向硬件设计资料的本地优先 RAG 系统。它将已登记的 PDF、DOCX、PPTX 解析、结构化切分并建立本地 Dense + Sparse 索引，可以返回领域、主题、资料类别、来源身份和可回查的原文位置；只有已完成本地路由和检索后，显式执行 `ask` 或 API 问答评测时才可能调用 DeepSeek。

默认 `config.yaml` 继续使用已验收的 DDR V1.2：3 份 active 厂商资料、782 个 Chunk、本地 BGE-M3、Qdrant Local、BM25/RRF、多格式入口、来源分类、可验证引用、DeepSeek 问答以及冻结 40 题评测。独立 V2 已完成阶段 1–5，并于 2026-10-06 增量接入 TN662 1.3.2 与 UG206 1.9.3：当前共 10 份资料、1,825 个 Chunk、1,825×1,024 BGE-M3 向量、`hardware_knowledge_v2` Qdrant 集合和 BM25 索引；冻结 90 题继续用于回归。离线使用 `config.hardware-v2.yaml`；只有显式改用 `config.hardware-v2-online.yaml` 才启用 V2 DeepSeek 回答。

## 核心边界

- `route`、`catalog`、`parse`、`chunk`、`embed`、`index`、`bm25`、`ingest`、`search`、`eval validate` 和默认的 `eval run` 全部在本地执行，不需要 API Key。
- `ask` 和显式的 `eval run --with-answer-eval` 会调用 DeepSeek 并产生费用。
- `route` 只做确定性本地范围解析，不加载 Embedding、不检索、不调用模型。无法可靠确定领域时，`search`/`ask` 要求用 `--domain` 澄清，并在任何回答 API 调用前退出。
- API 请求只包含当前问题、允许引用列表、解析质量提示，以及本次命中的有限 Chunk 的正文、资料类别、来源身份、适用型号和原文定位元数据；不会上传整份源文件、向量文件、Qdrant/BM25 索引或评测标准答案。
- `.env` 中的 Key 只用于请求认证，不会进入提示词、源码或评测报告；`.env` 已被 `.gitignore` 排除。
- 回答是工程资料检索辅助，不能替代原厂最新文档、SI 仿真、PCB/器件审查或工程签核。

## 数据流程

```text
登记 PDF / DOCX / PPTX
  → Docling 解析（Markdown + 带来源结构的 JSON）
  → HybridChunker 结构化切分（最大 600 token）
  → 本地 BGE-M3 向量 + 本地 BM25
  → 本地单领域路由，或显式重复 --domain 的跨领域范围
  → 各领域内 Qdrant Dense / BM25 Sparse / RRF Hybrid 检索
  → 跨领域轮转合并、去重
  → 本轮结果内绑定的 [C#] 引用（领域、主题、资料类别、来源身份、章节、页/幻灯片/结构元素、来源路径）
  → 可选 DeepSeek 回答（本地验证引用）
```

## 已验证环境

- Windows 64 位
- Python 3.12.5
- AMD Ryzen 7 7840H
- 16 GB RAM
- NVIDIA RTX 4060 Laptop GPU，8 GB 显存
- CUDA PyTorch 2.10.0+cu128
- Docling 2.107.0
- Transformers 5.12.1
- Qdrant Client 1.19.1
- OpenAI Python SDK 2.44.0（使用 OpenAI 兼容接口访问 DeepSeek）

当前项目路径和首选 Python：

```powershell
Set-Location D:\pcb\AI_PCB
. .\scripts\use_d312_env.ps1
.\.venv-d312\Scripts\python.exe --version
```

程序解析资料时使用 CPU 4 线程；BGE-M3 向量化固定使用 `cuda:0`。当前没有经过验收的 CPU Embedding 回退路径。

## D 盘独立运行环境（当前推荐）

当前运行环境完全位于项目 D 盘目录：托管 CPython 3.12.5 在 `.runtime\managed-python\`，虚拟环境在 `.venv-d312\`，并且 `include-system-site-packages = false`。因此它不依赖旧 C 盘 Python 的解释器或包；旧 `.venv` 原样保留，仅用于必要时回退。

每个新的 PowerShell 会话先运行：

```powershell
Set-Location D:\pcb\AI_PCB
. .\scripts\use_d312_env.ps1
```

该脚本只修改当前会话的 `TEMP`、`TMP`、pip、uv、Hugging Face 与 tiktoken 缓存位置，将它们固定在 D 盘；不会修改系统 PATH、注册表、`.env` 或旧 `.venv`。日常命令使用：

```powershell
.\.venv-d312\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv-d312\Scripts\python.exe -m ddr_rag catalog validate
.\.venv-d312\Scripts\python.exe -m ddr_rag eval validate --config config.hardware-v2.yaml --questions evals/hardware-v2/hardware_v2_questions.yaml
```

环境已通过 `pip check`、CUDA PyTorch、核心依赖、项目 CLI 和完整 `82 passed, 2 warnings in 20.26s` 回归。两条警告均来自 Typer 对 Click API 的弃用提示。项目离线 `cl100k_base` 编码缓存也已固定在 `data/cache/tiktoken/`，无需在正常离线运行时下载。

## 旧 `.venv` 的手工重建参考（不作为当前推荐）

下列内容仅保留为历史记录，描述旧的 C 盘 Python + `.venv` 路径。新的工作、测试和操作请使用上面的 `.venv-d312`；不要以同一主次版本的 Windows 安装器尝试创建并行 D 盘 Python 实例。

### 1. 旧 `.venv` 的历史创建方式

```powershell
Set-Location D:\pcb\AI_PCB
& "C:\Users\jordanhdhg\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv
```

不建议新环境使用 `--system-site-packages`，否则可能复用系统中的 CPU 版 PyTorch。

### 2. 将本次 PowerShell 的缓存与临时目录指向 D 盘

```powershell
New-Item -ItemType Directory -Force .\data\cache\pip, .\data\cache\tmp, .\data\models\bge-m3 | Out-Null
$env:PIP_CACHE_DIR = "D:\pcb\AI_PCB\data\cache\pip"
$env:TEMP = "D:\pcb\AI_PCB\data\cache\tmp"
$env:TMP = "D:\pcb\AI_PCB\data\cache\tmp"
$env:HF_HOME = "D:\pcb\AI_PCB\data\models\bge-m3"
$env:HF_HUB_CACHE = "D:\pcb\AI_PCB\data\models\bge-m3\hub"
$env:HF_XET_CACHE = "D:\pcb\AI_PCB\data\models\bge-m3\xet"
```

这些环境变量只影响当前 PowerShell。程序加载 BGE-M3 时也会根据 `config.yaml` 自动把 Hugging Face 缓存固定到项目的 `data/models/bge-m3`。

### 3. 安装 CUDA PyTorch 和项目依赖

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cu128 torch==2.10.0+cu128
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

检查 CUDA：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CUDA unavailable')"
```

预期至少看到 `2.10.0+cu128`、`True` 和 RTX 4060。若使用其他显卡或 CUDA 构建，应安装相匹配的官方 PyTorch wheel，并重新完成向量化验收。

### 4. 首次下载 BGE-M3

运行时采用 `local_files_only=True`，因此必须先把模型下载到项目缓存。此步骤需要联网，仅首次安装需要：

```powershell
.\.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3', cache_dir=r'D:\pcb\AI_PCB\data\models\bge-m3')"
```

当前模型缓存约 4.25 GiB。Windows 未启用开发者模式时可能出现 Hugging Face symlink 警告；这不阻塞使用，但会增加 D 盘占用。

## DeepSeek 配置

只有 `ask` 和 `eval run --with-answer-eval` 需要 Key。首次配置时，如果 `.env` 尚不存在：

```powershell
Copy-Item .env.example .env
```

然后只在本机编辑 `.env`：

```dotenv
DEEPSEEK_API_KEY=在这里填写你的_Key
DDR_RAG_PROJECT_ROOT=D:\pcb\AI_PCB
```

不要提交、打印或复制真实 Key 到日志。`config.yaml` 当前使用：

```yaml
generation:
  enabled: true
  provider: deepseek
  model: deepseek-flash
  base_url: https://api.deepseek.com
  api_key_env: DEEPSEEK_API_KEY
  reasoning_effort: none
  max_evidence_chunks: 6
```

`reasoning_effort: none` 会显式关闭 DeepSeek Flash 默认 thinking，避免只有推理内容而最终正文为空。

## 快速使用

以下命令均从 `D:\pcb\AI_PCB` 执行，默认只使用 `active` 文档。若从其他目录运行，必须通过 `-c D:\pcb\AI_PCB\config.yaml` 显式指定配置文件。

### 查看 CLI

```powershell
.\.venv\Scripts\python.exe -m ddr_rag --help
```

### 先只读查看路由

```powershell
.\.venv\Scripts\python.exe -m ddr_rag route "LDO 稳定性如何判断？" --format text
.\.venv\Scripts\python.exe -m ddr_rag route "这个布线要求是什么？" --format json
.\.venv\Scripts\python.exe -m ddr_rag route "联合检查 DDR4 与 LDO" --domain memory --domain power_management
```

`route` 输出状态、路由领域、候选领域、主题、接口、型号、文档范围、显式过滤器和理由。它不加载 BGE-M3、不访问 Qdrant/BM25、不调用回答模型。关键词不足或同时指向多个领域时状态为 `clarification_required`；跨领域不会自动扩大，必须重复指定 `--domain`。

### 只在本地搜索证据

```powershell
$env:TRANSFORMERS_OFFLINE = "1"
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m ddr_rag search "DDR4 时钟布线要求是什么？" --memory-type DDR4 --limit 5 --format text
```

默认模式为 Hybrid，也可以显式选择：

```powershell
.\.venv\Scripts\python.exe -m ddr_rag search "CLKP CLKN 1500mil" --mode sparse --memory-type DDR4 --limit 5 --format json
.\.venv\Scripts\python.exe -m ddr_rag search "DDR4 CLK impedance" --mode dense --doc-id ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2 --limit 5
.\.venv\Scripts\python.exe -m ddr_rag search "电源与信号完整性联合审查" --domain power_management --domain signal_integrity --limit 6
```

`--domain`、`--topic`、`--interface` 和 `--part` 都可重复。显式多个领域时，每个领域分别执行 Dense、BM25 和 RRF，再轮转合并并按 Chunk 去重；`--limit` 小于领域数会明确报错。Dense 与 BM25 使用同一个文档/领域/主题/接口/型号范围，BM25 的词频统计也限制在当前领域分片内。

`search` 不调用 DeepSeek。文本模式给出本轮路由、`[C#]`、领域、主题、文档 ID、版本、资料类别、格式、原文位置、来源路径和正文；JSON 模式还提供 `route`、完整 Chunk 元数据与 `retrieval_sources`。默认 `config.yaml` 仍指向 DDR V1.2；检索 V2 时须显式传入 `--config config.hardware-v2.yaml`，不会隐式切换默认库。

当前推荐的 V2 离线检索示例：

```powershell
. .\scripts\use_d312_env.ps1
.\.venv-d312\Scripts\python.exe -m ddr_rag search "LDO 的压降电压是什么？" --config config.hardware-v2.yaml --domain power_management --limit 6 --format text
```

### 使用 DeepSeek 回答一个问题

```powershell
$env:TRANSFORMERS_OFFLINE = "1"
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m ddr_rag ask "DDR4 时钟布线要求是什么？" --memory-type DDR4 --limit 3 --format text
```

执行过程为：本地路由 → 本地 Hybrid 检索 → 发送有限证据给 DeepSeek → 本地验证回答中的 `[C#]` → 在答案末尾输出“答案来源”。歧义路由在第一步要求澄清且不会调用 API。来源栏目只包含模型实际引用且本地验证通过的资料，并显示领域、主题、资料类别、原厂/已审核/未审核身份、文件格式和原文位置。提示词要求区分通用规则、特定器件/标准规则和未审核经验；资料冲突时并列说明适用条件。没有可靠证据时直接拒答，并显示“本次没有可用于作答的引用来源”。

需要程序化处理时使用 `--format json`。JSON 中的 `route`、`answer`、`citations` 和 `retrieved` 使用同一查询范围和相同引用 ID 对应。

当前推荐的 V2 在线问答示例：

```powershell
. .\scripts\use_d312_env.ps1
.\.venv-d312\Scripts\python.exe -m ddr_rag ask "LDO 的压降电压是什么？" --config config.hardware-v2-online.yaml --domain power_management --limit 6 --format text
```

该命令会调用 DeepSeek，并发送问题及最多 6 条本地命中证据。若只想查看证据而不外发，请使用前一节的 `search` 命令和离线配置。

## 登记和入库资料

### 1. 放置原始资料

- 芯片厂商资料：`data/raw/vendor/`
- 标准资料：`data/raw/standards/`
- 公司规范：`data/raw/company/`
- 板厂能力：`data/raw/fab/`
- 已审核经验：`data/raw/experience/`

支持 `.pdf`、`.docx` 和 `.pptx`。原始资料不应修改或覆盖。旧 `.doc/.ppt` 请先另存为现代格式；扫描件 OCR、图片拓扑理解、Word 批注、PPT 备注/批注/隐藏页不属于 V1.2 入库范围。默认 V1.2 目录有 3 份 active PDF；独立 V2 目录有 10 份 active 资料。测试样本文档不会进入正式知识库。

### 2. 登记目录元数据

在 `data/catalog/documents.yaml` 为每份资料增加记录，至少正确填写：

- `doc_id`：稳定唯一 ID。
- `title`、`revision`、`vendor`、`file`。
- `memory_types`、`applicable_parts`。
- `status`、`published_date`、`supersedes`。
- `document_type`：如 `datasheet`、`hardware_design_guide`、`application_note`、`company_spec`、`engineering_experience`。
- `authority`：如 `vendor_datasheet`、`vendor_design_guide`、`approved_experience`、`unverified_note`。
- `authority_score`、`confidentiality`。
- 可选 `source_format`：必须与 `.pdf/.docx/.pptx` 扩展名一致；省略时自动推断。
- 可选 `file_hash`：用于发现原始资料被替换；实际 Chunk 始终保存计算得到的 SHA-256。

验证目录：

```powershell
.\.venv\Scripts\python.exe -m ddr_rag catalog validate
```

### 3. 一键入库

处理一份 active 文档：

```powershell
.\.venv\Scripts\python.exe -m ddr_rag ingest --doc-id <登记的文档_ID> --replace
```

处理全部 active 文档：

```powershell
.\.venv\Scripts\python.exe -m ddr_rag ingest --all --replace
```

`ingest` 顺序执行 parse → chunk → embed → Qdrant → BM25，任一阶段失败就停止。它不是跨五阶段事务：失败前已经成功写入的阶段不会自动回滚，应先查看错误和阶段产物再重试。Dense 向量、Qdrant 和 BM25 是全局派生产物，因此即使只更新一份文档，也会为当前全部 Chunk 重建这些索引。

只要检测到现有派生产物，不带 `--replace` 就会在解析前拒绝执行。这是覆盖保护；确认更新时才使用 `--replace`。它不会修改原始资料。目录中的资料分类或审核身份变化也需要重建 Chunk、向量、Qdrant 和 BM25，避免索引保留旧标签。

### 4. 分阶段执行

需要诊断时可以逐步运行：

```powershell
.\.venv\Scripts\python.exe -m ddr_rag parse --all --replace
.\.venv\Scripts\python.exe -m ddr_rag chunk --all --replace
.\.venv\Scripts\python.exe -m ddr_rag embed --replace
.\.venv\Scripts\python.exe -m ddr_rag index --replace
.\.venv\Scripts\python.exe -m ddr_rag bm25 --replace
```

主要输出：

| 阶段 | 输出 |
|---|---|
| Parse | `data/parsed/Markdown/`、`data/parsed/JSON/`、`logs/ingestion/` |
| Chunk | `data/chunks/v1.2/chunks.jsonl` |
| Embedding | `data/index/v1.2/bge-m3/` |
| Qdrant | `data/index/v1.2/qdrant/` |
| BM25 | `data/index/v1.2/bm25/` |

每个 Chunk 保存文档 ID、标题、版本、领域、主题、可选内存类型、适用接口/型号、资料类别、来源身份、格式、来源路径、章节、格式化原文位置、文档状态和 Token 数；最大实际 Token 数不超过 600。PDF 保留原页码，PPTX 保留原幻灯片号，DOCX 使用标题路径、结构元素和原文短摘，不虚构 Word 页码。

## 评测

### 校验题集和证据锚点

```powershell
.\.venv\Scripts\python.exe -m ddr_rag eval validate
```

该命令只读取 40 题 YAML 和本地 Chunk，不加载模型、不检索、不调用 API。

评测模型已支持通用 schema v2：每题可声明 `domains`、`topics`、`applicable_interfaces` 和可选 `memory_type`，数据集自行配置题量、语言及来源要求；PDF、PPTX、DOCX 分别使用页码、幻灯片号和结构元素锚点。既有 `ddr_rag_v1` 题集在读取时确定性补充 `memory` 领域并保留原 40/30/10 契约。

### 离线检索评测

```powershell
$env:TRANSFORMERS_OFFLINE = "1"
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m ddr_rag eval run --top-k 5
```

这是默认模式，只运行本地路由、BGE-M3 + Qdrant + BM25/RRF。它按题目声明的领域范围以及文档、章节和格式化原文锚点计算 Top-5 命中率，报告中固定记录 `answer_model_called=false`。

### 逐题 DeepSeek 问答评测

```powershell
$env:TRANSFORMERS_OFFLINE = "1"
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m ddr_rag eval run --top-k 5 --with-answer-eval
```

只有这个显式开关才会在离线命中率先达到门槛后调用 DeepSeek。每题实际发送的证据数取 `--top-k` 与 `generation.max_evidence_chunks` 中较小者，当前配置最多 6 条。可回答题要求引用覆盖所有预期来源锚点；不可回答题要求明确拒答。题集的 `expected_key_facts` 不会发送给模型，而是在生成后与答案并列供人工语义复核。

如只想受控复核某一题，可重复指定 `--question-id`。程序仍会先完整校验 40 题题集及全部锚点，之后才筛选指定题；例如：

```powershell
$env:TRANSFORMERS_OFFLINE = "1"
.\.venv\Scripts\python.exe -m ddr_rag eval run --top-k 5 --with-answer-eval --question-id DDR_REFUSE_05 --min-refusal-rate 1.0
```

模型首次输出若没有任何合法 `[C#]`、且不等于固定拒答句，程序最多发起一次严格格式纠正请求；伪造/越界引用仍直接拒绝，不会重试。报告会分别记录 API 题数和实际 API 请求数。

评测会产生多次 API 请求和费用。当前 40 题实际尝试 36 次请求；4 道没有本地候选的题目直接本地拒答，未调用 API。

报告输出到 `evals/reports/`，使用时间戳命名且不覆盖历史结果。JSON/Markdown 报告不保存 Chunk 正文或 Key，但会保存问题、生成答案、预期事实和引用元数据，包括本地 `source_path`；分享报告前应检查这些元数据是否适合公开。

## 当前验收结果

| 项目 | 当前结果 |
|---|---|
| V1.2 默认库 | 3 文档、782 Chunk、`ddr_knowledge_v1_2` 782 点、BM25 14,883 词项 |
| V1.2 Chunk SHA-256 | `555F9B69CB9BFD4FBF79E6889DA2492E463B5397603C78D473CEE0BBD0C9839A` |
| 离线 Top-5（V1.2） | 30/30 全锚点命中，100%；锚点 recall 31/31，100% |
| V2 阶段 2 路由/检索 fixture | Dense、Sparse、Hybrid 均通过显式跨领域隔离、轮转与去重 |
| V2 阶段 3 资料登记 | 8 文档、0 错误、0 警告；PPTX 38/38 页结构和渲染一致，用户验收通过 |
| V2 阶段 4 数据 | 8 文档、1,694 Chunk、1,694 × 1,024 float32 向量 |
| V2 阶段 4 索引 | `hardware_knowledge_v2` 1,694 点；BM25 1,694 Chunk、22,673 词项 |
| V2 90 题本地验收 | 旧 40 题 30/30 与 31/31；新增单资料 28/30；跨领域 6/6；歧义澄清 4/4 |
| V2 阶段 5 本地前置门 | Top-6 为 36/36 all-anchor、42/42 expected-anchor；歧义 4/4 |
| V2 阶段 5 在线回答 | 来源引用 35/36（97.2%）；拒答 14/14（100%）；歧义 4/4 零 API；0 错误 |
| V2 阶段 5 人工语义复核 | 29/36 完整覆盖两条预期要点；7/36 部分覆盖；0 题明确矛盾或无依据硬编 |
| V2 阶段 5 API 用量 | 完整 50 题为 46 次请求；另有 1 次单题预检，阶段合计 47 次；没有格式纠正重试 |
| V2 2026-10-06 增量接入 | 10 文档、1,825 Chunk/向量/Qdrant/BM25；TN662 76 Chunk、UG206 55 Chunk；旧 8 文档 Chunk 哈希不变 |
| 增量接入后离线回归 | DDR 40 题 30/30 与 31/31；V2 Top-6 35/36（97.2%）、单资料 30/30、跨领域 6/6、歧义 4/4；零 API |
| 全量在线回答（V1.1） | 30/30 引用覆盖通过，100%；10/10 严格拒答通过，100% |
| 全量在线 API 用量 | 36 个有候选题、36 次请求、0 错误；4 个无候选题在本地拒答 |
| 自动测试 | 86 passed（含 V2 查询扩展、评测路由、分组验收及原有回归） |

V2 阶段 2 对 V1.2 的最新零 API 离线回归：

- `evals/reports/ddr_rag_v1_offline_20260929T102500+0800.md`
- `evals/reports/ddr_rag_v1_offline_20260929T102500+0800.json`

V2 阶段 4 本地验收：

- `evals/hardware-v2/stage4_acceptance.md`
- `evals/hardware-v2/hardware_v2_90_questions_review.md`
- `evals/hardware-v2/reports/ddr-v1-regression/ddr_rag_v1_offline_20260929T161443+0800.md`
- `evals/hardware-v2/reports/v2-new/hardware_rag_v2_stage4_offline_20260929T162008+0800.md`

V2 阶段 5 在线回答验收：

- `evals/hardware-v2/stage5_acceptance.md`
- `evals/hardware-v2/reports/stage5-online/hardware_rag_v2_stage4_offline_20261005T162922+0800.md`
- `evals/hardware-v2/reports/stage5-online/hardware_rag_v2_stage4_answers_20261005T163221+0800.md`

V1.2 构建完成时的离线报告：

- `evals/reports/ddr_rag_v1_offline_20260926T235411+0800.md`
- `evals/reports/ddr_rag_v1_offline_20260926T235411+0800.json`

V1.1 全量逐题回答报告：

- `evals/reports/ddr_rag_v1_answers_20260926T225410+0800.md`
- `evals/reports/ddr_rag_v1_answers_20260926T225410+0800.json`

V1.1 全量离线报告：

- `evals/reports/ddr_rag_v1_offline_20260926T225209+0800.md`
- `evals/reports/ddr_rag_v1_offline_20260926T225209+0800.json`

2026-09-24 的 28/30、9/10 历史全量报告和 `DDR_REFUSE_05` 单题补测报告均保留用于比较，不覆盖也不与本次结果混写。

## 已知限制

- V1.1 的完整在线评测已确认 `DDR_ANS_RK3568_04`、`DDR_ANS_RK3568_10` 可回答，且全量结果为 30/30 引用覆盖与 10/10 拒答通过；这衡量的是引用/拒答硬约束。报告中的 `expected_key_facts` 仍须在需要工程签核时人工语义复核。
- NXP 解析状态为 `partial_success`。第 8、16、24、32、40 页的 Docling preprocess 记录异常；涉及这些页的精确表格、图片或数值时必须回看原 PDF。
- Rockchip 原 PDF 第 26 页 `RK3568 DDR PHY I/O Map` 是复杂中文大表，Markdown 存在列合并或错位风险，具体引脚映射必须回看原 PDF/JSON 页面来源。
- 当前主链路依赖文本、简单表格文本和图注。BGE-M3 文本向量不能理解图片中的几何连接、箭头或纯拓扑关系；只有图片而没有可检索正文的资料不会生成可回答 Chunk。
- DOCX 引用使用章节、Docling 结构元素和原文短摘，不声称具有稳定的 Word 物理页码；PPTX 引用使用原始幻灯片号，空白页不生成 Chunk，隐藏页不参与检索。
- 未审核工程经验可以参与回答，但必须显示“未审核”，不能表述成原厂要求；来源标签不代替最终工程审核。
- `config.yaml` 仍只使用已验收的 V1.2 独立产物；V2 必须显式选择配置。`config.hardware-v2.yaml` 保持离线，`config.hardware-v2-online.yaml` 才启用 DeepSeek。V1.1 配置保存在 `config.v1.1.yaml`，旧 Chunk、向量和 Qdrant 目录均保留，不要未经确认删除。
- 阶段 5 的自动来源引用/拒答门已通过，但人工逐条复核发现 7/36 道可回答题至少缺少一个预期细节，主要涉及模型漏述及 PPT 标题性/截断正文。具体题号与缺口见 `evals/hardware-v2/stage5_acceptance.md`；答案不能脱离原文复核用于工程签核。
- 文档适用范围不同。Rockchip、TI、NXP 或不同 DDR 类型的规则不能因数值相似而直接互换。

## 常见问题

### `torch.cuda.is_available()` 为 `False`

确认命令使用项目 `.venv`，并检查 `torch.__version__` 是否带 `+cu128`。如果新环境使用了 `--system-site-packages`，可能错误复用 C 盘基础 Python 的 CPU PyTorch；建议重建干净项目环境或在项目环境安装 CUDA wheel。

### 提示找不到 BGE-M3 本地模型

运行“首次下载 BGE-M3”的命令，并确认 `config.yaml` 的 `embedding.model_cache` 为 `data/models/bge-m3`。业务运行设置 `TRANSFORMERS_OFFLINE=1` 后不会联网补下载。

### HybridChunker 首次启动看似卡住

首次导入会加载 Transformers 并扫描 Python 分发包，在已验证机器上可能约 90 秒。只要进程仍在运行，可先等待；它不等同于死锁。

### Windows 控制台出现乱码或 `UnicodeEncodeError`

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

程序化读取优先使用 `--format json`。JSON 模式会进行安全转义。

### `ingest` 提示已有派生产物

这是覆盖保护。确认目录登记和原始资料正确后，显式加 `--replace`。不要通过删除整个 `data/index` 或原始资料来绕过检查。

### 缺少 `DEEPSEEK_API_KEY`

检查项目根目录 `.env` 是否存在、变量名是否为 `DEEPSEEK_API_KEY`，以及当前命令是否从包含 `config.yaml` 的项目目录执行。不要把 Key 写入 `config.yaml`。

### 回答因无引用、伪造引用或空正文而失败

这是安全机制。先用同一问题执行 `search` 检查本地证据；不要关闭引用校验。若证据不足，应补充可靠资料或接受拒答。

### Qdrant 点数与 Chunk 数不一致

不要直接删除正在使用的集合。创建新的集合名并更新 `config.yaml`，重新执行 `index --replace` 后核对点数、维度和距离；当前活动集合 `ddr_knowledge_v1_2` 已验证为 782 点。

## 测试

```powershell
Set-Location D:\pcb\AI_PCB
. .\scripts\use_d312_env.ps1
.\.venv-d312\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

独立环境最新结果为 `86 passed, 2 warnings in 25.00s`；历史 V2 阶段 4 验收为 `82 passed in 44.66s`。测试不会使用真实 API Key；回答器测试使用本地假客户端。多格式和跨领域测试只在 D 盘临时目录生成 DOCX/PPTX、Chunk、向量、Qdrant 和 BM25 小样本，不会加入正式资料目录或覆盖正式索引。

## 重要文件

- `config.yaml` / `config.v1.2.yaml`：当前解析、切分、Embedding、索引、检索和生成配置；`config.v1.1.yaml` 用于回退核验。
- `config.hardware-v2.yaml`：独立 V2 路径与分类配置；本地产物已构建，在线生成保持关闭。
- `config.hardware-v2-online.yaml`：显式 V2 在线问答入口；会把问题及最多 6 条检索证据正文/来源元数据发送至 DeepSeek。
- `scripts/use_d312_env.ps1`：独立环境的当前会话入口；统一将运行时与缓存固定到项目 D 盘目录。
- `.runtime/managed-python/` 与 `.venv-d312/`：项目当前推荐的托管 CPython 和无系统站点包虚拟环境；旧 `.venv/` 仅作为回退保留。
- `.env.example`：DeepSeek Key 和项目根目录模板；真实值放在被忽略的 `.env`。
- `data/catalog/documents.yaml`：权威资料目录。
- `data/catalog/hardware_v2_documents.yaml`：独立 V2 目录，当前共 10 份资料。
- `data/hardware-v2/review/cosh_signal_integrity/conversion_review.md`：旧 PPT 转换的结构、渲染和人工检查材料。
- `data/taxonomy/hardware_v2_taxonomy.v1.yaml`：V2 受控领域、主题、内存类型和接口词表。
- `data/classification/hardware_v2_classification.v1.yaml`：版本化文档/章节分类映射。
- `evals/ddr_rag_v1_questions.yaml`：版本化 40 题评测集。
- `evals/hardware-v2/hardware_v2_questions.yaml`：V2 新增 50 题评测集；与冻结 40 题合计 90 题。
- `evals/hardware-v2/hardware_v2_90_questions_review.md`：便于人工逐题检查的 90 题清单。
- `evals/hardware-v2/stage4_acceptance.md`：V2 阶段 4 本地验收结论、指标和报告索引。
- `evals/hardware-v2/stage5_acceptance.md`：V2 阶段 5 在线指标、人工语义复核和已知限制。
- `项目说明文档/改进方向.md`：阶段 5 后识别的六项待规划质量增强；不代表已批准实施。
- `项目说明文档/出现问题.md`：问题、原因、解决方案和验证结果。
- `项目说明文档/执行过程.md`：按时间记录的完整实施历史。
- `项目说明文档/交接.md`：当前状态和下一步快照。
- `plan.md`：总体架构、阶段计划和验收标准。

## 安全原则

- 不修改或覆盖原始资料。
- 不把 API Key、密码或令牌写入源码、报告或版本库。
- 不把检索结果当作最终工程签核；关键表格、图形、异常页和数值回查对应原始文件。
- 不在未审核领域、主题、适用器件、文档版本和内存类型时跨资料套用规则。
- 更新数据时依赖显式 `--replace` 和完整性校验，不通过批量删除规避保护。

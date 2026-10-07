# 通用硬件 RAG V2 实施计划（已批准，阶段 1–5 已完成）

更新时间：2026-10-05 16:56:14（Asia/Shanghai）  
状态：阶段 1–5 已完成。阶段 4 采用“原 DDR 固定回归 40 题 + V2 新增 50 题 = 共 90 题”；阶段 5 在用户明确批准具体数据外发边界后完成 DeepSeek 在线回答验收。默认配置仍为 V1.2，离线 V2 配置仍关闭生成。

## 1. 目标与边界

把现有 DDR RAG V1.2 升级为“**共用一套 RAG 平台、知识领域明确隔离、需要时才显式跨领域联合检索**”的通用硬件 RAG V2。

- DDR 仍是正式领域之一，原有 DDR 查询、证据、来源格式和 V1.2 回归必须保留。
- 首批新增领域：`high_speed_interface`、`power_management`、`electrical_safety`、`signal_integrity`；兜底领域为 `hardware_general`。
- 一个文档或 Chunk 可以属于多个领域；普通问题默认只检索一个明确领域。跨领域必须由用户重复指定 `--domain`；系统不因为词面关联自动扩大到全库。
- 无法可靠判断领域的问题返回“需要澄清领域”，并列出可选领域；该分支不调用 DeepSeek 或其他回答 API。
- 本期不做 OCR、图片/复杂图表理解、自动监视目录、Web/EDA/Agent 接入，也不把 `.doc`/`.ppt` 原件直接入库。

## 2. V2 统一数据模型

在 `DocumentRecord`、`ChunkRecord`、Qdrant payload、BM25 记录、检索 JSON、Citation、回答证据与评测报告中贯通下列字段。

| 字段 | 规则 | 作用 |
| --- | --- | --- |
| `domains` | 非空列表 | 检索隔离与路由，例如 `memory`、`power_management`。 |
| `topics` | 非空列表 | 领域内细分，例如 `DDR2`、`ldo`、`creepage_clearance`。 |
| `memory_types` | 改为可空列表 | 仅内存资料或 Chunk 填 `DDR2`、`DDR4`、`LPDDR4` 等；非内存资料为空。 |
| `applicable_interfaces` | 默认空列表 | USB、PCIe、SATA、HDMI、CSI 等接口适用范围。 |
| `document_type` | 扩充枚举 | 保持既有类别，补充 `technical_whitepaper`、`training_material`。 |

现有 `authority`、`source_format`、`source_path`、`source_sha256`、版本、状态、`applicable_parts`、章节、页码/幻灯片/Word 结构定位及可核验引用机制全部保留。资料类别与来源身份仍是两条独立信息，不能互相替代。

`domains` 与 `topics` 使用受控词表校验；不得为了通过校验把非 DDR 文件标为 DDR。目录级默认分类可被章节/Chunk 分类覆盖：例如一份 SoC 资料整体属于 `memory`，其中 USB 章节应标为 `high_speed_interface`，电源章节应标为 `power_management`。

## 3. 资料分类与首批候选

分类依据、原始 SHA-256、建议登记字段和限制见 [未入库资料/资料审查.md](../未入库资料/资料审查.md)。本期拟采用：

| 候选资料 | `domains` | `topics` | 身份/状态 |
| --- | --- | --- | --- |
| JEDEC JESD79-2C DDR2 | `memory` | `ddr2`, `sdram_standard` | 标准资料 / active |
| TI SPRAAR7J 高速接口布局 | `high_speed_interface` | `usb`, `sata`, `pcie`, `hdmi`, `sgmii`, `csi` | 原厂资料 / active |
| TI ZHCY093 LDO 基础 | `power_management` | `ldo`, `power_supply` | 原厂资料 / active |
| TI ZHCP238 电气间隙和爬电距离 | `electrical_safety` | `creepage_clearance`, `high_voltage_pcb` | 原厂资料 / active |
| 同洲《信号完整性基础》 | `signal_integrity` | `eye_diagram`, `jitter`, `pcie` | 未审核工程培训 / active |

旧 `.ppt` 仅在第三阶段转换为同目录内新建、不可覆盖原件的 `.pptx` 副本；转换后逐张核验编号、正文、空白/隐藏页和可读性。若转换失败，该资料保留为“未入库”，不影响其余资料。

## 4. 检索、CLI 与回答行为

1. 新建统一查询范围解析器，按顺序处理显式 `--doc-id`、重复 `--domain`、`--topic`、`--interface`、`--part`、兼容的 `--memory-type`，再处理本地领域路由。
2. `search` 和 `ask` 均支持可重复的 `--domain`。单领域查询只使用该领域；多个领域分别完成 Dense、BM25、RRF，然后按领域轮转合并并去重，避免一个领域挤占全部证据。`max_evidence` 小于请求领域数时应明确报错。
3. 新增只读 `route` CLI，输出路由领域、适用型号/接口、使用的显式过滤器及理由。它不检索、不调用模型，可用于调试和评测。
4. Dense 与 BM25 必须使用完全相同的范围。Qdrant 使用 `domains` 等 payload 过滤；BM25 保留同一向量库中的 Chunk，但以领域分片统计与过滤，防止跨领域词频稀释。
5. 回答提示词从“DDR 助手”改为“基于硬件资料的证据助手”。回答必须区分通用规则、特定器件/标准规则及未审核经验；混合来源或冲突须并列其适用条件。答案末尾的“答案来源”继续只列本轮真实、通过校验的 `[C#]`，增加领域/主题展示。

## 5. 配置、迁移和隔离

- 新增 `config.hardware-v2.yaml`，默认不改动当前 `config.yaml`；V1.2 仍可直接回退与使用。
- V2 新产物位于 `data/hardware-v2/`：解析副本、Chunk、BGE-M3 向量、Qdrant Local 和按领域 BM25 索引均与 V1.2 隔离；新集合名为 `hardware_knowledge_v2`。
- V2 目录使用独立的 `data/catalog/hardware_v2_documents.yaml`；原 `data/catalog/documents.yaml` 与三份 DDR 正式资料不就地修改。
- 既有三份 PDF 可复用已验证的 V1.2 解析结果作为 V2 输入，但 V2 Chunk 新增字段后必须重新生成 V2 Chunk、向量、Qdrant 和 BM25。不得只改 Qdrant 标签。
- V1.2 的原始 PDF、Chunk、向量、索引、报告和配置永久保留；本期不删除任何资料或派生产物。

## 6. 实施阶段与阶段门

### 阶段 1：模型、词表和分类映射（已完成）

实现受控领域/主题词表、可选 `memory_types`、新字段贯通和版本化的“文档/章节 → 分类”映射；同步把评测数据结构从 DDR 专用 ID/固定 30+10 配额改为可配置资料集。新增单元测试，但不复制候选资料、不转换 PPT、不构建索引。

阶段门：现有 58 项测试继续通过；三份 DDR 资料在 V1.2 配置下保持原状；非内存元数据可被诚实校验；无领域或非法领域被拒绝。

完成结果（2026-09-28）：统一字段已贯通数据模型、Chunk、未来索引 payload、检索/引用/回答证据与通用评测报告；新增版本化受控词表和文档/章节分类映射。完整本地回归为 66 项通过，V1.2 目录、题集、782 点 Qdrant 与关键文件哈希均保持原基线；未进行任何正式资料或索引迁移。

### 阶段 2：检索路由、CLI、引用与离线测试框架（已完成）

实现 `route`、显式/自动单领域路由、重复 `--domain` 跨领域检索、Dense/BM25 同范围和领域均衡合并；更新提示词、JSON/文本来源格式与通用评测器。用临时 fixtures 完成单元/集成回归，仍不碰正式资料与 V1.2 索引。

阶段门：显式跨领域只返回指定领域；歧义问题要求澄清且零 API；同一型号多个文档仍可共同命中；DDR 离线 40 题的 V1.2 原配置指标保持 30/30 all-anchor hit@5、31/31 anchor recall@5。

完成结果（2026-09-29）：新增统一 `QueryScope` 与只读 `route`，`search`/`ask` 支持可重复的领域、主题、接口和型号过滤；显式多领域分别执行 Dense/BM25/RRF 后轮转合并去重，BM25 只在当前领域范围计算统计量。歧义 `ask` 在回答器前退出，临时 V2 Qdrant/BM25 fixture 验证 Dense、Sparse、Hybrid 均只返回指定领域且同一型号多文档不丢失。提示词、CLI、引用与评测入口已通用化；完整测试 `77 passed in 53.43s`。现有 V1.2 目录仍为 3 文档、0 错误、0 警告，Qdrant 仍为 782 点；零 API 离线报告 `ddr_rag_v1_offline_20260929T102500+0800` 保持 30/30 和 31/31，`answer_model_called=false`。关键 V1.2 配置、目录和 Chunk 哈希均未变化。

### 阶段 3：首批资料受控登记（已完成）

在独立 V2 目录创建目录记录；复制四份 PDF 到相应 raw 子目录；生成并核验旧 PPT 的 `.pptx` 副本后登记。每步进行哈希、格式、目录和可解析性检查；失败资料单独记录且不入库。

阶段门：原件未修改；目录字段、领域/主题、来源身份与资料审查结论一致；非 PDF 引用定位不虚构页码。

执行结果（2026-09-29）：四份 PDF 已按来源身份复制到 `data/raw/standards/` 与 `data/raw/vendor/`，源/目标哈希逐份一致；旧 `.ppt` 已保留不动，并生成 `data/raw/experience/cosh_ip_signal_integrity_training_2009.pptx`。源/目标均为 38 页、4:3，逐页形状、文本、备注、布局和几何指纹全部一致，38/38 张 PowerPoint 原生 1600×1200 渲染 PNG 的 SHA-256 全部一致；PPTX 包完整性与精确页面几何检查均为 0 问题，人工联系表总览未见转换异常。独立 `config.hardware-v2.yaml` 与 `data/catalog/hardware_v2_documents.yaml` 已创建，8 文档目录校验为 0 错误、0 警告；完整本地回归为 `77 passed in 54.52s`。V1.2 配置、目录、Chunk 哈希保持原基线，`data/hardware-v2/parsed`、`chunks`、`index`、`logs` 均不存在；未解析、切块、向量化、建索引或调用 API。详细视觉材料见 `data/hardware-v2/review/cosh_signal_integrity/conversion_review.md`。用户于 2026-09-29 明确确认“PPT 转换无误”，阶段 3 验收门已通过。

### 阶段 4：V2 构建与离线验收

构建独立的 V2 解析、HybridChunker、BGE-M3、Qdrant 与 BM25 产物；运行全量本地测试、现有 DDR 固定 40 题回归和新的通用硬件离线题集。V2 新增题集固定为 50 题：五份新增资料各 6 道可回答题和 2 道证据不足题（共 40 题，其中可回答 30、证据不足 10），再加 6 道显式跨领域题和 4 道歧义路由题。两个题集合计 90 题；旧 40 题保持原文件和契约，不复制改写来虚增题量。

阶段门：原 40 题回归保持 V1.2 的 30/30 all-anchor hit@5 与 31/31 expected-anchor recall@5；每份新增资料至少 5/6 可回答题命中预期来源；30 道单资料可回答题整体 anchor hit@5 不低于 90%；6/6 跨领域题的 Top-6 覆盖期望领域；4/4 歧义题均在本地澄清、零 API；10 道证据不足题只做离线候选/边界诊断，不把离线检索结果冒充回答层拒答率；所有引用可回查到原文件位置。题目必须覆盖不同知识点和来源位置，同一事实的简单改写不重复计数。

完成结果（2026-09-29）：8 份资料均生成 Markdown 与 Docling JSON；得到 1,694 个不超过 600 token 的 Chunk，SHA-256 为 `315d3ad995c77d9553a8d967481e2a446820746885309315159d169eb8c10c93`。BGE-M3 产物为 1,694×1,024 float32 且已归一化；Qdrant 集合 `hardware_knowledge_v2` 有 1,694 点，BM25 有 1,694 条记录、22,673 词项。冻结 40 题回归达到 30/30 all-anchor hit@5 和 31/31 expected-anchor recall@5；新增 50 题中单资料题 28/30（93.3%，五份资料均至少 5/6）、跨领域 6/6、歧义澄清 4/4。完整本地回归 `82 passed in 44.66s`。默认 `config.yaml`、V1.2 目录和产物未切换，阶段内没有运行 `ask`、`--with-answer-eval` 或其他回答 API。验收见 `evals/hardware-v2/stage4_acceptance.md`，90 题人工审查清单见 `evals/hardware-v2/hardware_v2_90_questions_review.md`。

### 阶段 5：可选在线回答评测（已完成）

仅在阶段 4 通过且用户再次单独授权后，才用 DeepSeek 对指定题集执行 `--with-answer-eval`。默认不执行；报告必须标明资料集、模型、实际请求数、来源覆盖、拒答/澄清表现和失败项，且不得把本地检索验收称为在线回答验收。

完成结果（2026-10-05）：用户明确批准外发 V2 题目及每题最多 6 条检索证据正文/来源元数据后，先完成 1 题预检，再完成新增 50 题全量在线评测。36 道可回答题的全部预期来源引用为 35/36（97.2%），14 道应拒答题为 14/14（100%），4 道歧义题本地停止且 API 请求为 0；完整运行有 46 个 API 题、46 次实际请求、0 个逐题错误，加上预检后阶段合计 47 次请求。人工语义复核为 29/36 题完整覆盖本题两条预期要点、7/36 题部分覆盖、0 题与证据明确矛盾或无依据硬编；自动引用门与人工语义完整度已分开报告。验收见 `../evals/hardware-v2/stage5_acceptance.md`。

## 7. 当前唯一任务

V2 阶段 1–5 已完成。下一步由用户使用离线检索或显式在线问答进行实际测试；阶段 5 发现的 7 道部分覆盖题作为已知限制保留，不未经用户指令自动扩展资料、重建索引或再次调用 API。

## 8. 阶段完成后的增量资料接入

2026-10-06 经用户明确授权，仅将高云 TN662 1.3.2 与 UG206 1.9.3 按既有受控流程接入 V2。两份官方中文 PDF 完成审查、哈希一致 raw 复制、目录/章节分类、Docling 解析、HybridChunker、BGE-M3、Qdrant/BM25 重建及本地回归。当前 V2 为 10 文档、1,825 个 Chunk、1,825×1,024 向量、1,825 个 Qdrant 点和 1,825 条 BM25 记录（24,530 词项）；原 8 文档 Chunk 逐份哈希不变，V1.2 六项冻结哈希不变。

冻结 90 题没有增删或改写。DDR 40 题保持 30/30 与 31/31；V2 50 题 Top-6 为 35/36（97.2%）、单资料 30/30、跨领域 6/6、歧义 4/4。唯一精确锚点变化为新增且相关的 TN662 PDN 证据进入跨领域题前列，使原 TI PSRR 精确标题 Chunk 位于第 7；既定 90% 门通过。完整增量验收见 `../evals/hardware-v2/post_gowin_ingest_acceptance.md`。本次没有调用在线回答 API，也没有处理其他候选资料。

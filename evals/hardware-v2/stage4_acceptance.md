# 通用硬件 RAG V2 阶段 4 本地验收报告

日期：2026-09-29（Asia/Shanghai）

## 结论

阶段 4 通过。V2 独立解析、Chunk、Embedding、Qdrant、BM25 与 90 题本地验收均已完成；没有运行 `ask`、`--with-answer-eval` 或任何回答 API。默认 `config.yaml` 仍指向 V1.2，V2 通过 `config.hardware-v2.yaml` 显式使用。

## 数据与索引

- 目录：8 份资料，0 错误、0 警告。
- 解析：8 份 Markdown + 8 份 Docling JSON。
- Chunk：1,694 条，重复 ID 0，最大 600 token，SHA-256 `315d3ad995c77d9553a8d967481e2a446820746885309315159d169eb8c10c93`。
- Embedding：1,694 × 1,024 float32；范数 `0.99999988–1.00000012`。
- Qdrant：`hardware_knowledge_v2`，1,694 点，1,024 维，Cosine。
- BM25：1,694 条，22,673 词项，平均长度 170.48。

## 90 题验收

### 原 DDR 冻结 40 题

- 原题文件未修改。
- Top-5：30/30 可回答题全部预期来源命中。
- Expected-anchor recall@5：31/31。
- 报告：`reports/ddr-v1-regression/ddr_rag_v1_offline_20260929T161443+0800.{json,md}`。

### V2 新增 50 题

- 组成：30 道单资料可回答题、10 道资料不足题、6 道显式跨领域题、4 道歧义澄清题。
- 单资料 anchor hit@5：28/30（93.3%），超过 90% 阶段门。
- 分资料：JEDEC DDR2 5/6、TI 高速接口 6/6、TI LDO 6/6、TI 安规 6/6、同洲 SI 5/6；全部不低于 5/6。
- 跨领域 Top-6 领域覆盖：6/6。
- 歧义本地澄清：4/4；四题检索结果均为 0，未进入 Embedding、检索或回答 API。
- 资料不足题：10/10 只记录离线候选诊断；本轮 10 题均有词面候选，未据此推断回答层是否应拒答。
- 精确锚点诊断：36 道可回答题在 Top-6 中为 30/36 全锚点、34/42 单锚点；该总数包含阶段门只要求领域覆盖的跨领域题，不替代上述分组门。
- 未命中 Top-5 的两道单资料题：`V2_DDR2_ANS_01`、`V2_SI_ANS_01`；每份资料仍满足 5/6，整体仍为 93.3%。
- 报告：`reports/v2-new/hardware_rag_v2_stage4_offline_20260929T162008+0800.{json,md}`。

## 题目审查材料

- 90 题可读清单：`hardware_v2_90_questions_review.md`。
- V2 新增 50 题 YAML：`hardware_v2_questions.yaml`。
- 原 DDR 40 题 YAML：`../ddr_rag_v1_questions.yaml`（保持不变）。

## 回归与边界

- 完整本地回归：`82 passed in 44.66s`。
- 默认目录：3 文档，0 错误、0 警告；V2 目录：8 文档，0 错误、0 警告。
- 40 题和 50 题的结构、语言配额与全部原文锚点均校验通过。
- V1.2 的 `config.yaml`、`config.v1.2.yaml`、正式目录、Chunk、Embedding manifest 和 BM25 manifest 哈希全部保持阶段前基线。
- 阶段 5 尚未授权；不得把本报告称为在线回答质量验收。

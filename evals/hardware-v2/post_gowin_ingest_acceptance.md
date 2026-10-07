# 高云 TN662 / UG206 增量接入验收

日期：2026-10-06（Asia/Shanghai）

## 范围

本次只把 TN662 1.3.2 与 UG206 1.9.3 加入通用硬件 RAG V2。原 90 题继续作为冻结回归集，没有新增、删除或改写题目；没有调用 DeepSeek 或其他回答 API。

## 数据与索引

- V2 目录：10 文档，0 错误，0 警告。
- 新增解析：TN662 37/37 页、18 表、28 图片；UG206 20/20 PDF 页、16 表、27 图片；两份均为 `success`、0 解析错误。
- Chunk：1,825 条，ID 重复 0，必填追溯字段缺失 0，最大 600 Token；SHA-256 `8BEB6B7A43D55AD28AC2005EB65EED124A0C30041D77B0BC5C5084A37A080CC3`。
- 新增 Chunk：TN662 76 条，UG206 55 条。原 8 份资料的逐文档 Chunk 数量和逐行 SHA-256 全部与接入前一致。
- Embedding：1,825 × 1,024 float32，向量范数 `0.99999988–1.00000012`。
- Qdrant：`hardware_knowledge_v2` 1,825 点，状态 green，必填 payload 缺失 0。
- BM25：1,825 条，24,530 词项，平均长度 172.35；Chunk 哈希与 Embedding manifest 一致。

## 新资料真实检索

- TN662 查询“GW3A-20 的 DDR3 Bank 分布和 I/O 分配规则是什么？”：前两名分别命中 `2.1.5 GW3A-20`（PDF 第 12 页）和 `2.5.5 GW3A-20`（PDF 第 19 页），Dense 与 Sparse 均参与融合。
- UG206 查询“GW2A/GW2AR 的 VCCX 与 VCCIO 上电顺序、上电时间和电源滤波要求是什么？”：前五名依次覆盖上电时序、电源指标、电源滤波、上电时间和电源上升斜率，均回查 PDF 第 2–3 页。

## 回归

- 完整自动测试：`86 passed, 2 warnings in 25.00s`；警告仍为 Typer/Click 弃用提示。
- 冻结 DDR 40 题：30/30 all-anchor hit@5，31/31 expected-anchor recall@5。
- 冻结 V2 50 题 Top-6：35/36 all-anchor（97.2%），expected-anchor recall 97.6%，单资料题 30/30，跨领域范围覆盖 6/6，歧义澄清 4/4。
- 唯一 Top-6 精确锚点变化为 `V2_CROSS_03`：新加入且内容相关的 TN662 `4.3.1 PDN`（电源噪声）进入第 3 名，使原 TI `什么是 PSRR？` 精确章节从 Top-6 移至第 7 名；TI 同页 PSRR 相关 Chunk 仍为第 1 名。该变化不属于错误领域或无关噪声，不修改题集、不降低门槛、不对新资料作错误分类；既定 90% 门仍通过。
- V1.2 六项冻结文件哈希全部保持不变。

## 结论

两份高云官方资料已经完成本地登记、解析、分类、切块、Embedding、Qdrant/BM25 更新和回归，适合在 `config.hardware-v2.yaml` 下使用。默认 V1.2 未切换或改写；本次没有在线回答评测。

# 通用硬件 RAG V2 阶段 4：90 题审查清单

- 总题数：90
- 原 DDR 冻结题：40（原文件不修改）
- V2 新增题：50（36 道可回答，10 道资料不足，4 道歧义澄清）
- 本清单只展示题面与来源锚点；关键事实和拒答理由以对应 YAML 为准。

## 原 DDR 冻结 40 题

| # | 题号 | 类型 | 题目 | 领域 | 预期来源锚点 |
|---:|---|---|---|---|---|
| 1 | `DDR_ANS_RK3568_01` | 可回答 | RK3568 DDR4 CLK 差分对的目标阻抗是多少？ | memory | `ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2` / p.165,166 |
| 2 | `DDR_ANS_RK3568_02` | 可回答 | What length-match limit applies between CLKP and CLKN for RK3568 DDR4? | memory | `ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2` / p.165,166 |
| 3 | `DDR_ANS_RK3568_03` | 可回答 | RK3568 DDR4 中 CLK 与 DQS 的等长限制是多少？ | memory | `ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2` / p.165,166 |
| 4 | `DDR_ANS_RK3568_04` | 可回答 | For RK3568 DDR4 clock routing, what is the maximum L2a-to-L2b mismatch? | memory | `ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2` / p.165,166 |
| 5 | `DDR_ANS_RK3568_05` | 可回答 | RK3568 DDR4 的 CLK 与 CSn/CKE/ODT 信号之间长度应如何控制？ | memory | `ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2` / p.165,166 |
| 6 | `DDR_ANS_RK3568_06` | 可回答 | What clearance is required between RK3568 DDR4 CLK and other signals? | memory | `ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2` / p.165,166 |
| 7 | `DDR_ANS_RK3568_07` | 可回答 | RK3568 的 DDR4+ECC CSn/CKE/ODT 信号中，M 段与非 M 段阻抗分别是多少？ | memory | `ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2` / p.169 |
| 8 | `DDR_ANS_RK3568_08` | 可回答 | What is the maximum CLK-to-CSn/CKE/ODT length difference for RK3568 DDR4+ECC? | memory | `ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2` / p.169 |
| 9 | `DDR_ANS_RK3568_09` | 可回答 | RK3568 DDR4+ECC 中，除 CSn/CKE/ODT 外的 CA/CMD 与 CLK 等长限制是什么？ | memory | `ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2` / p.170 |
| 10 | `DDR_ANS_RK3568_10` | 可回答 | Can the RK3568 DDR4 CLK-to-DQS 1500 mil limit be applied directly to LPDDR4? | memory | `ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2` / p.165,166<br>`ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2` / p.170 |
| 11 | `DDR_ANS_TI_01` | 可回答 | Which JEDEC DDR4 device widths are generally compatible with the AM62x/AM62Lx DDR4 interface? | memory | `TI_AM62X_AM62LX_DDR_LAYOUT_GUIDE_SPRAD06C` / p.12 |
| 12 | `DDR_ANS_TI_02` | 可回答 | TI AM62x DDR4 的 Keepout Region 对非 DDR4 信号有什么要求？ | memory | `TI_AM62X_AM62LX_DDR_LAYOUT_GUIDE_SPRAD06C` / p.13 |
| 13 | `DDR_ANS_TI_03` | 可回答 | Why does the TI AM62x guide recommend DBI for DDR4? | memory | `TI_AM62X_AM62LX_DDR_LAYOUT_GUIDE_SPRAD06C` / p.13 |
| 14 | `DDR_ANS_TI_04` | 可回答 | TI AM62x DDR4 的 VPP 在刷新期间需要具备怎样的供电电流能力？ | memory | `TI_AM62X_AM62LX_DDR_LAYOUT_GUIDE_SPRAD06C` / p.13 |
| 15 | `DDR_ANS_TI_05` | 可回答 | What is the purpose of DDR4 net classes in the TI AM62x layout guide? | memory | `TI_AM62X_AM62LX_DDR_LAYOUT_GUIDE_SPRAD06C` / p.13 |
| 16 | `DDR_ANS_TI_06` | 可回答 | TI AM62x 的多颗 DDR4 存储器设计中，哪些网络类别需要终端？ | memory | `TI_AM62X_AM62LX_DDR_LAYOUT_GUIDE_SPRAD06C` / p.14 |
| 17 | `DDR_ANS_TI_07` | 可回答 | What are VREFDQ and VREFCA used for in the TI DDR4 guidance? | memory | `TI_AM62X_AM62LX_DDR_LAYOUT_GUIDE_SPRAD06C` / p.14 |
| 18 | `DDR_ANS_TI_08` | 可回答 | TI AM62x DDR4 中 VTT 的标称电压与用途是什么？ | memory | `TI_AM62X_AM62LX_DDR_LAYOUT_GUIDE_SPRAD06C` / p.14 |
| 19 | `DDR_ANS_TI_09` | 可回答 | What topology does TI require for DDR4 data lines on AM62x regardless of device count? | memory | `TI_AM62X_AM62LX_DDR_LAYOUT_GUIDE_SPRAD06C` / p.17,18 |
| 20 | `DDR_ANS_TI_10` | 可回答 | TI AM62x DDR4 的 DQ/DQS/DM 等长是否要求跨 Byte Lane 匹配？ | memory | `TI_AM62X_AM62LX_DDR_LAYOUT_GUIDE_SPRAD06C` / p.20,21 |
| 21 | `DDR_ANS_NXP_01` | 可回答 | i.MX 8M Plus 可以与哪些 DDR 类型配合使用？ | memory | `NXP_IMX8MP_HARDWARE_DEVELOPERS_GUIDE_REV1` / p.13 |
| 22 | `DDR_ANS_NXP_02` | 可回答 | Why does NXP recommend time-delay rather than length matching for i.MX 8M Plus LPDDR4-4000? | memory | `NXP_IMX8MP_HARDWARE_DEVELOPERS_GUIDE_REV1` / p.15 |
| 23 | `DDR_ANS_NXP_03` | 可回答 | i.MX 8M Plus LPDDR4-4000 进行延迟匹配时，过孔延迟是否需要计入？ | memory | `NXP_IMX8MP_HARDWARE_DEVELOPERS_GUIDE_REV1` / p.15 |
| 24 | `DDR_ANS_NXP_04` | 可回答 | What maximum PCB-plus-package propagation delay is listed for CK_t/CK_c in NXP LPDDR4-4000 routing guidance? | memory | `NXP_IMX8MP_HARDWARE_DEVELOPERS_GUIDE_REV1` / p.15 |
| 25 | `DDR_ANS_NXP_05` | 可回答 | NXP 的 LPDDR4-4000 建议中，DQS 真互补信号的匹配要求是什么？ | memory | `NXP_IMX8MP_HARDWARE_DEVELOPERS_GUIDE_REV1` / p.15 |
| 26 | `DDR_ANS_NXP_06` | 可回答 | Which elements are included in the i.MX 8M Plus DDR signal-integrity simulation architecture? | memory | `NXP_IMX8MP_HARDWARE_DEVELOPERS_GUIDE_REV1` / p.19 |
| 27 | `DDR_ANS_NXP_07` | 可回答 | i.MX 8M Plus LPDDR4-4000 的 DQ 写眼图宽度目标是多少？ | memory | `NXP_IMX8MP_HARDWARE_DEVELOPERS_GUIDE_REV1` / p.19 |
| 28 | `DDR_ANS_NXP_08` | 可回答 | What package effect must be included when matching i.MX 8M Plus LPDDR4 or DDR4 routes? | memory | `NXP_IMX8MP_HARDWARE_DEVELOPERS_GUIDE_REV1` / p.19,20 |
| 29 | `DDR_ANS_NXP_09` | 可回答 | i.MX 8M Plus 已针对哪些 JEDEC DDR 标准进行设计和测试？ | memory | `NXP_IMX8MP_HARDWARE_DEVELOPERS_GUIDE_REV1` / p.21 |
| 30 | `DDR_ANS_NXP_10` | 可回答 | What revision of the i.MX 8M Plus Hardware Developer's Guide is in this knowledge base? | memory | `NXP_IMX8MP_HARDWARE_DEVELOPERS_GUIDE_REV1` / p.1 |
| 31 | `DDR_REFUSE_01` | 资料不足 | RK3568 的 DDR5 CK 差分阻抗要求是什么？ | memory | — |
| 32 | `DDR_REFUSE_02` | 资料不足 | What LPDDR5 routing-delay limits does the i.MX 8M Plus guide specify? | memory | — |
| 33 | `DDR_REFUSE_03` | 资料不足 | TI AM62x DDR4 布线规则能否直接作为 RK3588 的板级约束？ | memory | — |
| 34 | `DDR_REFUSE_04` | 资料不足 | What DDR4 trace length target does this knowledge base mandate for Micron MT40A devices on i.MX 8M Plus? | memory | — |
| 35 | `DDR_REFUSE_05` | 资料不足 | 当前资料是否规定 AM62x LPDDR4 必须使用 12 层 PCB 叠层？ | memory | — |
| 36 | `DDR_REFUSE_06` | 资料不足 | Provide the complete JEDEC DDR5 eye-mask table from the local knowledge base. | memory | — |
| 37 | `DDR_REFUSE_07` | 资料不足 | 当前知识库是否包含已经批准的 PCB 工厂 3 mil/3 mil 制造能力？ | memory | — |
| 38 | `DDR_REFUSE_08` | 资料不足 | Can the local DDR documents guarantee that my completed board will pass SI simulation? | memory | — |
| 39 | `DDR_REFUSE_09` | 资料不足 | TI AM62x 支持双颗 LPDDR5X 的推荐拓扑是什么？ | memory | — |
| 40 | `DDR_REFUSE_10` | 资料不足 | What is the current market price of DDR4 SDRAM according to this knowledge base? | memory | — |

## V2 新增 50 题

| # | 题号 | 类型 | 题目 | 领域 | 预期来源锚点 |
|---:|---|---|---|---|---|
| 41 | `V2_DDR2_ANS_01` | 可回答 | DDR2 首次上电初始化时，CKE、ODT 和稳定电源/时钟后的等待时间有什么要求？ | memory | `JEDEC_JESD79_2C_DDR2_SDRAM_2006` / p.23 |
| 42 | `V2_DDR2_ANS_02` | 可回答 | DDR2 的 ODT 功能终接哪些信号、由什么控制，以及在 Self Refresh 中是否可用？ | memory | `JEDEC_JESD79_2C_DDR2_SDRAM_2006` / p.33 |
| 43 | `V2_DDR2_ANS_03` | 可回答 | What is DDR2 Posted CAS, and how are additive latency, read latency, and write latency related? | memory | `JEDEC_JESD79_2C_DDR2_SDRAM_2006` / p.39 |
| 44 | `V2_DDR2_ANS_04` | 可回答 | Which burst lengths and burst types does DDR2 support, and what interruption restriction applies to BL=4? | memory | `JEDEC_JESD79_2C_DDR2_SDRAM_2006` / p.40 |
| 45 | `V2_DDR2_ANS_05` | 可回答 | 发出 DDR2 Refresh 命令前，各 Bank 必须处于什么状态？刷新完成后到下一条 Activate 或 Refresh 之间受什么时间约束？ | memory | `JEDEC_JESD79_2C_DDR2_SDRAM_2006` / p.55 |
| 46 | `V2_DDR2_ANS_06` | 可回答 | DDR2 Self Refresh 如何在没有外部时钟时保持数据？进入该模式前 ODT 和 CKE 应如何处理？ | memory | `JEDEC_JESD79_2C_DDR2_SDRAM_2006` / p.56 |
| 47 | `V2_DDR2_REF_01` | 资料不足 | JESD79-2C 对 DDR2-1600 的 tCK、tRCD 和完整 AC 时序限值分别是多少？ | memory | — |
| 48 | `V2_DDR2_REF_02` | 资料不足 | 这份 DDR2 标准中应怎样配置 DDR5 片上 ECC、Bank Group 和 Decision Feedback Equalization？ | memory | — |
| 49 | `V2_HSI_ANS_01` | 可回答 | What general rule does TI give for the total trace length of a high-speed signal pair? | high_speed_interface | `TI_SPRAAR7J_HIGH_SPEED_INTERFACE_LAYOUT_REV_J` / p.5 |
| 50 | `V2_HSI_ANS_02` | 可回答 | For a high-speed differential interface, which lengths must match, and where should serpentine compensation be placed? | high_speed_interface | `TI_SPRAAR7J_HIGH_SPEED_INTERFACE_LAYOUT_REV_J` / p.6 |
| 51 | `V2_HSI_ANS_03` | 可回答 | Why should high-speed traces stay over a solid ground reference plane instead of crossing a split or void? | high_speed_interface | `TI_SPRAAR7J_HIGH_SPEED_INTERFACE_LAYOUT_REV_J` / p.6 |
| 52 | `V2_HSI_ANS_04` | 可回答 | What is TI's 5W spacing rule for high-speed differential pairs, and what spacing results from a 6 mil trace width? | high_speed_interface | `TI_SPRAAR7J_HIGH_SPEED_INTERFACE_LAYOUT_REV_J` / p.9 |
| 53 | `V2_HSI_ANS_05` | 可回答 | USB 通孔插座和表贴插座的高速差分线分别建议从哪一层连接，原因是什么？ | high_speed_interface | `TI_SPRAAR7J_HIGH_SPEED_INTERFACE_LAYOUT_REV_J` / p.10 |
| 54 | `V2_HSI_ANS_06` | 可回答 | 高速信号过孔为什么会造成不连续，TI 对 Stub 长度和过长 Stub 的处理有什么建议？ | high_speed_interface | `TI_SPRAAR7J_HIGH_SPEED_INTERFACE_LAYOUT_REV_J` / p.11 |
| 55 | `V2_HSI_REF_01` | 资料不足 | 依据这份指南，PCIe 6.0 64 GT/s 通道从封装到连接器的精确插损预算是多少 dB？ | high_speed_interface | — |
| 56 | `V2_HSI_REF_02` | 资料不足 | 这份资料能否给出 USB4 80Gbps 连接器的完整认证测试项目、仪器设置和合格限值？ | high_speed_interface | — |
| 57 | `V2_LDO_ANS_01` | 可回答 | LDO 的压降电压如何定义？输入电压低于所需余量时输出会怎样？ | power_management | `TI_ZHCY093_LDO_BASICS_ZH` / p.3 |
| 58 | `V2_LDO_ANS_02` | 可回答 | LDO 的静态电流和关断电流分别描述什么工作状态下的电流消耗？ | power_management | `TI_ZHCY093_LDO_BASICS_ZH` / p.11 |
| 59 | `V2_LDO_ANS_03` | 可回答 | LDO 的“砖墙”电流限制与恒流源有什么区别，内部限流的目的是什么？ | power_management | `TI_ZHCY093_LDO_BASICS_ZH` / p.13 |
| 60 | `V2_LDO_ANS_04` | 可回答 | LDO 出现从 VOUT 流向 VIN 的反向电流时，典型电流路径和潜在风险是什么？ | power_management | `TI_ZHCY093_LDO_BASICS_ZH` / p.15 |
| 61 | `V2_LDO_ANS_05` | 可回答 | LDO 的 PSRR 表示什么？为什么只看数据表在 120 Hz 或 1 kHz 的单点数值可能不够？ | power_management | `TI_ZHCY093_LDO_BASICS_ZH` / p.17 |
| 62 | `V2_LDO_ANS_06` | 可回答 | NR/SS 引脚上的降噪电容如何影响 LDO 输出噪声、启动斜率和浪涌电流？ | power_management | `TI_ZHCY093_LDO_BASICS_ZH` / p.20 |
| 63 | `V2_LDO_REF_01` | 资料不足 | 请给出 TPS7A05 每个引脚的精确编号、封装焊盘尺寸和推荐 PCB 封装图。 | power_management | — |
| 64 | `V2_LDO_REF_02` | 资料不足 | 根据这份资料，今天采购 10,000 颗指定 LDO 的人民币单价、交期和可用库存是多少？ | power_management | — |
| 65 | `V2_SAFE_ANS_01` | 可回答 | 爬电距离与电气间隙分别如何测量，它们主要受哪些不同因素影响？ | electrical_safety | `TI_ZHCP238_CREEPAGE_CLEARANCE_2024` / p.2 |
| 66 | `V2_SAFE_ANS_02` | 可回答 | 污染等级 1 到 4 的环境特征如何逐级变化？办公室和室外持久潮湿环境通常分别属于哪一级？ | electrical_safety | `TI_ZHCP238_CREEPAGE_CLEARANCE_2024` / p.3 |
| 67 | `V2_SAFE_ANS_03` | 可回答 | CTI 如何用于绝缘材料分组？常见 FR4 和 TI 隔离产品在资料中分别归入什么材料组？ | electrical_safety | `TI_ZHCP238_CREEPAGE_CLEARANCE_2024` / p.3 |
| 68 | `V2_SAFE_ANS_04` | 可回答 | 瞬态过压类别按什么原则划分？类别 I 与类别 IV 的典型连接位置有何区别？ | electrical_safety | `TI_ZHCP238_CREEPAGE_CLEARANCE_2024` / p.3 |
| 69 | `V2_SAFE_ANS_05` | 可回答 | 确定基本或增强绝缘的爬电距离前，需要哪些输入条件？增强绝缘如何处理查表所得距离？ | electrical_safety | `TI_ZHCP238_CREEPAGE_CLEARANCE_2024` / p.6 |
| 70 | `V2_SAFE_ANS_06` | 可回答 | 确定电气间隙时为何必须知道瞬态电压、污染等级和海拔？海拔超过 2,000 m 后怎么办？ | electrical_safety | `TI_ZHCP238_CREEPAGE_CLEARANCE_2024` / p.7 |
| 71 | `V2_SAFE_REF_01` | 资料不足 | 某块 1,500 V PCB 的最小爬电距离和电气间隙各是多少毫米？ | electrical_safety | — |
| 72 | `V2_SAFE_REF_02` | 资料不足 | 仅凭这份资料，能否判定我的具体产品已经通过 UL 和 IEC 安规认证？ | electrical_safety | — |
| 73 | `V2_SI_ANS_01` | 可回答 | 这份培训资料如何定义“信号完整性”，分析时要同时检查哪两个方面？ | signal_integrity | `COSH_IP_SIGNAL_INTEGRITY_TRAINING_2009` / s.3 |
| 74 | `V2_SI_ANS_02` | 可回答 | 培训资料中的特征阻抗 Z0 是什么，可用哪两个瞬时量的比值表示？ | signal_integrity | `COSH_IP_SIGNAL_INTEGRITY_TRAINING_2009` / s.7 |
| 75 | `V2_SI_ANS_03` | 可回答 | 资料如何解释传输线反射产生的原因，反射程度用什么量描述？ | signal_integrity | `COSH_IP_SIGNAL_INTEGRITY_TRAINING_2009` / s.8 |
| 76 | `V2_SI_ANS_04` | 可回答 | 与单端信令相比，资料列出的差分信令在摆幅、功耗、EMI/噪声和 SNR 方面有哪些特点？ | signal_integrity | `COSH_IP_SIGNAL_INTEGRITY_TRAINING_2009` / s.22 |
| 77 | `V2_SI_ANS_05` | 可回答 | 抖动的基本定义是什么？资料按计算方法列出了哪些常见抖动类型？ | signal_integrity | `COSH_IP_SIGNAL_INTEGRITY_TRAINING_2009` / s.27 |
| 78 | `V2_SI_ANS_06` | 可回答 | 资料为什么把传输线看作低通滤波器，PCI Express 预加重怎样补偿高频损耗？ | signal_integrity | `COSH_IP_SIGNAL_INTEGRITY_TRAINING_2009` / s.35 |
| 79 | `V2_SI_REF_01` | 资料不足 | 这份 2009 培训资料给出的 PCIe 6.0 PAM4 合规眼图 Mask 数值和 BER 限值是多少？ | signal_integrity | — |
| 80 | `V2_SI_REF_02` | 资料不足 | 没有提供示波器波形、测量带宽和探头信息时，能否判定我这块板的眼图一定合格？ | signal_integrity | — |
| 81 | `V2_CROSS_01` | 可回答 | 联合说明 DDR2 ODT 的用途，以及传输线阻抗不匹配为什么会产生反射。 | memory, signal_integrity | `JEDEC_JESD79_2C_DDR2_SDRAM_2006` / p.33<br>`COSH_IP_SIGNAL_INTEGRITY_TRAINING_2009` / s.8 |
| 82 | `V2_CROSS_02` | 可回答 | 高速差分对组内等长应怎样处理？若用两个单端通道再相减测差分信号，测试端还需要注意什么？ | high_speed_interface, signal_integrity | `TI_SPRAAR7J_HIGH_SPEED_INTERFACE_LAYOUT_REV_J` / p.6<br>`COSH_IP_SIGNAL_INTEGRITY_TRAINING_2009` / s.23 |
| 83 | `V2_CROSS_03` | 可回答 | 排查时钟周期性抖动时，为什么应同时检查给时钟电路供电的 LDO PSRR 与电源噪声？ | power_management, signal_integrity | `TI_ZHCY093_LDO_BASICS_ZH` / p.17<br>`COSH_IP_SIGNAL_INTEGRITY_TRAINING_2009` / s.31 |
| 84 | `V2_CROSS_04` | 可回答 | 高压电源板评审时，LDO 热设计和绝缘电气间隙分别要依据哪些条件判断？ | power_management, electrical_safety | `TI_ZHCY093_LDO_BASICS_ZH` / p.8<br>`TI_ZHCP238_CREEPAGE_CLEARANCE_2024` / p.7 |
| 85 | `V2_CROSS_05` | 可回答 | 用 LDO 给 DDR2 供电时，为什么既要保证 LDO 不进入压降，又要遵守 DDR2 电源/时钟稳定后的初始化等待？ | memory, power_management | `TI_ZHCY093_LDO_BASICS_ZH` / p.3<br>`JEDEC_JESD79_2C_DDR2_SDRAM_2006` / p.23 |
| 86 | `V2_CROSS_06` | 可回答 | 同一块 PCB 上高速差分线靠近高压区时，参考平面连续性与安规距离分别解决什么风险？ | high_speed_interface, electrical_safety | `TI_SPRAAR7J_HIGH_SPEED_INTERFACE_LAYOUT_REV_J` / p.6<br>`TI_ZHCP238_CREEPAGE_CLEARANCE_2024` / p.2 |
| 87 | `V2_AMBIG_01` | 歧义澄清 | 这块板的间距应该留多少？ | 待澄清 | — |
| 88 | `V2_AMBIG_02` | 歧义澄清 | 这个问题应该怎么布线才正确？ | 待澄清 | — |
| 89 | `V2_AMBIG_03` | 歧义澄清 | 这个参数超限会有什么后果？ | 待澄清 | — |
| 90 | `V2_AMBIG_04` | 歧义澄清 | 这个设计是否合格？ | 待澄清 | — |

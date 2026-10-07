from types import SimpleNamespace

from ddr_rag.query_scope import enrich_query, resolve_document_scope


def test_enrich_query_appends_local_english_ddr_aliases() -> None:
    expanded = enrich_query("LPDDR4 过孔延迟与眼图宽度")

    assert "via" in expanded
    assert "propagation delay" in expanded
    assert "eye width" in expanded


def test_enrich_query_appends_chinese_aliases_for_english_routing_terms() -> None:
    expanded = enrich_query("DDR4 clock routing L2a-to-L2b mismatch")

    assert "时钟" in expanded
    assert "走线" in expanded
    assert "等长" in expanded
    assert "长度差" in expanded


def test_enrich_query_adds_document_metadata_aliases() -> None:
    expanded = enrich_query("What revision is this hardware guide?")

    assert "document information" in expanded
    assert "Rev." in expanded


def test_enrich_query_compacts_spaced_engineering_units() -> None:
    assert "1500mil" in enrich_query("DDR4 CLK-to-DQS limit is 1500 mil")


def test_enrich_query_expands_jedec_to_a_generic_compliance_phrase() -> None:
    assert "JEDEC specification compliance" in enrich_query("JEDEC DDR 标准有哪些？")


def test_enrich_query_adds_power_up_and_odt_aliases() -> None:
    expanded = enrich_query("DDR2 上电初始化时保持 ODT 为低电平")

    assert "power-up and initialization sequence" in expanded
    assert "stable power" in expanded
    assert "on-die termination" in expanded

    waiting = enrich_query("DDR2 电源和时钟稳定后的初始化等待")
    assert "power-up and initialization sequence" in waiting
    assert "200 us" in waiting


def test_enrich_query_adds_signal_integrity_definition_aliases() -> None:
    expanded = enrich_query("信号完整性如何定义？")

    assert "signal integrity definition" in expanded
    assert "voltage waveform" in expanded
    assert "timing" in expanded


def test_enrich_query_adds_cross_domain_thermal_and_clearance_terms() -> None:
    expanded = enrich_query("LDO 热设计和绝缘电气间隙分别依据哪些条件？")

    assert "thermal performance" in expanded
    assert "junction temperature" in expanded
    assert "IEC 60664-1" in expanded
    assert "海拔 2000m" in expanded


def test_enrich_query_adds_reference_plane_and_safety_risk_terms() -> None:
    expanded = enrich_query("参考平面连续性与安规距离分别解决什么风险？")

    assert "high-speed signal reference planes" in expanded
    assert "return current" in expanded
    assert "爬电距离" in expanded
    assert "瞬态过压" in expanded


def test_resolve_document_scope_uses_only_a_unique_catalog_part(monkeypatch) -> None:
    catalog = SimpleNamespace(
        documents=[
            SimpleNamespace(doc_id="RK", applicable_parts=["RK3568"], status="active"),
            SimpleNamespace(doc_id="TI", applicable_parts=["AM62x"], status="active"),
        ]
    )
    monkeypatch.setattr("ddr_rag.query_scope.load_catalog", lambda settings: catalog)

    assert resolve_document_scope(object(), "RK3568 DDR4 clock") == ("RK",)
    assert resolve_document_scope(object(), "generic DDR4 clock") is None
    assert resolve_document_scope(object(), "RK3568 DDR4 clock", "TI") == ("TI",)


def test_resolve_document_scope_keeps_all_documents_for_the_same_part(monkeypatch) -> None:
    catalog = SimpleNamespace(
        documents=[
            SimpleNamespace(doc_id="RK_GUIDE", applicable_parts=["RK3568"], status="active"),
            SimpleNamespace(doc_id="RK_NOTE", applicable_parts=["RK3568"], status="active"),
            SimpleNamespace(doc_id="TI_GUIDE", applicable_parts=["AM62x"], status="active"),
        ]
    )
    monkeypatch.setattr("ddr_rag.query_scope.load_catalog", lambda settings: catalog)

    assert resolve_document_scope(object(), "RK3568 DDR4 clock") == ("RK_GUIDE", "RK_NOTE")
    assert resolve_document_scope(object(), "Compare RK3568 and AM62x") == (
        "RK_GUIDE", "RK_NOTE", "TI_GUIDE"
    )

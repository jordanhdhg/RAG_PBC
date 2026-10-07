"""Local query enrichment and auditable hardware-domain scope resolution."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ddr_rag.catalog import load_catalog
from ddr_rag.config import AppSettings
from ddr_rag.taxonomy import (
    CONTROLLED_DOMAINS,
    CONTROLLED_MEMORY_TYPES,
    DOMAIN_TOPICS,
    normalize_domains,
    normalize_interfaces,
    normalize_memory_types,
    normalize_topics,
    validate_domain_topic_relationship,
)


class QueryScopeError(RuntimeError):
    """Raised when explicit query filters are invalid or mutually inconsistent."""


class QueryScope(BaseModel):
    """One fully local, serializable decision about the permitted retrieval scope."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    status: Literal["resolved", "clarification_required"]
    domains: list[str] = Field(default_factory=list)
    candidate_domains: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    applicable_interfaces: list[str] = Field(default_factory=list)
    applicable_parts: list[str] = Field(default_factory=list)
    memory_types: list[str] = Field(default_factory=list)
    doc_ids: list[str] | None = None
    active_only: bool = True
    routing_source: Literal[
        "explicit_domains", "explicit_filters", "automatic", "unresolved"
    ]
    explicit_filters: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)

    @property
    def clarification_message(self) -> str:
        choices = ", ".join(self.candidate_domains or sorted(CONTROLLED_DOMAINS))
        return f"需要澄清领域；请使用 --domain 明确选择以下一个或多个领域：{choices}"


_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "memory": (
        r"(?<![A-Z0-9])(?:LP)?DDR[2-5]X?(?![A-Z0-9])",
        r"(?<![A-Z0-9])SDRAM(?![A-Z0-9])",
        r"内存|存储器",
    ),
    "high_speed_interface": (
        r"(?<![A-Z0-9])USB(?:[23](?:\.\d)?)?(?![A-Z0-9])",
        r"(?<![A-Z0-9])SATA(?![A-Z0-9])",
        r"(?<![A-Z0-9])PCI(?:E| EXPRESS)(?![A-Z0-9])",
        r"(?<![A-Z0-9])HDMI(?![A-Z0-9])",
        r"(?<![A-Z0-9])SGMII(?![A-Z0-9])",
        r"(?<![A-Z0-9])CSI(?:-?2)?(?![A-Z0-9])",
        r"高速接口",
    ),
    "power_management": (
        r"(?<![A-Z0-9])LDO(?![A-Z0-9])",
        r"POWER SUPPLY|VOLTAGE REGULATOR|POWER SEQUENCING",
        r"电源管理|供电|稳压|上电时序",
    ),
    "electrical_safety": (
        r"CREEPAGE|CLEARANCE|INSULATION|ELECTRICAL SAFETY",
        r"爬电|电气间隙|安规|绝缘|高压PCB",
    ),
    "signal_integrity": (
        r"SIGNAL INTEGRITY|EYE DIAGRAM|JITTER",
        r"(?<![A-Z0-9])SI(?![A-Z0-9])",
        r"信号完整性|眼图|抖动",
    ),
    "hardware_general": (
        r"GENERAL HARDWARE|HARDWARE DESIGN|PCB LAYOUT",
        r"通用硬件|硬件设计|PCB布局",
    ),
}


_CHINESE_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "上电初始化",
        ("power-up and initialization sequence", "stable power", "stable clock", "200 us"),
    ),
    ("过孔", ("via", "vias")),
    ("延迟", ("delay", "propagation delay")),
    ("等长", ("length matching", "skew")),
    ("终端", ("termination", "terminators")),
    ("网络类别", ("net classes",)),
    ("刷新", ("refresh",)),
    ("供电", ("power supply",)),
    ("电流", ("current",)),
    ("阻抗", ("impedance",)),
    ("反射", ("reflection",)),
    ("压降", ("dropout",)),
    (
        "热设计",
        (
            "第 3 章 热性能",
            "接面温度",
            "功耗",
            "热阻",
            "封装",
            "thermal performance",
            "junction temperature",
            "power dissipation",
            "package",
        ),
    ),
    (
        "参考平面",
        ("high-speed signal reference planes", "continuous ground", "return current"),
    ),
    (
        "安规距离",
        (
            "爬电距离",
            "电气间隙",
            "固体绝缘表面",
            "工作电压",
            "污染",
            "湿度",
            "瞬态过压",
            "空气电离",
            "电弧",
        ),
    ),
    ("拓扑", ("topology",)),
    ("间距", ("spacing",)),
    ("时钟", ("clock",)),
    ("眼图", ("eye", "eye width")),
)

_ENGLISH_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("odt", ("on-die termination",)),
    ("clock", ("时钟", "CLK")),
    ("routing", ("走线",)),
    ("mismatch", ("等长", "长度差", "skew", "length matching")),
    ("length matching", ("等长", "长度差", "skew")),
    ("skew", ("等长", "长度差", "length matching")),
    ("revision", ("document information", "Rev.")),
    ("version", ("document information", "Rev.")),
    ("jedec", ("JEDEC specification compliance",)),
)


def _has_english_term(text: str, term: str) -> bool:
    """Match a readable English term without matching inside an identifier."""

    return bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text, flags=re.IGNORECASE))


def _infer_explicit_memory_names(query: str) -> list[str]:
    """Extract only fully named memory standards without widening automatic domain routing."""

    return [
        memory_type
        for memory_type in sorted(CONTROLLED_MEMORY_TYPES)
        if re.search(
            rf"(?<![A-Z0-9]){re.escape(memory_type)}(?![A-Z0-9])",
            query,
            flags=re.IGNORECASE,
        )
    ]


def enrich_query(query: str) -> str:
    """Append small deterministic Chinese/English aliases for common DDR terms.

    This is local vocabulary expansion, not translation-model inference. It lets
    English engineering questions match Chinese vendor guides (and vice versa),
    while giving BM25 and the multilingual BGE-M3 encoder the same domain terms.
    """

    normalized = query.strip()
    additions: list[str] = []
    for chinese_term, english_terms in _CHINESE_TERMS:
        if chinese_term in normalized:
            additions.extend(english_terms)
    for english_term, chinese_terms in _ENGLISH_TERMS:
        if _has_english_term(normalized, english_term):
            additions.extend(chinese_terms)
    for number, unit in re.findall(
        r"\b(\d+(?:\.\d+)?)\s+(mil|mm|ohm|ma|mv|v|ps|ns)\b",
        normalized,
        flags=re.IGNORECASE,
    ):
        additions.append(f"{number}{unit}")
    if "眼图" in normalized and "写" in normalized:
        additions.append("write")
    if "信号完整性" in normalized and "定义" in normalized:
        additions.extend(("signal integrity definition", "voltage waveform", "timing"))
    if "初始化" in normalized and ("稳定" in normalized or "等待" in normalized):
        additions.extend(
            ("power-up and initialization sequence", "stable power", "stable clock", "200 us")
        )
    if "电气间隙" in normalized and ("条件" in normalized or "依据" in normalized):
        additions.extend(
            (
                "脉冲电压",
                "终端设备类型",
                "IEC 60664-1",
                "IEC 62368-1",
                "IEC 61800-5",
                "IEC 62109-1",
                "海拔 2000m",
            )
        )
    existing = normalized.casefold()
    unique = [term for term in dict.fromkeys(additions) if term.casefold() not in existing]
    return " ".join((normalized, *unique)) if unique else normalized


def _normalized_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _unique_text(values: list[str] | tuple[str, ...] | None) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in (values or []) if value.strip()))


def infer_query_domains(query: str) -> list[str]:
    """Return every domain explicitly indicated by deterministic local keywords."""

    normalized = query.upper()
    return [
        domain
        for domain, patterns in _DOMAIN_HINTS.items()
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns)
    ]


def _domains_for_topics(values: list[str]) -> set[str]:
    if not values:
        return set()
    candidates = [
        {domain for domain, topics in DOMAIN_TOPICS.items() if topic in topics}
        for topic in values
    ]
    intersection = set.intersection(*candidates)
    return intersection or set.union(*candidates)


def _active_catalog_documents(settings: AppSettings, *, active_only: bool) -> list[Any]:
    try:
        catalog = load_catalog(settings)
    except (FileNotFoundError, OSError) as exc:
        raise QueryScopeError(f"Could not load the document catalog for query routing: {exc}") from exc
    return [
        document
        for document in catalog.documents
        if not active_only or document.status == "active"
    ]


def _resolve_document_filters(
    settings: AppSettings,
    query: str,
    *,
    explicit_doc_id: str | None,
    explicit_parts: list[str],
    active_only: bool,
) -> tuple[list[str] | None, list[str], list[str]]:
    """Resolve document/part filters without using them to broaden domain scope."""

    reasons: list[str] = []
    if explicit_doc_id or explicit_parts:
        documents = _active_catalog_documents(settings, active_only=active_only)
        selected = documents
        if explicit_doc_id:
            selected = [
                document
                for document in selected
                if document.doc_id == explicit_doc_id.strip()
            ]
            if not selected:
                raise QueryScopeError(
                    "Registered document is not available in the selected status scope: "
                    f"{explicit_doc_id}"
                )
            reasons.append(f"显式文档过滤：{explicit_doc_id.strip()}")
        matched_parts: list[str] = []
        if explicit_parts:
            normalized_parts = {_normalized_identifier(part) for part in explicit_parts}
            matched_parts = sorted(
                {
                    part
                    for document in selected
                    for part in document.applicable_parts
                    if _normalized_identifier(part) in normalized_parts
                }
            )
            selected = [
                document
                for document in selected
                if any(
                    _normalized_identifier(part) in normalized_parts
                    for part in document.applicable_parts
                )
            ]
            reasons.append("显式型号过滤：" + ", ".join(explicit_parts))
            if not selected:
                reasons.append("没有登记文档匹配显式型号过滤")
        return sorted({document.doc_id for document in selected}), matched_parts, reasons

    try:
        documents = _active_catalog_documents(settings, active_only=active_only)
    except QueryScopeError:
        return None, [], reasons
    normalized_query = _normalized_identifier(query)
    inferred_parts = sorted(
        {
            part
            for document in documents
            for part in document.applicable_parts
            if (normalized_part := _normalized_identifier(part))
            and normalized_part in normalized_query
        }
    )
    if not inferred_parts:
        return None, [], reasons
    inferred_ids = sorted(
        {
            document.doc_id
            for document in documents
            if any(part in inferred_parts for part in document.applicable_parts)
        }
    )
    reasons.append("从问题识别适用型号：" + ", ".join(inferred_parts))
    return inferred_ids, inferred_parts, reasons


def resolve_query_scope(
    settings: AppSettings,
    query: str,
    *,
    explicit_doc_id: str | None = None,
    explicit_domains: list[str] | tuple[str, ...] | None = None,
    explicit_topics: list[str] | tuple[str, ...] | None = None,
    explicit_interfaces: list[str] | tuple[str, ...] | None = None,
    explicit_parts: list[str] | tuple[str, ...] | None = None,
    memory_type: str | None = None,
    active_only: bool = True,
) -> QueryScope:
    """Resolve explicit filters first, then use a deterministic single-domain router."""

    normalized_query = query.strip()
    if not normalized_query:
        raise QueryScopeError("Query cannot be empty.")
    raw_domains = _unique_text(explicit_domains)
    raw_topics = _unique_text(explicit_topics)
    raw_interfaces = _unique_text(explicit_interfaces)
    raw_parts = _unique_text(explicit_parts)
    try:
        domains = normalize_domains(raw_domains) if raw_domains else []
        topics = normalize_topics(raw_topics) if raw_topics else []
        interfaces = normalize_interfaces(raw_interfaces)
        memory_types = normalize_memory_types([memory_type]) if memory_type else []
        if domains and topics:
            validate_domain_topic_relationship(domains, topics)
        if domains and interfaces:
            validate_domain_topic_relationship(domains, interfaces)
    except ValueError as exc:
        raise QueryScopeError(str(exc)) from exc
    if memory_types and domains and "memory" not in domains:
        raise QueryScopeError("--memory-type requires --domain memory when domains are explicit.")

    doc_ids, parts, document_reasons = _resolve_document_filters(
        settings,
        normalized_query,
        explicit_doc_id=explicit_doc_id,
        explicit_parts=raw_parts,
        active_only=active_only,
    )
    explicit_filter_summary: dict[str, Any] = {
        "doc_id": explicit_doc_id.strip() if explicit_doc_id else None,
        "domains": domains,
        "topics": topics,
        "interfaces": interfaces,
        "parts": raw_parts,
        "memory_type": memory_types[0] if memory_types else None,
    }
    reasons = list(document_reasons)
    if domains:
        if "memory" in domains and not memory_types:
            memory_types = _infer_explicit_memory_names(normalized_query)
            if memory_types:
                reasons.append("从问题识别内存类型：" + ", ".join(memory_types))
        reasons.append("使用显式领域：" + ", ".join(domains))
        return QueryScope(
            query=normalized_query,
            status="resolved",
            domains=domains,
            topics=topics,
            applicable_interfaces=interfaces,
            applicable_parts=parts,
            memory_types=memory_types,
            doc_ids=doc_ids,
            active_only=active_only,
            routing_source="explicit_domains",
            explicit_filters=explicit_filter_summary,
            reasons=reasons,
        )

    explicit_candidates: set[str] = set()
    if memory_types:
        explicit_candidates = {"memory"}
        reasons.append("由 --memory-type 确定 memory 领域")
    constraint_sets: list[set[str]] = []
    if topics:
        constraint_sets.append(_domains_for_topics(topics))
        reasons.append("由显式主题推导候选领域")
    if interfaces:
        constraint_sets.append(_domains_for_topics(interfaces))
        reasons.append("由显式接口推导候选领域")
    if constraint_sets:
        constrained = set.intersection(*constraint_sets)
        if not constrained:
            raise QueryScopeError(
                "Explicit topic/interface filters do not share a compatible domain."
            )
        if explicit_candidates:
            compatible = explicit_candidates.intersection(constrained)
            if not compatible:
                raise QueryScopeError(
                    "Explicit topic/interface filters conflict with --memory-type domain scope."
                )
            explicit_candidates = compatible
        else:
            explicit_candidates = constrained
    if len(explicit_candidates) == 1:
        resolved_domain = next(iter(explicit_candidates))
        return QueryScope(
            query=normalized_query,
            status="resolved",
            domains=[resolved_domain],
            topics=topics,
            applicable_interfaces=interfaces,
            applicable_parts=parts,
            memory_types=memory_types,
            doc_ids=doc_ids,
            active_only=active_only,
            routing_source="explicit_filters",
            explicit_filters=explicit_filter_summary,
            reasons=reasons,
        )

    inferred_domains = set(infer_query_domains(normalized_query))
    candidates = explicit_candidates or inferred_domains
    if explicit_candidates and inferred_domains:
        narrowed = explicit_candidates.intersection(inferred_domains)
        if narrowed:
            candidates = narrowed
            reasons.append("本地关键词路由缩小了显式过滤器的候选领域")
    elif inferred_domains:
        reasons.append("本地关键词路由命中：" + ", ".join(sorted(inferred_domains)))

    if len(candidates) == 1:
        resolved_domain = next(iter(candidates))
        return QueryScope(
            query=normalized_query,
            status="resolved",
            domains=[resolved_domain],
            topics=topics,
            applicable_interfaces=interfaces,
            applicable_parts=parts,
            memory_types=memory_types,
            doc_ids=doc_ids,
            active_only=active_only,
            routing_source="explicit_filters" if explicit_candidates else "automatic",
            explicit_filters=explicit_filter_summary,
            reasons=reasons,
        )

    candidate_domains = sorted(candidates or CONTROLLED_DOMAINS)
    reasons.append("领域无法唯一确定，检索和回答均未启动")
    return QueryScope(
        query=normalized_query,
        status="clarification_required",
        candidate_domains=candidate_domains,
        topics=topics,
        applicable_interfaces=interfaces,
        applicable_parts=parts,
        memory_types=memory_types,
        doc_ids=doc_ids,
        active_only=active_only,
        routing_source="unresolved",
        explicit_filters=explicit_filter_summary,
        reasons=reasons,
    )


def scope_for_domain(scope: QueryScope, domain: str) -> QueryScope:
    """Create a single-domain retrieval scope from a resolved cross-domain request."""

    if domain not in scope.domains:
        raise QueryScopeError(f"Domain {domain} is outside the resolved query scope.")
    return scope.model_copy(
        update={
            "domains": [domain],
            "memory_types": scope.memory_types if domain == "memory" else [],
        }
    )


def resolve_document_scope(
    settings: AppSettings,
    query: str,
    explicit_doc_id: str | None = None,
) -> tuple[str, ...] | None:
    """Return every active document for mentioned part IDs, or no inferred scope."""

    if explicit_doc_id:
        return (explicit_doc_id.strip(),)
    normalized_query = _normalized_identifier(query)
    if not normalized_query:
        return None
    try:
        catalog = load_catalog(settings)
    except (FileNotFoundError, OSError):
        return None
    matches = {
        document.doc_id
        for document in catalog.documents
        if document.status == "active"
        and any(
            (normalized_part := _normalized_identifier(part))
            and normalized_part in normalized_query
            for part in document.applicable_parts
        )
    }
    return tuple(sorted(matches)) if matches else None

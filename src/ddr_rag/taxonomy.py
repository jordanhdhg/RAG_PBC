"""Controlled metadata vocabulary for the general hardware RAG data model."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final


TAXONOMY_VERSION: Final = "hardware-v2-taxonomy-v1"

# A topic may intentionally belong to more than one domain.  For example, PCIe
# material can describe both interface layout and signal-integrity measurement.
DOMAIN_TOPICS: Final[dict[str, frozenset[str]]] = {
    "memory": frozenset(
        {
            "ddr2", "ddr3", "ddr3l", "ddr4", "ddr5", "lpddr3", "lpddr4",
            "lpddr4x", "lpddr5", "lpddr5x", "sdram_standard",
            "ddr_design", "ddr_routing", "ddr_power",
        }
    ),
    "high_speed_interface": frozenset(
        {"usb", "sata", "pcie", "hdmi", "sgmii", "csi", "high_speed_layout"}
    ),
    "power_management": frozenset(
        {"ldo", "power_supply", "power_sequencing", "power_integrity", "ddr_power"}
    ),
    "electrical_safety": frozenset(
        {"creepage_clearance", "high_voltage_pcb", "insulation", "clearance"}
    ),
    "signal_integrity": frozenset(
        {"signal_integrity", "eye_diagram", "jitter", "pcie", "impedance", "termination"}
    ),
    "hardware_general": frozenset({"hardware_design", "pcb_layout"}),
}

CONTROLLED_DOMAINS: Final[frozenset[str]] = frozenset(DOMAIN_TOPICS)
CONTROLLED_TOPICS: Final[frozenset[str]] = frozenset().union(*DOMAIN_TOPICS.values())
CONTROLLED_MEMORY_TYPES: Final[frozenset[str]] = frozenset(
    {"DDR2", "DDR3", "DDR3L", "DDR4", "DDR5", "LPDDR3", "LPDDR4", "LPDDR4X", "LPDDR5", "LPDDR5X"}
)
CONTROLLED_INTERFACES: Final[frozenset[str]] = frozenset(
    {"usb", "sata", "pcie", "hdmi", "sgmii", "csi"}
)


def _normalize(values: Iterable[str], *, uppercase: bool = False) -> list[str]:
    normalized: list[str] = []
    for value in values:
        item = value.strip()
        if not item:
            continue
        item = item.upper() if uppercase else item.casefold()
        if item not in normalized:
            normalized.append(item)
    return normalized


def normalize_domains(values: Iterable[str]) -> list[str]:
    normalized = _normalize(values)
    unknown = sorted(set(normalized).difference(CONTROLLED_DOMAINS))
    if unknown:
        raise ValueError("unknown domains: " + ", ".join(unknown))
    if not normalized:
        raise ValueError("domains must contain at least one controlled value")
    return normalized


def normalize_topics(values: Iterable[str]) -> list[str]:
    normalized = _normalize(values)
    unknown = sorted(set(normalized).difference(CONTROLLED_TOPICS))
    if unknown:
        raise ValueError("unknown topics: " + ", ".join(unknown))
    if not normalized:
        raise ValueError("topics must contain at least one controlled value")
    return normalized


def normalize_memory_types(values: Iterable[str]) -> list[str]:
    normalized = _normalize(values, uppercase=True)
    unknown = sorted(set(normalized).difference(CONTROLLED_MEMORY_TYPES))
    if unknown:
        raise ValueError("unknown memory_types: " + ", ".join(unknown))
    return normalized


def normalize_interfaces(values: Iterable[str]) -> list[str]:
    normalized = _normalize(values)
    unknown = sorted(set(normalized).difference(CONTROLLED_INTERFACES))
    if unknown:
        raise ValueError("unknown applicable_interfaces: " + ", ".join(unknown))
    return normalized


def topics_for_memory_types(memory_types: Iterable[str]) -> list[str]:
    """Return the controlled legacy DDR topics used to read unchanged V1.2 records."""

    return [memory_type.casefold() for memory_type in normalize_memory_types(memory_types)]


def validate_domain_topic_relationship(domains: Iterable[str], topics: Iterable[str]) -> None:
    domain_list = normalize_domains(domains)
    topic_list = normalize_topics(topics)
    allowed = frozenset().union(*(DOMAIN_TOPICS[domain] for domain in domain_list))
    invalid = sorted(set(topic_list).difference(allowed))
    if invalid:
        raise ValueError(
            "topics are not valid for the selected domains: " + ", ".join(invalid)
        )


def validate_classification(
    *,
    domains: Iterable[str],
    topics: Iterable[str],
    memory_types: Iterable[str],
    applicable_interfaces: Iterable[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    normalized_domains = normalize_domains(domains)
    normalized_topics = normalize_topics(topics)
    normalized_memory_types = normalize_memory_types(memory_types)
    normalized_interfaces = normalize_interfaces(applicable_interfaces)
    validate_domain_topic_relationship(normalized_domains, normalized_topics)
    if normalized_memory_types and "memory" not in normalized_domains:
        raise ValueError("memory_types may only be set when domains includes memory")
    return (
        normalized_domains,
        normalized_topics,
        normalized_memory_types,
        normalized_interfaces,
    )

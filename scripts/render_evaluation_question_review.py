"""Render immutable V1 and V2 evaluation YAML files as one readable Markdown list."""

from __future__ import annotations

import argparse
from pathlib import Path

from ddr_rag.evaluation import EvaluationDataset, EvaluationQuestion, load_evaluation_dataset


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _question_type(question: EvaluationQuestion) -> str:
    if question.expected_route_status == "clarification_required":
        return "歧义澄清"
    return "可回答" if question.answerable else "资料不足"


def _source_summary(question: EvaluationQuestion) -> str:
    if not question.expected_sources:
        return "—"
    summaries: list[str] = []
    for source in question.expected_sources:
        if source.page_numbers:
            locator = "p." + ",".join(str(value) for value in source.page_numbers)
        elif source.slide_numbers:
            locator = "s." + ",".join(str(value) for value in source.slide_numbers)
        else:
            locator = "elements:" + ",".join(source.element_refs)
        summaries.append(f"`{source.doc_id}` / {locator}")
    return "<br>".join(summaries)


def _dataset_rows(dataset: EvaluationDataset, start: int) -> list[str]:
    rows: list[str] = []
    for number, question in enumerate(dataset.questions, start=start):
        domains = ", ".join(question.domains) if question.domains else "待澄清"
        rows.append(
            "| "
            + " | ".join(
                (
                    str(number),
                    f"`{question.question_id}`",
                    _question_type(question),
                    _cell(question.question),
                    _cell(domains),
                    _source_summary(question),
                )
            )
            + " |"
        )
    return rows


def render_review(old_dataset: EvaluationDataset, new_dataset: EvaluationDataset) -> str:
    total = len(old_dataset.questions) + len(new_dataset.questions)
    lines = [
        "# 通用硬件 RAG V2 阶段 4：90 题审查清单",
        "",
        f"- 总题数：{total}",
        f"- 原 DDR 冻结题：{len(old_dataset.questions)}（原文件不修改）",
        f"- V2 新增题：{len(new_dataset.questions)}（36 道可回答，10 道资料不足，4 道歧义澄清）",
        "- 本清单只展示题面与来源锚点；关键事实和拒答理由以对应 YAML 为准。",
        "",
        "## 原 DDR 冻结 40 题",
        "",
        "| # | 题号 | 类型 | 题目 | 领域 | 预期来源锚点 |",
        "|---:|---|---|---|---|---|",
        *_dataset_rows(old_dataset, 1),
        "",
        "## V2 新增 50 题",
        "",
        "| # | 题号 | 类型 | 题目 | 领域 | 预期来源锚点 |",
        "|---:|---|---|---|---|---|",
        *_dataset_rows(new_dataset, len(old_dataset.questions) + 1),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    old_dataset = load_evaluation_dataset(args.old.resolve())
    new_dataset = load_evaluation_dataset(args.new.resolve())
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_review(old_dataset, new_dataset), encoding="utf-8")
    print(f"Wrote {len(old_dataset.questions) + len(new_dataset.questions)} questions to {output}")


if __name__ == "__main__":
    main()

"""modules/pdf_report.py — Generate a PDF analysis report.

Layout:
  Page 1 — Summary: title, date, total photos, cost breakdown (by model),
                     top categories, top tags.
  Page 2+ — Per-photo table: filename · category · mood · tokens · cost · time.

Uses bundled Noto Sans TC (Traditional Chinese) Variable TTF for CJK glyphs.
reportlab's built-in CID fonts (MSung-Light/STSong-Light) reference a CMap
that's inconsistent with their CIDSystemInfo, which trips most PDF viewers
("Unknown CMap 'UniGB-UCS2-H' for character collection 'Adobe-CNS1'"), so we
ship a real TTF instead. SIL OFL license — safe to bundle.
"""

from __future__ import annotations

import io
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

from modules.pricing import PRICING, USD_TO_TWD_APPROX

_FONT_REGISTERED = False
_FONT_NAME = "NotoSansTC"
_FONT_FILE = "NotoSansTC-Regular.ttf"


def _find_bundled_font() -> Path | None:
    """Return path to the bundled CJK TTF, searching source tree first and
    then PyInstaller's _MEIPASS runtime dir for packaged builds."""
    candidates: list[Path] = [
        Path(__file__).resolve().parent.parent / "assets" / _FONT_FILE,
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / _FONT_FILE)
    for p in candidates:
        if p.exists():
            return p
    return None


def _ensure_cjk_font() -> str:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return _FONT_NAME
    font_path = _find_bundled_font()
    if font_path is None:
        raise RuntimeError(
            f"CJK font not found. Expected {_FONT_FILE} under assets/ or PyInstaller _MEIPASS."
        )
    pdfmetrics.registerFont(TTFont(_FONT_NAME, str(font_path)))
    _FONT_REGISTERED = True
    return _FONT_NAME


# Colors — light paper-friendly, violet accent matches Happy Vision brand
C_INK = colors.HexColor("#111315")
C_MUTE = colors.HexColor("#6b6b75")
C_LINE = colors.HexColor("#d8d8dd")
C_ACCENT = colors.HexColor("#6d4bff")
C_SUBTLE = colors.HexColor("#f5f4f9")


def _build_styles():
    font = _ensure_cjk_font()
    base = getSampleStyleSheet()["BodyText"]
    return {
        "cjk": font,
        "title": ParagraphStyle(
            "Title", parent=base, fontName=font, fontSize=24, leading=30,
            textColor=C_INK, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base, fontName=font, fontSize=11, leading=16,
            textColor=C_MUTE, spaceAfter=16,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base, fontName=font, fontSize=13, leading=18,
            textColor=C_INK, spaceAfter=6, spaceBefore=14,
        ),
        "kicker": ParagraphStyle(
            "Kicker", parent=base, fontName=font, fontSize=8, leading=12,
            textColor=C_MUTE, spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "Body", parent=base, fontName=font, fontSize=10, leading=14,
            textColor=C_INK,
        ),
        "small": ParagraphStyle(
            "Small", parent=base, fontName=font, fontSize=8, leading=11,
            textColor=C_MUTE,
        ),
        "mono_small": ParagraphStyle(
            "MonoSmall", parent=base, fontName="Courier", fontSize=8, leading=11,
            textColor=C_INK,
        ),
    }


def _summary_stats(results: list[dict]) -> dict:
    """Aggregate counts, tokens, cost by model."""
    total = len(results)
    total_input = 0
    total_output = 0
    total_cost = 0.0
    per_model: dict[str, dict] = {}
    categories: Counter = Counter()
    tags: Counter = Counter()
    for r in results:
        u = r.get("_usage") or {}
        model = u.get("model") or "(unknown)"
        inp = int(u.get("input_tokens") or 0)
        out = int(u.get("output_tokens") or 0)
        cost = float(u.get("cost_usd") or 0.0)
        total_input += inp
        total_output += out
        total_cost += cost
        bucket = per_model.setdefault(model, {"count": 0, "input": 0, "output": 0, "cost": 0.0})
        bucket["count"] += 1
        bucket["input"] += inp
        bucket["output"] += out
        bucket["cost"] += cost
        if r.get("category"):
            categories[r["category"]] += 1
        for kw in r.get("keywords") or []:
            tags[kw] += 1
    return {
        "total": total,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cost_usd": total_cost,
        "per_model": per_model,
        "top_categories": categories.most_common(8),
        "top_tags": tags.most_common(15),
    }


def _fmt_usd(v: float) -> str:
    if v >= 1.0:
        return f"${v:,.2f}"
    return f"${v:.4f}"


def _fmt_twd(v: float) -> str:
    return f"NT${int(round(v * USD_TO_TWD_APPROX)):,}"


def _fmt_n(v: int | None) -> str:
    if v is None:
        return "—"
    return f"{int(v):,}"


def _summary_page(results: list[dict], styles: dict, folder: str | None) -> list:
    stats = _summary_stats(results)
    flow = []

    flow.append(Paragraph("Happy Vision 分析報告", styles["title"]))
    sub = datetime.now().strftime("%Y-%m-%d %H:%M")
    if folder:
        sub = f"{sub} · {folder}"
    flow.append(Paragraph(sub, styles["subtitle"]))

    # Overview grid (2x2)
    overview_data = [
        [
            _kv("總張數", f"{stats['total']:,}", styles),
            _kv("總花費 (USD)", _fmt_usd(stats["cost_usd"]), styles),
        ],
        [
            _kv("約合 TWD", _fmt_twd(stats["cost_usd"]), styles),
            _kv("總 tokens", f"{(stats['input_tokens'] + stats['output_tokens']):,}", styles),
        ],
    ]
    overview = Table(overview_data, colWidths=[85 * mm, 85 * mm])
    overview.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, C_LINE),
        ("BACKGROUND", (0, 0), (-1, -1), C_SUBTLE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    flow.append(overview)

    # Per-model breakdown
    flow.append(Paragraph("花費明細 · 依模型", styles["h2"]))
    model_rows = [["模型", "張數", "Input tokens", "Output tokens", "花費 USD", "≈ NT$"]]
    for model, b in sorted(stats["per_model"].items(), key=lambda kv: -kv[1]["cost"]):
        model_rows.append([
            model,
            _fmt_n(b["count"]),
            _fmt_n(b["input"]),
            _fmt_n(b["output"]),
            _fmt_usd(b["cost"]),
            _fmt_twd(b["cost"]),
        ])
        # Show price row
        price = PRICING.get(model)
        if price:
            price_note = f"  定價 ${price['input']}/M input · ${price['output']}/M output"
            model_rows.append([Paragraph(price_note, styles["small"]), "", "", "", "", ""])
    mtable = Table(model_rows, colWidths=[60 * mm, 18 * mm, 30 * mm, 30 * mm, 20 * mm, 20 * mm])
    mtable.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), styles["cjk"], 9),
        ("FONT", (0, 0), (-1, 0), styles["cjk"], 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), C_ACCENT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, C_ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_SUBTLE]),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    flow.append(mtable)

    # Top categories + tags
    if stats["top_categories"]:
        flow.append(Paragraph("主要分類", styles["h2"]))
        cat_rows = [[c, str(n)] for c, n in stats["top_categories"]]
        ctable = Table(cat_rows, colWidths=[60 * mm, 20 * mm])
        ctable.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), styles["cjk"], 9),
            ("TEXTCOLOR", (0, 0), (-1, -1), C_INK),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, C_LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        flow.append(ctable)

    if stats["top_tags"]:
        flow.append(Paragraph("熱門關鍵字 (top 15)", styles["h2"]))
        flow.append(Paragraph(
            "  ·  ".join(f"{t} ({n})" for t, n in stats["top_tags"]),
            styles["body"],
        ))

    flow.append(Spacer(1, 10 * mm))
    note = (
        "本報告由 Happy Vision 自動生成。花費以 Google Gemini 公開定價計算，"
        "實際帳單以 Google Cloud Billing 為準。TWD 為匯率 ~32 的概估。"
    )
    flow.append(Paragraph(note, styles["small"]))
    return flow


def _kv(label: str, value: str, styles: dict):
    return Table(
        [[Paragraph(label, styles["kicker"])], [Paragraph(value, styles["title"])]],
        colWidths=[85 * mm],
    )


def _detail_table(results: list[dict], styles: dict) -> list:
    flow = [PageBreak(), Paragraph("逐張明細", styles["h2"])]

    # Sort by timestamp desc (newest first)
    ordered = sorted(
        results,
        key=lambda r: r.get("updated_at") or "",
        reverse=True,
    )

    header = ["檔名", "分類", "氛圍", "Tokens", "USD", "時間"]
    col_widths = [55 * mm, 25 * mm, 22 * mm, 22 * mm, 18 * mm, 28 * mm]

    # Chunk into pages to avoid giant tables
    chunk_size = 28
    chunks = [ordered[i:i + chunk_size] for i in range(0, len(ordered), chunk_size)] or [[]]

    for i, chunk in enumerate(chunks):
        rows = [header]
        for r in chunk:
            u = r.get("_usage") or {}
            name = Path(r.get("file_path", "")).name or "—"
            if len(name) > 32:
                name = name[:29] + "…"
            total_tokens = u.get("total_tokens") or (
                (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
            )
            ts = (r.get("updated_at") or "")[:16].replace("T", " ")
            cost = u.get("cost_usd") or 0.0
            rows.append([
                name,
                r.get("category", "—") or "—",
                r.get("mood", "—") or "—",
                _fmt_n(total_tokens) if total_tokens else "—",
                _fmt_usd(cost) if cost else "—",
                ts or "—",
            ])
        t = Table(rows, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), styles["cjk"], 8),
            ("FONT", (0, 1), (0, -1), "Courier", 7),  # mono for filenames
            ("FONT", (3, 1), (4, -1), "Courier", 8),  # mono for numbers
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 0), (-1, 0), C_ACCENT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_SUBTLE]),
            ("ALIGN", (3, 0), (4, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, C_LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(t)
        if i < len(chunks) - 1:
            flow.append(PageBreak())
    return flow


def generate_report(results: list[dict], folder: str | None = None) -> bytes:
    """Render a PDF report from a list of analyzed results. Returns PDF bytes.

    Each `result` is expected to have the shape stored by ResultStore:
    the analysis fields (title, description, keywords, category, mood, ...)
    plus `file_path`, `updated_at`, and optionally a `_usage` sub-dict
    (from get_result_with_usage / get_results_for_folder).
    """
    styles = _build_styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="Happy Vision Report",
        author="Happy Vision",
    )
    story: list = []
    story.extend(_summary_page(results, styles, folder))
    if results:
        story.extend(_detail_table(results, styles))
    doc.build(story)
    return buf.getvalue()

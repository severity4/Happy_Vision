"""modules/cost_estimator.py — Project cost + ETA for a batch-mode submission.

Two strategies, best-first:
  1. Historical average: if the user has ≥20 completed results in the DB for
     the same model + image_max_size, use the observed average tokens/photo.
     That's the most accurate number because it reflects their actual prompt
     + scene complexity.
  2. Heuristic fallback: if we have no history, estimate from image_max_size.
     Gemini 2.5 flash-lite charges ~258 tokens per 768x768 tile plus the
     prompt. This tracks their published pricing doc within ~15%.

Output is always "savings vs realtime" as well so the confirmation modal can
say "Batch $2.25 vs realtime $4.50 — save $2.25".
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from modules.gemini_batch import MAX_PHOTOS_PER_BATCH
from modules.gemini_vision import MODEL_MAP
from modules.logger import setup_logger
from modules.metadata_writer import ExiftoolBatch, read_rating_batch
from modules.pipeline import scan_photos
from modules.pricing import PRICING, calc_cost_usd, USD_TO_TWD_APPROX
from modules.result_store import ResultStore

log = setup_logger("cost_estimator")

# Heuristic tokens/photo per image_max_size, measured from the v0.9.0 e2e
# run (3 real photos at 1024px gave 472 input tokens average). These grow
# roughly linearly with tile count; each 2x in long edge ~ 4x tiles.
HEURISTIC_INPUT_TOKENS = {
    1024: 500,   # ~2-4 tiles + ~200 prompt tokens
    1536: 1000,
    2048: 2000,
    3072: 3500,
}
HEURISTIC_OUTPUT_TOKENS = 300  # analyze_photo typical completion size


@dataclass
class CostEstimate:
    photo_count: int          # photos that will actually be sent
    scanned_count: int        # files scanned before filtering
    skipped_processed: int    # already in DB with status='completed'
    skipped_rating: int       # below min_rating threshold
    chunks: int               # number of batch jobs (3000 per chunk)
    model: str                # "lite" / "flash"
    image_max_size: int
    avg_input_tokens: int
    avg_output_tokens: int
    source: str               # "history" | "heuristic"
    sample_size: int          # N rows used if source=="history"
    realtime_cost_usd: float
    batch_cost_usd: float
    savings_usd: float
    twd_per_batch: float      # approximation for display
    hours_slo: int            # 24h typical

    def to_dict(self) -> dict:
        return {
            "photo_count": self.photo_count,
            "scanned_count": self.scanned_count,
            "skipped_processed": self.skipped_processed,
            "skipped_rating": self.skipped_rating,
            "chunks": self.chunks,
            "model": self.model,
            "model_name": MODEL_MAP.get(self.model, self.model),
            "image_max_size": self.image_max_size,
            "avg_input_tokens": self.avg_input_tokens,
            "avg_output_tokens": self.avg_output_tokens,
            "source": self.source,
            "sample_size": self.sample_size,
            "realtime_cost_usd": round(self.realtime_cost_usd, 4),
            "batch_cost_usd": round(self.batch_cost_usd, 4),
            "savings_usd": round(self.savings_usd, 4),
            "twd_per_batch": round(self.twd_per_batch, 2),
            "hours_slo": self.hours_slo,
        }


def _historical_avg(
    store: ResultStore, model: str, image_max_size: int, min_rows: int = 20,
) -> tuple[int, int, int] | None:
    """Return (avg_input, avg_output, n) for recent rows matching model.

    We filter by model only — image_max_size isn't persisted per-row, so we
    can't match it exactly. Good enough in practice: most users don't keep
    switching size mid-library."""
    model_name = MODEL_MAP.get(model, model)
    rows = store.conn.execute(
        """SELECT input_tokens, output_tokens FROM results
           WHERE status = 'completed'
             AND model = ?
             AND input_tokens IS NOT NULL AND input_tokens > 0
           ORDER BY updated_at DESC
           LIMIT 200""",
        (model_name,),
    ).fetchall()
    if len(rows) < min_rows:
        return None
    total_in = sum(r["input_tokens"] for r in rows)
    total_out = sum((r["output_tokens"] or 0) for r in rows)
    n = len(rows)
    return (total_in // n, total_out // n, n)


def _count_after_filters(
    store: ResultStore,
    photos: list[str],
    skip_existing: bool,
    min_rating: int,
) -> tuple[int, int, int]:
    """Returns (photos_to_send, skipped_processed, skipped_rating).

    Rating check is best-effort: if exiftool is missing or we can't open a
    shared batch, we don't estimate the rating filter — just return 0 there
    and let the actual submit apply it. Over-estimating cost is fine; under-
    estimating would burn user budget."""
    remaining = list(photos)
    skipped_processed = 0
    if skip_existing:
        filtered = []
        for p in remaining:
            if store.is_processed(p):
                skipped_processed += 1
            else:
                filtered.append(p)
        remaining = filtered

    skipped_rating = 0
    if min_rating > 0 and remaining:
        try:
            batch = ExiftoolBatch()
            try:
                kept = []
                for p in remaining:
                    try:
                        rating = read_rating_batch(batch, p)
                    except Exception:  # noqa: BLE001
                        rating = min_rating  # on read failure, pass through
                    if rating < min_rating:
                        skipped_rating += 1
                    else:
                        kept.append(p)
                remaining = kept
            finally:
                batch.close()
        except Exception:  # noqa: BLE001
            log.warning("Rating pre-filter unavailable for estimate; skipping check")

    return len(remaining), skipped_processed, skipped_rating


def estimate_batch_cost(
    folder: str,
    model: str = "lite",
    image_max_size: int = 3072,
    skip_existing: bool = True,
    min_rating: int = 0,
    store: ResultStore | None = None,
) -> CostEstimate:
    """Full cost projection for submitting `folder` as a batch run."""
    owned_store = store is None
    if owned_store:
        store = ResultStore()
    try:
        photos = scan_photos(folder)
        photo_count, skipped_processed, skipped_rating = _count_after_filters(
            store, photos, skip_existing, min_rating,
        )

        hist = _historical_avg(store, model, image_max_size)
        if hist is not None:
            avg_in, avg_out, sample = hist
            source = "history"
        else:
            avg_in = HEURISTIC_INPUT_TOKENS.get(
                image_max_size,
                HEURISTIC_INPUT_TOKENS[3072],
            )
            avg_out = HEURISTIC_OUTPUT_TOKENS
            sample = 0
            source = "heuristic"

        total_in = avg_in * photo_count
        total_out = avg_out * photo_count
        realtime = calc_cost_usd(MODEL_MAP.get(model, model), total_in, total_out, batch=False)
        batch = calc_cost_usd(MODEL_MAP.get(model, model), total_in, total_out, batch=True)
        savings = realtime - batch

        chunks = max(1, (photo_count + MAX_PHOTOS_PER_BATCH - 1) // MAX_PHOTOS_PER_BATCH) if photo_count > 0 else 0

        return CostEstimate(
            photo_count=photo_count,
            scanned_count=len(photos),
            skipped_processed=skipped_processed,
            skipped_rating=skipped_rating,
            chunks=chunks,
            model=model,
            image_max_size=image_max_size,
            avg_input_tokens=avg_in,
            avg_output_tokens=avg_out,
            source=source,
            sample_size=sample,
            realtime_cost_usd=realtime,
            batch_cost_usd=batch,
            savings_usd=savings,
            twd_per_batch=batch * USD_TO_TWD_APPROX,
            hours_slo=24,
        )
    finally:
        if owned_store:
            store.close()


__all__ = ["CostEstimate", "estimate_batch_cost"]

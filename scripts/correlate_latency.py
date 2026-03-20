"""Cross-system latency correlation between poc-deepgram and notifications-spike.

Matches utterances from a Deepgram session (ground-truth audio timing) with
Genesys transcription events (notification arrival timing) to compute the true
end-to-end latency of the Genesys transcription pipeline.

Usage:
    uv run python -m scripts.correlate_latency \
        --deepgram ../poc-deepgram/results/nova-3_2026-03-17T18-36-27Z.json \
        --genesys conversation_events/02ecc434-d65b-491e-9555-59aa3949d046.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import statistics
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.55
MAX_TEMPORAL_DISTANCE_S = 60.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DeepgramEvent:
    transcript: str
    audio_wall_clock_start: float
    audio_wall_clock_end: float


@dataclass
class GenesysEvent:
    transcript: str
    received_at: float
    channel: str
    utterance_id: str = ""
    offset_ms: int = 0
    duration_ms: int = 0


@dataclass
class CorrelationResult:
    deepgram_transcript: str
    genesys_transcript: str
    audio_wall_clock_end: float
    genesys_received_at: float
    true_latency_s: float
    true_latency_ms: float
    channel: str
    similarity: float = 0.0


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_deepgram_session(path: Path) -> list[DeepgramEvent]:
    """Load final transcripts from a poc-deepgram session JSON file.

    Skips events where audio_wall_clock_end is None (no stream_start_time).
    """
    data = json.loads(path.read_text())
    events: list[DeepgramEvent] = []
    for t in data.get("transcripts", []):
        wc_start = t.get("audio_wall_clock_start")
        wc_end = t.get("audio_wall_clock_end")
        if wc_end is None:
            continue
        events.append(
            DeepgramEvent(
                transcript=t["transcript"],
                audio_wall_clock_start=wc_start if wc_start is not None else 0.0,
                audio_wall_clock_end=wc_end,
            )
        )
    return events


def load_genesys_conversation(path: Path) -> list[GenesysEvent]:
    """Load final transcript events from a notifications-spike JSONL file."""
    events: list[GenesysEvent] = []
    for line in path.read_text().strip().splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        transcript_data = raw.get("transcript", {})
        if not transcript_data.get("isFinal", False):
            continue
        alts = transcript_data.get("alternatives", [])
        if not alts:
            continue
        alt = alts[0]
        events.append(
            GenesysEvent(
                transcript=alt.get("transcript", ""),
                received_at=raw["receivedAt"],
                channel=transcript_data.get("channel", "UNKNOWN"),
                utterance_id=transcript_data.get("utteranceId", ""),
                offset_ms=alt.get("offsetMs", 0),
                duration_ms=alt.get("durationMs", 0),
            )
        )
    return events


def load_eventbridge_conversation(path: Path) -> list[GenesysEvent]:
    """Load final transcript events from an EventBridge SQS consumer JSONL file.

    Handles the EB format where ``transcripts`` is a top-level array (one SQS
    message can carry multiple utterances).  Deduplicates by ``utteranceId``
    because SQS standard queues provide at-least-once delivery.
    """
    events: list[GenesysEvent] = []
    seen: set[str] = set()
    for line in path.read_text().strip().splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        received_at = raw["receivedAt"]
        for transcript_data in raw.get("transcripts", []):
            if not transcript_data.get("isFinal", False):
                continue
            utterance_id = transcript_data.get("utteranceId", "")
            if utterance_id and utterance_id in seen:
                continue
            if utterance_id:
                seen.add(utterance_id)
            alts = transcript_data.get("alternatives", [])
            if not alts:
                continue
            alt = alts[0]
            events.append(
                GenesysEvent(
                    transcript=alt.get("transcript", ""),
                    received_at=received_at,
                    channel=transcript_data.get("channel", "UNKNOWN"),
                    utterance_id=utterance_id,
                    offset_ms=alt.get("offsetMs", 0),
                    duration_ms=alt.get("durationMs", 0),
                )
            )
    return events


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def match_utterances(
    deepgram_events: list[DeepgramEvent],
    genesys_events: list[GenesysEvent],
    similarity_threshold: float = SIMILARITY_THRESHOLD,
    max_temporal_distance_s: float = MAX_TEMPORAL_DISTANCE_S,
) -> list[tuple[DeepgramEvent, GenesysEvent, float]]:
    """Match Genesys events to Deepgram events by text similarity.

    Returns list of (deepgram_event, genesys_event, similarity_score) tuples.
    Each Genesys event is matched to at most one Deepgram event (best match).
    Each Deepgram event can be consumed by at most one Genesys event.
    """
    if not deepgram_events or not genesys_events:
        return []

    # Build candidate pairs scored by similarity + temporal proximity
    candidates: list[tuple[float, int, int, float]] = []
    for gi, gn in enumerate(genesys_events):
        for di, dg in enumerate(deepgram_events):
            sim = _similarity(dg.transcript, gn.transcript)
            if sim < similarity_threshold:
                continue
            temporal_dist = abs(gn.received_at - dg.audio_wall_clock_end)
            if temporal_dist > max_temporal_distance_s:
                continue
            candidates.append((sim, gi, di, temporal_dist))

    # Sort by similarity descending, then temporal distance ascending
    candidates.sort(key=lambda c: (-c[0], c[3]))

    matched_dg: set[int] = set()
    matched_gn: set[int] = set()
    matches: list[tuple[DeepgramEvent, GenesysEvent, float]] = []

    for sim, gi, di, _ in candidates:
        if gi in matched_gn or di in matched_dg:
            continue
        matches.append((deepgram_events[di], genesys_events[gi], sim))
        matched_dg.add(di)
        matched_gn.add(gi)

    # Sort matches by audio time for consistent ordering
    matches.sort(key=lambda m: m[0].audio_wall_clock_end)
    return matches


# ---------------------------------------------------------------------------
# Latency computation
# ---------------------------------------------------------------------------


def compute_latency(
    dg: DeepgramEvent,
    gn: GenesysEvent,
    similarity: float = 0.0,
) -> CorrelationResult:
    """Compute true end-to-end latency for a matched pair."""
    latency_s = gn.received_at - dg.audio_wall_clock_end
    return CorrelationResult(
        deepgram_transcript=dg.transcript,
        genesys_transcript=gn.transcript,
        audio_wall_clock_end=dg.audio_wall_clock_end,
        genesys_received_at=gn.received_at,
        true_latency_s=latency_s,
        true_latency_ms=latency_s * 1000,
        channel=gn.channel,
        similarity=similarity,
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def correlate(
    deepgram_path: Path,
    genesys_path: Path,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> list[CorrelationResult]:
    """Load data from both systems, match utterances, and compute latencies."""
    dg_events = load_deepgram_session(deepgram_path)
    gn_events = load_genesys_conversation(genesys_path)

    logger.info(
        "Loaded %d Deepgram events, %d Genesys events",
        len(dg_events),
        len(gn_events),
    )

    matches = match_utterances(
        dg_events, gn_events, similarity_threshold=similarity_threshold
    )
    logger.info("Matched %d utterance pairs", len(matches))

    results = [compute_latency(dg, gn, sim) for dg, gn, sim in matches]
    return results


def correlate_eventbridge(
    deepgram_path: Path,
    eventbridge_path: Path,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> list[CorrelationResult]:
    """Correlate Deepgram ground truth with EventBridge SQS consumer data."""
    dg_events = load_deepgram_session(deepgram_path)
    eb_events = load_eventbridge_conversation(eventbridge_path)

    logger.info(
        "Loaded %d Deepgram events, %d EventBridge events",
        len(dg_events),
        len(eb_events),
    )

    matches = match_utterances(
        dg_events, eb_events, similarity_threshold=similarity_threshold
    )
    logger.info("Matched %d utterance pairs", len(matches))

    results = [compute_latency(dg, gn, sim) for dg, gn, sim in matches]
    return results


def print_summary(results: list[CorrelationResult]) -> None:
    """Print human-readable summary of correlation results."""
    if not results:
        print("No matched utterances found.")
        return

    latencies_ms = [r.true_latency_ms for r in results]
    print(f"\n{'='*60}")
    print(f"Cross-System Latency Analysis")
    print(f"{'='*60}")
    print(f"Matched pairs:  {len(results)}")
    print(f"Mean latency:   {statistics.mean(latencies_ms):.0f} ms")
    print(f"Median latency: {statistics.median(latencies_ms):.0f} ms")
    print(f"Min latency:    {min(latencies_ms):.0f} ms")
    print(f"Max latency:    {max(latencies_ms):.0f} ms")
    if len(latencies_ms) >= 2:
        stdev = statistics.stdev(latencies_ms)
        print(f"Std deviation:  {stdev:.0f} ms")
        quantiles = statistics.quantiles(latencies_ms, n=100)
        if len(quantiles) > 94:
            print(f"p95 latency:    {quantiles[94]:.0f} ms")
        if len(quantiles) > 98:
            print(f"p99 latency:    {quantiles[98]:.0f} ms")

    # By channel
    channels = {r.channel for r in results}
    if len(channels) > 1:
        print(f"\nBy channel:")
        for ch in sorted(channels):
            ch_latencies = [r.true_latency_ms for r in results if r.channel == ch]
            print(
                f"  {ch}: median={statistics.median(ch_latencies):.0f}ms "
                f"(n={len(ch_latencies)})"
            )

    print(f"\n{'─'*60}")
    print(f"{'Latency':>10}  {'Sim':>5}  {'Ch':>8}  Transcript")
    print(f"{'─'*60}")
    for r in results:
        trunc = r.genesys_transcript[:45] + ("..." if len(r.genesys_transcript) > 45 else "")
        print(f"{r.true_latency_ms:>8.0f}ms  {r.similarity:>5.2f}  {r.channel:>8}  {trunc}")
    print()


def export_csv(results: list[CorrelationResult], output_path: Path) -> None:
    """Export correlation results to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "deepgram_transcript",
            "genesys_transcript",
            "audio_wall_clock_end",
            "genesys_received_at",
            "true_latency_s",
            "true_latency_ms",
            "channel",
            "similarity",
        ])
        for r in results:
            writer.writerow([
                r.deepgram_transcript,
                r.genesys_transcript,
                r.audio_wall_clock_end,
                r.genesys_received_at,
                round(r.true_latency_s, 4),
                round(r.true_latency_ms, 1),
                r.channel,
                round(r.similarity, 3),
            ])
    logger.info("Results exported to %s", output_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Correlate poc-deepgram and notifications-spike data to measure true Genesys transcription latency.",
    )
    parser.add_argument(
        "--deepgram",
        type=Path,
        required=True,
        help="Path to poc-deepgram session JSON file",
    )
    parser.add_argument(
        "--genesys",
        type=Path,
        required=True,
        help="Path to notifications-spike conversation JSONL file",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=SIMILARITY_THRESHOLD,
        help=f"Minimum text similarity for matching (default: {SIMILARITY_THRESHOLD})",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Path to export CSV results (default: analysis_results/cross_system/correlation.csv)",
    )

    args = parser.parse_args()

    if not args.deepgram.exists():
        print(f"Error: Deepgram session file not found: {args.deepgram}", file=sys.stderr)
        sys.exit(1)
    if not args.genesys.exists():
        print(f"Error: Genesys conversation file not found: {args.genesys}", file=sys.stderr)
        sys.exit(1)

    results = correlate(args.deepgram, args.genesys, similarity_threshold=args.threshold)
    print_summary(results)

    csv_path = args.csv or Path("analysis_results/cross_system/correlation.csv")
    export_csv(results, csv_path)


if __name__ == "__main__":
    main()

# Word Error Rate (WER) Analysis

WER analysis is a standard method for evaluating how well a speech-to-text (STT) system performs by comparing its output to a correct reference transcription.

---

## What is WER?

WER measures the percentage of words that were incorrectly predicted by the STT system.

**Formula:**

```
WER = (S + D + I) / N
```

Where:

- **S (Substitutions)**: Wrong word predicted instead of the correct one
- **D (Deletions)**: Words missing from the STT output
- **I (Insertions)**: Extra words added by the STT system
- **N**: Total number of words in the reference (ground truth)

---

## Simple Example

**Reference (ground truth):**

> "I love machine learning"

**STT output:**

> "I like machine learning"

**Analysis:**

- "love" → "like" = 1 substitution
- No deletions or insertions
- Total reference words = 4

```
WER = (1 + 0 + 0) / 4 = 25%
```

---

## Types of Errors

### 1. Substitution (S)

Wrong word predicted.

```
Reference: "the cat sat"
Hypothesis: "the bat sat"
                 ↑ substitution
```

### 2. Deletion (D)

Word missing from the output.

```
Reference: "I am happy"
Hypothesis: "I happy"
               ↑ deletion
```

### 3. Insertion (I)

Extra word added to the output.

```
Reference: "I am happy"
Hypothesis: "I am very happy"
                  ↑ insertion
```

---

## Why WER Analysis Matters

WER is more than a single number — it helps diagnose STT system behavior:

- **High substitutions** → model confuses similar-sounding words
- **High deletions** → model misses speech (possibly low volume or noise)
- **High insertions** → model hallucinating or over-predicting

---

## Deeper WER Analysis (Beyond the Score)

In real projects, analysis typically goes beyond the top-level WER score:

### Error Breakdown

Percentage of substitutions vs deletions vs insertions helps pinpoint model weaknesses. For example, if deletions dominate, the model is likely missing speech segments rather than confusing words.

### Per-Category Analysis

Errors grouped by word type reveal systematic weaknesses:

- **Numbers** (e.g., "twenty" vs "20")
- **Names / entities** (proper nouns the model has not seen)
- **Accents or dialects** (regional pronunciation differences)

### Alignment Inspection

Dynamic programming (Levenshtein distance) aligns reference and hypothesis word-by-word:

```
REF: I   love  machine  learning
HYP: I   like  machine  learning
          ↑
       substitution
```

This reveals exactly which words were affected and how.

---

## Limitations of WER

WER is useful but imperfect:

- **Treats all errors equally** — a minor word substitution counts the same as a critical error
- **Sensitive to formatting** — punctuation, casing, and number formatting affect the score
- **Does not capture meaning** — "I love dogs" vs "I like dogs" counts as an error, but meaning is close
- **Can exceed 100%** — if insertions are very high, WER can be greater than 100%

---

## Related Metrics

| Metric | Description |
|--------|-------------|
| **CER** (Character Error Rate) | Better for languages without clear word boundaries |
| **MER** (Match Error Rate) | Alternative normalization that bounds the metric to 0-1 |
| **Semantic metrics** | Measure meaning similarity rather than exact word match (emerging trend) |

---

## When to Use WER

WER is best for:

- Benchmarking STT models against each other
- Comparing model versions over time
- Tracking improvements after fine-tuning or retraining

---

## Interpreting WER (Reference Benchmarks)

A WER below 10% is generally considered production-quality for most speech-to-text systems, while values above 20% indicate significant transcription errors requiring correction.

### General Industry Ranges

| WER Range | Interpretation | Typical Scenario |
|-----------|---------------|-----------------|
| < 5% | Excellent (near-human) | Clean audio, dictation |
| 5–10% | Very good | Voice assistants, controlled environments |
| 10–20% | Good | Meetings, general transcription |
| 20–30% | Fair | Noisy or real-world audio |
| > 30% | Poor | Hard to understand |

Source: [1]

### Call Center / Conversational Audio

| WER | Interpretation |
|-----|---------------|
| < 10% | Excellent (rare in production) |
| 10–15% | Acceptable (typical real-world baseline) |
| > 15% | Needs improvement |

Source: [2]

### Environment-Based Expectations

- **2–5% WER** → achievable with studio-quality audio
- **10–15% WER** → realistic for meetings / phone calls
- **20%+ WER** → common in noisy or accented speech

Source: [3]

### Practical Rule of Thumb

- **< 10%** → production-ready for most use cases
- **10–20%** → usable but needs human correction
- **> 20%** → poor UX unless heavily post-processed

Sources: [4][5]

### Important Interpretation Notes

- WER is **context-dependent**: audio quality, accents, and domain vocabulary all affect results [1]
- Lower WER = better accuracy, but not all errors are equally important — meaning may still be preserved despite errors [3]

---

## Methodology Decisions (This Project)

The following architectural decisions were made for the WER analysis in `notebooks/transcription_accuracy-04-WER-ANALYSIS.ipynb`. Each addresses a specific data quality or measurement issue discovered during analysis.

### Decision 1: Number Normalization (`num2words`)

**Problem:** Digit sequences ("40") and their word equivalents ("forty") are semantically identical but WER counts them as substitution errors. This inflates WER when the SRT ground truth uses digits and the STT outputs words (or vice versa).

**Solution:** Override the `_normalize()` function in the notebook to convert all standalone digit sequences to their word equivalents using `num2words` before WER computation. Applied to both reference and hypothesis.

```python
text = re.sub(r"\b\d+\b", lambda m: num2words(int(m.group())), text)
text = text.replace("-", " ")  # "twenty-one" → "twenty one"
```

**Why override instead of modifying `correlate_latency.py`:** The shared `_normalize()` in `scripts/correlate_latency.py` is used by notebook-03 for utterance matching. Adding number normalization there could change match results and break existing analysis. The override is scoped to the WER notebook only.

**Impact:** ~3 fewer substitution errors across all sessions (minor, confirming number mismatches were not a major error source).

### Decision 2: Salesforce Test Call Intro Stripping

**Problem:** Every test recording begins with a "Salesforce test call" phrase spoken as part of the Genesys test call setup. This phrase has no corresponding text in the SRT ground truth, creating spurious insertion errors. Deepgram transcribes it as "say less force test call"; r2d2 produces inconsistent variants.

**Solution:** Before WER computation, check the first few words of each hypothesis for known intro variants and strip them:

```python
INTRO_VARIANTS = [
    "salesforce test call",
    "say less force test call",
    "sales force test call",
    "say less for test call",
    "say less force",
]
```

The function allows up to 2 leading junk words before the intro to handle cases where the STT produces a few spurious words before the recognizable phrase.

**Impact:** Stripped from all 5 Deepgram sessions. r2d2 variants were not consistently recognized by exact match and are instead handled by the sliding alignment (Decision 3).

### Decision 3: Sliding Reference Alignment

**Problem:** Recordings may start after the movie monologue has already begun. The SRT reference contains words from the beginning of the monologue that were never present in the audio. This creates artificial deletion streaks at the start of the alignment, inflating both deletion counts and overall WER.

**Alternatives considered:**
1. **Forced timestamp trimming** — Requires word-level timestamps from all STT engines; r2d2 may not provide them in a compatible format. Rejected: engine-dependent.
2. **Anchor-based alignment** — Find the first shared distinctive word and trim both texts. Already built keyword anchors per movie. Rejected: fails if the anchor word itself is mistranscribed; requires per-movie configuration.
3. **Sliding reference alignment** — Try `WER(ref[offset:], hyp)` for offsets 0 through 30% of reference length. Pick the offset that minimizes WER. **Selected:** fully automatic, no per-movie configuration, handles any offset size, naturally returns offset=0 when no trimming needed.
4. **Ignore leading errors** — Skip errors until the first correct match. Rejected: unprincipled, hides real issues.

**Solution:** After stripping the intro from the hypothesis, slide the reference start forward word by word up to 30% of reference length. Pick the offset that produces the minimum WER.

```python
def find_best_ref_offset(ref_text, hyp_text, max_offset_pct=0.3):
    for offset in range(1, max_offset + 1):
        w = jiwer.wer(" ".join(ref_words[offset:]), hyp_text)
        if w < best_wer:
            best_wer, best_offset = w, offset
    return best_offset, best_wer, raw_wer
```

**Impact:** Mockingbird Deepgram improved from 28.6% → 21.7% (20-word offset, confirming recording started ~20 words into the monologue). Overall weighted WER improved by ~2% across all channels.

### Decision 4: Per-Channel Alignment Offsets

**Problem:** Should all three channels (Deepgram, Notifications, EventBridge) use the same reference offset for a given session, or should each find its own optimal offset?

**Solution:** Per-channel offsets. Rationale: each STT engine processes audio differently — Deepgram may transcribe slightly more or fewer words at the start than r2d2. The sliding algorithm naturally finds the best offset per channel. If the audio truly started at the same point, the offsets will converge to similar values.

**Observation:** Offsets do differ across channels for the same session (e.g., Mockingbird: Deepgram=20, Notif/EB=17), confirming that per-channel alignment is appropriate.

### Decision 5: Ground Truth Quality

**Initial state:** SRT files were auto-generated YouTube subtitles (4 of 5 movies). These contained their own transcription errors, which inflated WER for all channels equally. One movie (Mockingbird) had a manually-verified SRT. Maleficent had no SRT at all.

**Resolution (March 26, 2026):** All 6 ground truth files have been manually reviewed and corrected:
- **Cyrano** (`Cyrano.en.auto.srt`) — manually reviewed and corrected
- **Glengarry** (`Glengarry.en.auto.srt`) — manually reviewed and corrected
- **Mockingbird** (`Mockingbird.en.manual.srt`) — already manually verified
- **Shawshank** (`Shawshank.en.auto.srt`) — manually reviewed and corrected
- **Iron Man** (`IronMan.en.auto.srt`) — manually reviewed and corrected
- **Maleficent** (`Maleficent.en.manual.srt`) — manually transcribed from audio (plain text format, parsed via fallback)

All files now have `srt_type: "manual"` in the notebook configuration. WER values from the next execution reflect accuracy against verified ground truth.

**Note:** File names retain `.auto.srt` for the original 4 files (renaming would break git history). The `srt_type` field in the notebook is the authoritative indicator of verification status.

#### SRT Review Process

Each SRT file was reviewed by listening to the corresponding test call audio and comparing against the transcript text word-by-word. The following corrections were applied:

1. **Incorrect words** — Auto-generated captions that misheard the speaker were replaced with the correct word (e.g., YouTube auto-caption errors from the original upload).
2. **Censored profanity** — YouTube auto-captions censor profanity with `[__]`. These were replaced with the actual spoken word (e.g., `[__]` → the word as spoken). STT engines transcribe spoken profanity, so the reference must match.
3. **Formatted numbers and currency** — Expressions like `$80,000` were rewritten as spoken words (e.g., "eighty thousand dollars"). The normalization pipeline handles standalone digits via `num2words`, but formatted numbers with commas, dollar signs, or decimals do not normalize correctly (e.g., `$80,000` → `eightyzero` due to comma splitting the digit sequence). Writing numbers as spoken words avoids this.
4. **Missing words** — Words dropped by YouTube's auto-captioning were added back.
5. **Maleficent** — Transcribed from scratch by listening to the audio, since no YouTube SRT existed. Written as plain text (no SRT timestamps), parsed by the `parse_srt()` plain-text fallback.

The audio source for review was the Deepgram recording of each test call (`poc-deepgram/results/nova-3_*.json` session audio), which captures the same audio stream heard by all three STT channels.

---

## References

### Benchmark Sources

| # | Source | Description |
|---|--------|-------------|
| 1 | https://vatis.tech/blog/what-is-wer-in-speech-to-text-everything-you-need-to-know-2025 | WER industry ranges and interpretation guide |
| 2 | https://www.futurebeeai.com/knowledge-hub/word-error-rate-benchmark-call-center-speech-recognition | Call center speech recognition WER benchmarks |
| 3 | https://voicecontrol.chat/blog/posts/word-error-rate-wer-explained-the-metric-behind-speech-recognition-accuracy | Environment-based WER expectations |
| 4 | https://summarizemeeting.com/en/faq/what-is-word-error-rate | Practical WER interpretation |
| 5 | https://www.tencentcloud.com/techpedia/120367 | WER fundamentals and production thresholds |

### Core Definitions and Theory

| # | Source | Description |
|---|--------|-------------|
| 6 | https://en.wikipedia.org/wiki/Word_error_rate | Wikipedia — WER definition, formula, and examples |
| 7 | https://en.wikipedia.org/wiki/Speech_recognition | Wikipedia — Speech recognition overview (includes WER context) |

### Academic and Standards Sources

| # | Source | Description |
|---|--------|-------------|
| 8 | https://www.nist.gov/itl/iad/mig/speech-recognition | NIST — Origin of standard ASR evaluation practices including WER |
| 9 | https://web.stanford.edu/~jurafsky/slp3/ | Stanford — Speech and Language Processing (Jurafsky & Martin), ASR evaluation sections |

### Cloud Provider Documentation

| # | Source | Description |
|---|--------|-------------|
| 10 | https://cloud.google.com/speech-to-text/docs/accuracy | Google Cloud — Speech-to-Text accuracy concepts, WER factors |
| 11 | https://docs.aws.amazon.com/transcribe/latest/dg/how-it-works.html | AWS Transcribe — Accuracy and evaluation considerations |
| 12 | https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-custom-speech-test-and-train | Microsoft Azure — Speech Service evaluation workflows using WER |

### Open Source Tooling

| # | Source | Description |
|---|--------|-------------|
| 13 | https://huggingface.co/metrics/wer | Hugging Face — WER metric implementation and examples |
| 14 | https://kaldi-asr.org/doc/ | Kaldi — ASR toolkit using WER as primary evaluation metric |
| 15 | https://speechbrain.github.io/ | SpeechBrain — Includes WER computation utilities |

### Evaluation and Benchmarking

| # | Source | Description |
|---|--------|-------------|
| 16 | https://paperswithcode.com/task/speech-recognition | Papers With Code — WER benchmarks across models and datasets |
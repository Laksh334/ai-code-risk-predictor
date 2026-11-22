"""B1 - Commit-message NLP: signs of developer frustration and rushed work.

Adds per-commit columns (all start with "msg_") to the commits table. The pipeline then
averages them per file over the file's history before each snapshot date, e.g.
msg_frustrated = share of the file's commits whose message sounds frustrated.

Signals
  msg_frustrated      lexicon: "stupid", "again", "finally", "wtf", "ugh", "!!" ...
  msg_rushed          lexicon: "wip", "quick fix", "hack", "workaround", "for now", "forgot" ...
  msg_short           message of 3 words or fewer ("fix", "oops", "more changes")
  msg_revert          undoing an earlier commit
  msg_words           message length
  msg_late_night      committed 22:00-05:59 in the author's own timezone
  msg_weekend         committed on Saturday/Sunday (author's timezone)
  msg_hf_frustration  HuggingFace emotion model: P(anger) + P(disgust), 0..1
                      (cached per commit; NaN if transformers isn't installed)

    from ml.nlp import add_message_features
    commits = add_message_features(commits)
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd
from pipeline.paths import DATA_DIR

log = logging.getLogger(__name__)

HF_MODEL = "j-hartmann/emotion-english-distilroberta-base"
HF_CACHE = DATA_DIR / "cache" / "nlp_hf_emotion.pkl"

_FRUSTRATION = re.compile(
    r"\b(stupid|dumb|silly|idiot\w*|annoy\w*|ugh+|argh+|grr+|damn\w*|crap\w*|wtf|hate|sigh"
    r"|ugly|horrible|terrible|awful|nasty|insane|crazy|ridiculous|sucks?|mess(y)?|hell"
    r"|frustrat\w*|finally|again|seriously|still\s+(broken|failing|not)|once more)\b"
    r"|!{2,}",
    re.IGNORECASE,
)
_RUSHED = re.compile(
    r"\b(wip|tmp|temp|temporary|quick(\s*fix)?|hack\w*|kludge|workaround|for now|todo|fixme|xxx"
    r"|forgot\w*|oops|whoops|another (try|attempt)|try again|hopefully|should work|not sure"
    r"|maybe|trying|attempt( to)?)\b",
    re.IGNORECASE,
)
_REVERT = re.compile(r"^\s*revert\b|this reverts commit", re.IGNORECASE)
_NOISE = re.compile(r"https?://\S+|#\d+|\b[0-9a-f]{7,40}\b|signed-off-by:.*", re.IGNORECASE)

MSG_COLS = [
    "msg_frustrated", "msg_rushed", "msg_short", "msg_revert", "msg_words",
    "msg_late_night", "msg_weekend", "msg_hf_frustration",
]


def clean_message(message: str) -> str:
    """Drop URLs, issue numbers, commit hashes and sign-offs: noise for word matching."""
    return _NOISE.sub(" ", message).strip()


def lexicon_features(messages: pd.Series) -> pd.DataFrame:
    clean = messages.fillna("").map(clean_message)
    subject = clean.str.split("\n", n=1).str[0]
    words = subject.str.split().str.len().fillna(0).astype(int)
    return pd.DataFrame({
        "msg_frustrated": clean.map(lambda s: int(bool(_FRUSTRATION.search(s)))),
        "msg_rushed": clean.map(lambda s: int(bool(_RUSHED.search(s)))),
        "msg_short": (words <= 3).astype(int),
        "msg_revert": messages.fillna("").map(lambda s: int(bool(_REVERT.search(s)))),
        "msg_words": clean.str.split().str.len().fillna(0).astype(int),
    }, index=messages.index)


def timing_features(dates: pd.Series, tz_offset_min: pd.Series) -> pd.DataFrame:
    """Local time of the commit. Unknown/broken timezone -> UTC is used."""
    local = dates + pd.to_timedelta(tz_offset_min.fillna(0), unit="m")
    hour = local.dt.hour
    return pd.DataFrame({
        "msg_late_night": ((hour >= 22) | (hour < 6)).astype(int),
        "msg_weekend": (local.dt.dayofweek >= 5).astype(int),
    }, index=dates.index)


# ---------------------------------------------------------------------------
# HuggingFace emotion model (optional, cached)
# ---------------------------------------------------------------------------

_classifier = None


def _load_classifier():
    global _classifier
    if _classifier is None:
        from transformers import pipeline  # imported lazily: heavy, and optional

        _classifier = pipeline("text-classification", model=HF_MODEL, top_k=None,
                               truncation=True, max_length=128, device=-1)
    return _classifier


def hf_frustration(messages: pd.Series, shas: pd.Series, cache_file: Path = HF_CACHE) -> pd.Series:
    """P(anger) + P(disgust) per commit. Each commit is only ever scored once (cache by sha)."""
    cache: dict[str, float] = pd.read_pickle(cache_file) if cache_file.exists() else {}
    todo = {s: m for s, m in zip(shas, messages) if s not in cache}
    if todo:
        try:
            clf = _load_classifier()
        except Exception as e:  # transformers/torch missing or model download failed
            log.warning("HuggingFace model unavailable (%s) - msg_hf_frustration left empty", e)
            return pd.Series(np.nan, index=messages.index)
        texts = [clean_message(m)[:500] or "." for m in todo.values()]
        log.info("Scoring %d new commit messages with %s ...", len(texts), HF_MODEL)
        for sha, scores in zip(todo, clf(texts, batch_size=32)):
            probs = {s["label"]: s["score"] for s in scores}
            cache[sha] = round(probs.get("anger", 0) + probs.get("disgust", 0), 4)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        pd.to_pickle(cache, cache_file)
    return shas.map(cache).astype(float)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_message_features(commits: pd.DataFrame, use_hf: bool | None = None) -> pd.DataFrame:
    """Return the commits table with the msg_* columns added (computed once per commit).

    `use_hf` default comes from RISK_USE_HF (1/0). Small servers (e.g. 512 MB RAM) can turn
    the ~1 GB emotion model off: msg_hf_frustration is then unknown and the model fills it in."""
    if use_hf is None:
        use_hf = os.environ.get("RISK_USE_HF", "1") != "0"
    if commits.empty:
        return commits.assign(**{c: pd.Series(dtype=float) for c in MSG_COLS})
    per_commit = commits.drop_duplicates("commit_sha").set_index("commit_sha")
    feats = pd.concat([
        lexicon_features(per_commit["commit_message"]),
        timing_features(per_commit["commit_date"], per_commit["tz_offset_min"]),
    ], axis=1)
    feats["msg_hf_frustration"] = (
        hf_frustration(per_commit["commit_message"], per_commit.index.to_series())
        if use_hf else np.nan
    )
    out = commits.drop(columns=[c for c in MSG_COLS if c in commits.columns])
    return out.merge(feats, left_on="commit_sha", right_index=True, how="left")

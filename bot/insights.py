# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/bot/insights.py
"""
Activity pattern analysis, insights generation, and next-activity prediction.
"""

import math
import logging
from datetime import datetime, timedelta, date
from collections import defaultdict
from typing import List, Dict, Tuple, Optional, Any

logger = logging.getLogger(__name__)


# ── Core Pattern Analysis ────────────────────────────────────────────────────

def analyze_patterns(entries: List[dict]) -> dict:
    """
    Computes all pattern data from a list of activity entries.
    Returns a dict with keys: time_profiles, transitions, gap_patterns,
    dow_profiles, consistency, category_hours.
    """
    if not entries:
        return _empty_patterns()

    # Category hours
    cat_hours: Dict[str, float] = defaultdict(float)
    for e in entries:
        cat = e.get("activity_type", "Other") or "Other"
        cat_hours[cat] += e.get("duration_hrs", 0)

    # Time-of-day profiles per activity type
    type_start_hours: Dict[str, List[float]] = defaultdict(list)
    type_durations: Dict[str, List[float]] = defaultdict(list)
    for e in entries:
        start = e.get("start")
        if start:
            t = e.get("activity_type", "Other") or "Other"
            type_start_hours[t].append(start.hour + start.minute / 60)
            type_durations[t].append(e.get("duration_hrs", 0))

    time_profiles = {}
    for t, hours in type_start_hours.items():
        avg_h = _circular_mean(hours)
        std_h = _circular_std(hours, avg_h)
        time_profiles[t] = {
            "avg_start": avg_h,
            "std_start": std_h,
            "avg_duration": sum(type_durations[t]) / len(type_durations[t]) if type_durations[t] else 0,
            "count": len(hours),
        }

    # Transition matrix (what follows what)
    transitions: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for i in range(len(entries) - 1):
        curr = entries[i].get("activity_type", "Other") or "Other"
        nxt = entries[i + 1].get("activity_type", "Other") or "Other"
        transitions[curr][nxt] += 1

    # Normalize to probabilities
    trans_probs: Dict[str, List[Tuple[str, float]]] = {}
    for curr, nexts in transitions.items():
        total = sum(nexts.values())
        trans_probs[curr] = sorted(
            [(nxt, count / total) for nxt, count in nexts.items()],
            key=lambda x: -x[1],
        )

    # Gap patterns (within same day)
    gaps = []
    for i in range(len(entries) - 1):
        end = entries[i].get("end")
        next_start = entries[i + 1].get("start")
        if end and next_start and end.date() == next_start.date():
            gap_hrs = (next_start - end).total_seconds() / 3600
            if gap_hrs >= 0.5:
                gaps.append({
                    "time": end.hour + end.minute / 60,
                    "duration": gap_hrs,
                })

    gap_patterns = {}
    if gaps:
        avg_gap_time = _circular_mean([g["time"] for g in gaps])
        avg_gap_dur = sum(g["duration"] for g in gaps) / len(gaps)
        gap_patterns = {
            "avg_start": avg_gap_time,
            "avg_duration": avg_gap_dur,
            "count": len(gaps),
        }

    # Day-of-week profiles
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_hours: Dict[int, float] = defaultdict(float)
    dow_counts: Dict[int, int] = defaultdict(int)
    for e in entries:
        start = e.get("start")
        if start:
            dow = start.weekday()
            dow_hours[dow] += e.get("duration_hrs", 0)
            dow_counts[dow] += 1

    dow_profiles = {}
    for d in range(7):
        dow_profiles[day_names[d]] = {
            "hours": dow_hours[d],
            "entries": dow_counts[d],
        }

    # Consistency metrics
    daily_hours: Dict[date, float] = defaultdict(float)
    for e in entries:
        start = e.get("start")
        if start:
            daily_hours[start.date()] += e.get("duration_hrs", 0)

    tracked_days = len(daily_hours)
    total_days = 30  # default window
    avg_daily = sum(daily_hours.values()) / tracked_days if tracked_days else 0
    high_days = sum(1 for h in daily_hours.values() if h >= 16)
    low_days = sum(1 for h in daily_hours.values() if h < 8)

    consistency = {
        "tracked_days": tracked_days,
        "total_days": total_days,
        "ratio": tracked_days / total_days if total_days else 0,
        "avg_daily_hrs": avg_daily,
        "high_days": high_days,
        "low_days": low_days,
    }

    return {
        "time_profiles": time_profiles,
        "transitions": trans_probs,
        "gap_patterns": gap_patterns,
        "dow_profiles": dow_profiles,
        "consistency": consistency,
        "category_hours": dict(cat_hours),
    }


# ── Prediction Engine ────────────────────────────────────────────────────────

def predict_next_activity(
    patterns: dict,
    last_type: Optional[str] = None,
    current_time: Optional[datetime] = None,
) -> List[Tuple[str, float, str]]:
    """
    Predicts the next activity based on:
    1. Transition probability from last activity
    2. Time-of-day probability for each activity type
    Returns list of (activity_type, confidence, reason).
    """
    if not patterns or not patterns.get("time_profiles"):
        return []

    current_hour = (current_time.hour + current_time.minute / 60) if current_time else 12.0

    scores: Dict[str, float] = defaultdict(float)
    reasons: Dict[str, str] = {}

    # Score from transitions
    if last_type and last_type in patterns.get("transitions", {}):
        for nxt, prob in patterns["transitions"][last_type]:
            scores[nxt] += prob * 0.5  # 50% weight from transitions
            reasons[nxt] = f"usually follows {last_type}"

    # Score from time-of-day fit
    for t, profile in patterns.get("time_profiles", {}).items():
        avg = profile["avg_start"]
        std = max(profile["std_start"], 1.0)  # min 1h std
        # Gaussian probability: how likely is this activity at current time?
        time_prob = _gaussian_pdf(current_hour, avg, std)
        scores[t] += time_prob * 0.3  # 30% weight from time

    # Score from frequency
    total_entries = sum(p["count"] for p in patterns.get("time_profiles", {}).values())
    for t, profile in patterns.get("time_profiles", {}).items():
        freq = profile["count"] / total_entries if total_entries else 0
        scores[t] += freq * 0.2  # 20% weight from frequency

    # Normalize and sort
    total_score = sum(scores.values())
    if not total_score:
        return []

    results = []
    for t, score in sorted(scores.items(), key=lambda x: -x[1]):
        confidence = score / total_score
        reason = reasons.get(t, _time_reason(t, current_hour, patterns))
        results.append((t, confidence, reason))

    return results[:5]


def _time_reason(activity: str, hour: float, patterns: dict) -> str:
    """Generates a human-readable reason based on time-of-day."""
    profile = patterns.get("time_profiles", {}).get(activity, {})
    avg = profile.get("avg_start", 12)
    if abs(hour - avg) < 2:
        return f"typical time for {activity}"
    return f"you sometimes do {activity} around now"


# ── Insights Rendering ───────────────────────────────────────────────────────

def render_insights_section(patterns: dict, predictions: List[Tuple[str, float, str]]) -> str:
    """Renders the insights + predictions section as HTML for the dashboard."""
    from bot.formatting import bold, code, fmt_dur, fmt_time, fmt_pct

    lines = []

    # ── Insights ──
    lines.append(bold("Insights"))
    lines.append("")

    # Most consistent activity (lowest start time std)
    time_profiles = patterns.get("time_profiles", {})
    if time_profiles:
        most_consistent = min(
            ((t, p) for t, p in time_profiles.items() if p["count"] >= 3),
            key=lambda x: x[1]["std_start"],
            default=None,
        )
        if most_consistent:
            t, p = most_consistent
            avg_h = p["avg_start"]
            lines.append(f"  Most consistent: <b>{t}</b> (usually ~{code(_fmt_hour(avg_h))})")

        # Average session durations
        dur_parts = []
        for t, p in sorted(time_profiles.items(), key=lambda x: -x[1]["avg_duration"] * x[1]["count"]):
            if p["count"] >= 2:
                dur_parts.append(f"{t} {fmt_dur(p['avg_duration'])}")
        if dur_parts:
            lines.append(f"  Avg session: {' | '.join(dur_parts[:4])}")

    # Gap patterns
    gap = patterns.get("gap_patterns", {})
    if gap:
        lines.append(f"  Typical break: ~{code(_fmt_hour(gap['avg_start']))}, avg {fmt_dur(gap['avg_duration'])}")

    # Day-of-week insights
    dow = patterns.get("dow_profiles", {})
    if dow:
        peak = max(dow.items(), key=lambda x: x[1]["hours"])
        light = min(dow.items(), key=lambda x: x[1]["hours"] if x[1]["hours"] > 0 else float('inf'))
        if peak[1]["hours"] > 0:
            lines.append(f"  Peak: {code(peak[0])} ({fmt_dur(peak[1]['hours'])}) | Lightest: {code(light[0])} ({fmt_dur(light[1]['hours'])})")

    # Consistency
    cons = patterns.get("consistency", {})
    if cons:
        lines.append(f"  Tracking: {cons['tracked_days']}/{cons['total_days']} days ({fmt_pct(cons['tracked_days'], cons['total_days'])}) | Avg {fmt_dur(cons['avg_daily_hrs'])}/day")

    # ── Predictions ──
    if predictions:
        lines.append("")
        lines.append(bold("Predictions"))
        lines.append("")
        for i, (activity, confidence, reason) in enumerate(predictions[:3], 1):
            bar = _confidence_bar(confidence)
            lines.append(f"  {i}. <b>{activity}</b> {bar} {reason}")

    return "\n".join(lines)


def _confidence_bar(confidence: float) -> str:
    """Visual confidence bar: ██████░░░░ 62%"""
    filled = int(confidence * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"<code>{bar}</code> {int(confidence * 100)}%"


def _fmt_hour(hour_float: float) -> str:
    """Converts hour float (e.g. 14.67) to '14:40'."""
    h = int(hour_float)
    m = int((hour_float - h) * 60)
    return f"{h:02d}:{m:02d}"


# ── Math Helpers ─────────────────────────────────────────────────────────────

def _circular_mean(angles: List[float]) -> float:
    """Mean of angles on a 24h circle (handles wrap-around)."""
    if not angles:
        return 0
    sin_sum = sum(math.sin(2 * math.pi * a / 24) for a in angles)
    cos_sum = sum(math.cos(2 * math.pi * a / 24) for a in angles)
    mean_angle = math.atan2(sin_sum, cos_sum) * 24 / (2 * math.pi)
    return mean_angle % 24


def _circular_std(angles: List[float], mean: float) -> float:
    """Standard deviation on a 24h circle."""
    if len(angles) < 2:
        return 0
    diffs = []
    for a in angles:
        d = abs(a - mean)
        if d > 12:
            d = 24 - d
        diffs.append(d)
    return (sum(d ** 2 for d in diffs) / len(diffs)) ** 0.5


def _gaussian_pdf(x: float, mu: float, sigma: float) -> float:
    """Gaussian probability density."""
    if sigma <= 0:
        return 0
    return math.exp(-0.5 * ((x - mu) / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))


def _empty_patterns() -> dict:
    return {
        "time_profiles": {},
        "transitions": {},
        "gap_patterns": {},
        "dow_profiles": {},
        "consistency": {},
        "category_hours": {},
    }


# ── Smart Suggestions ────────────────────────────────────────────────────────

def generate_smart_suggestions(
    entries_24h: List[dict],
    patterns: dict,
    now: datetime,
) -> List[str]:
    """
    Generates contextual suggestions based on current state.
    Returns list of HTML-formatted suggestion strings.
    """
    from bot.formatting import bold, code, fmt_time, fmt_dur

    suggestions = []

    if not entries_24h:
        suggestions.append(f"{bold('No entries in last 24h')} — start logging your day!")
        return suggestions

    # Check for untracked gaps
    gaps = []
    for i in range(len(entries_24h) - 1):
        end = entries_24h[i].get("end")
        next_start = entries_24h[i + 1].get("start")
        if end and next_start:
            gap_hrs = (next_start - end).total_seconds() / 3600
            if gap_hrs >= 1:
                gaps.append({
                    "start": end,
                    "end": next_start,
                    "hours": gap_hrs,
                })

    if gaps:
        largest = max(gaps, key=lambda g: g["hours"])
        suggestions.append(
            f"{bold('Gap detected')}: {fmt_time(largest['start'])}-{fmt_time(largest['end'])} ({fmt_dur(largest['hours'])}) — fill it?"
        )

    # Check if last entry is still ongoing (no end time or end time in future)
    last = entries_24h[-1]
    last_end = last.get("end")
    if last_end and last_end > now:
        suggestions.append(
            f"{bold('Ongoing')}: {last.get('activity_type', '?')} started at {fmt_time(last.get('start', now))}"
        )
    elif last_end and (now - last_end).total_seconds() / 3600 > 2:
        gap_since_last = (now - last_end).total_seconds() / 3600
        suggestions.append(
            f"{bold('Untracked')} since {fmt_time(last_end)} ({fmt_dur(gap_since_last)} ago) — what have you been doing?"
        )

    # Check for duplicates
    seen = set()
    for e in entries_24h:
        key = (e.get("start"), e.get("end"), e.get("activity_type"))
        if key in seen:
            suggestions.append(f"{bold('Duplicate entry')} detected — consider removing one")
            break
        seen.add(key)

    # Check for overlaps
    for i in range(len(entries_24h)):
        for j in range(i + 1, len(entries_24h)):
            s1, e1 = entries_24h[i].get("start"), entries_24h[i].get("end")
            s2, e2 = entries_24h[j].get("start"), entries_24h[j].get("end")
            if s1 and e1 and s2 and e2 and s1 < e2 and s2 < e1:
                suggestions.append(f"{bold('Overlapping entries')} — {entries_24h[i].get('activity_type')} and {entries_24h[j].get('activity_type')}")
                break
        else:
            continue
        break

    # Time-based suggestions
    hour = now.hour
    if 5 <= hour < 9 and not any(e.get("activity_type") == "Meditation" for e in entries_24h[-3:]):
        suggestions.append(f"{bold('Morning routine')} — time for meditation?")
    if 21 <= hour or hour < 2:
        suggestions.append(f"{bold('Late night')} — don't forget to log sleep before bed")

    # Tracking consistency
    total_tracked = sum(e.get("duration_hrs", 0) for e in entries_24h)
    if total_tracked < 12:
        suggestions.append(f"{bold('Low tracking')}: only {fmt_dur(total_tracked)} logged in 24h — try to log more consistently")

    return suggestions[:5]  # Limit to 5 suggestions

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
from pathlib import Path

# Root projektu (backend_embedded/)
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# -------------------------
# Pomocnicze funkcje
# -------------------------

def qualitative_phrase(z, neg_un=None, neg_ov=None):
    """Return a natural phrase describing a z-score deviation."""
    if z is None:
        return ""
    if z >= 1.0:
        return neg_ov
    elif z <= -1.0:
        return neg_un
    else:
        return ""

def join_phrases(*phrases, sep=", "):
    """Join non-empty phrases gracefully, avoiding dangling commas."""
    parts = [p.strip() for p in phrases if p and p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return sep.join(parts[:-1]) + " and " + parts[-1]


def is_supported_metric_block(name, data, excluded_keys):
    """Return True when a metrics_summary block should participate in text/debug generation."""
    if not isinstance(data, dict):
        return False

    if name in excluded_keys:
        return False

    if (
        ("arm_stability" in name or "elbow_stability" in name)
        and data.get("expected_frac", 1.0) == 0
    ):
        return False

    return True


def iter_z_mean_metrics(metrics_summary, excluded_keys):
    """Yield (group_name, fragment_name, signed_z_score) for eligible z_mean_* metrics."""
    for key, value in metrics_summary.items():
        if not is_supported_metric_block(key, value, excluded_keys):
            continue

        for subk, subv in value.items():
            if isinstance(subv, (int, float)) and subk.startswith("z_mean_"):
                yield key, subk, float(subv)


def format_top_info_entry(group_name, fragment_name, z_score):
    """Serialize debug info with both the group label and the exact z-score fragment."""
    return f"{group_name}_{fragment_name}: {z_score:.3f}"


def describe_arm_stability(name, data):
    """Handle arm_stability and arm_stability_x/y."""
    if data.get("expected_frac", 1.0) == 0:
        return ""

    t, a = data.get("z_mean_timing", 0), data.get("z_mean_angle", 0)

    # Determine side and spatial orientation
    if "_left" in name:
        side = "left elbow"
    elif "_right" in name:
        side = "right elbow"
    else:
        side = "elbows"

    # interpretacja przestrzenna
    if name.endswith("_x"):
        orientation = "in front of the body"
        pos_forward = True
    elif name.endswith("_y"):
        orientation = "along the torso"
        pos_forward = False
    else:
        orientation = "in stable position"
        pos_forward = None

    if side == "elbows":
        if pos_forward is True:
            angle_low = "were held too far back"
            angle_high = "were pushed too far forward"
        else:
            angle_low = "were held too low"
            angle_high = "were lifted too high"
    else:
        if pos_forward is True:
            angle_low = "was held too far back"
            angle_high = "was pushed too far forward"
        else:
            angle_low = "was held too low"
            angle_high = "was lifted too high"

    desc_t = qualitative_phrase(
        t,
        neg_un=f"moved {orientation} too early",
        neg_ov=f"moved {orientation} too late"
    )

    desc_a = qualitative_phrase(
        a,
        neg_un=angle_low,
        neg_ov=angle_high
    )

    if desc_t and desc_a:
        desc = f"The {side} {desc_t} and {desc_a}"
    elif desc_t:
        desc = f"The {side} {desc_t}"
    elif desc_a:
        desc = f"The {side} {desc_a}"
    else:
        return ""

    return desc + ". "


def describe_elbow_stability(name, data):
    if data.get("expected_frac", 1.0) == 0:
        return ""

    t, a = data.get("z_mean_timing", 0), data.get("z_mean_angle", 0)
    side = "left elbow" if "left" in name else "right elbow" if "right" in name else "elbows"

    desc_t = qualitative_phrase(
        t,
        neg_un="moved too quickly",
        neg_ov="moved too slowly"
    )
    desc_a = qualitative_phrase(
        a,
        neg_un="was kept too straight",
        neg_ov="was bent a bit too much"
    )

    if desc_t and desc_a:
        desc = f"The {side} {desc_t} and {desc_a}"
    elif desc_t:
        desc = f"The {side} {desc_t}"
    elif desc_a:
        desc = f"The {side} {desc_a}"
    else:
        # fallback debug text you had, but let's return "" instead of HOPLA
        return ""

    return desc + ". "


def describe_step(name, data, intro):
    side = "left" if "_L" in name else "right" if "_R" in name else "both"
    dur = data.get("z_mean_duration")
    length = data.get("z_mean_step_length")
    knee = data.get("z_mean_knee_angle")

    dur_text = qualitative_phrase(
        dur,
        neg_un="performed slightly too fast",
        neg_ov="performed slightly too slow",
    )
    length_text = qualitative_phrase(
        length,
        neg_un="slightly too short",
        neg_ov="a bit too long",
    )

    knee_text = qualitative_phrase(
        knee,
        neg_un="the knee was too stiff",
        neg_ov="the knee was bent too much",
    )

    main_part = join_phrases(dur_text, length_text, sep=" and ")
    if main_part:
        desc = f"{intro} with the {side} leg were {main_part}"
        if knee_text:
            desc += f", {knee_text}"
        return desc + ". "
    elif knee_text:
        intro_lc = intro.lower()
        return f"{knee_text} in {intro_lc} with the {side} leg. "
    else:
        return ""


def describe_accent(name, data):
    side = "left" if "_L" in name else "right" if "_R" in name else "both"
    dur = data.get("z_mean_duration")
    knee = data.get("z_mean_knee_angle")

    dur_text = qualitative_phrase(
        dur,
        neg_un="slightly too fast",
        neg_ov="slightly too slow",
    )
    knee_text = qualitative_phrase(
        knee,
        neg_un="the knee was too stiff",
        neg_ov="the knee was bent too much",
    )

    if dur_text and knee_text:
        desc = f"Accents with the {side} leg were {dur_text}, while {knee_text}"
    elif dur_text:
        desc = f"Accents with the {side} leg were {dur_text}"
    elif knee_text:
        # poprawiam literówę "th with the"
        desc = f"{knee_text} in accents with the {side} leg"
    else:
        return ""

    return desc + ". "


def describe_bow(data):
    dur = data.get("z_mean_duration")
    knee = data.get("z_mean_knee_angle")

    d_text = qualitative_phrase(
        dur,
        neg_un="a bit rushed",
        neg_ov="slightly too slow"
    )
    k_text = qualitative_phrase(
        knee,
        neg_un="the knees bent too shallow",
        neg_ov="the knees bent too deeply"
    )

    if d_text and k_text:
        desc = f"The bow was {d_text} and {k_text}"
    elif d_text:
        desc = f"The bow was {d_text}"
    elif k_text:
        desc = f"The bow was made with {k_text}"
    else:
        return ""

    return desc + ". "


def describe_bow_lead(name, data):
    side = "left" if "_L" in name else "right" if "_R" in name else "both"
    dur = data.get("z_mean_duration")
    knee = data.get("z_mean_knee_angle")
    arm = data.get("z_mean_arm_angle")
    length = data.get("z_mean_step_length")

    d_text = qualitative_phrase(
        dur,
        neg_un="a bit rushed",
        neg_ov="slightly too slow"
    )
    k_text = qualitative_phrase(
        knee,
        neg_un="the knee bent too shallow",
        neg_ov="the knee bent too deeply"
    )
    a_text = qualitative_phrase(
        arm,
        neg_un="the arm was held too low",
        neg_ov="the arm lifted too high"
    )
    l_text = qualitative_phrase(
        length,
        neg_un="the step was slightly too short",
        neg_ov="the step was a bit too long"
    )

    main_part = join_phrases(d_text, k_text, sep=" and ")
    if d_text and (k_text or a_text or l_text):
        extras = join_phrases(a_text, l_text, sep=", ")
        if extras:
            return f"The {side} side bow was {main_part}, while {extras}. "
        else:
            return f"The {side} side bow was {main_part}. "
    elif d_text:
        return f"The {side} side bow was {d_text}. "
    elif any([k_text, a_text, l_text]):
        details = join_phrases(k_text, a_text, l_text, sep=", ")
        return f"In the {side} side bow {details}. "
    else:
        return ""


def describe_arms_up(data):
    dur = data.get("z_mean_duration")
    arm = data.get("z_mean_arm_angle")

    d_text = qualitative_phrase(
        dur,
        neg_un="too quickly",
        neg_ov="too slowly"
    )
    a_text = qualitative_phrase(
        arm,
        neg_un="were not raised high enough",
        neg_ov="were lifted a bit too high"
    )

    if d_text and a_text:
        return f"The arms were raised {d_text}, and {a_text}. "
    elif d_text:
        return f"The arms were raised {d_text}. "
    elif a_text:
        return f"The arms {a_text}. "
    else:
        return ""


def describe_head_nod(data):
    dur = data.get("z_mean_duration")
    head = data.get("z_mean_head_angle")

    d_text = qualitative_phrase(
        dur,
        neg_un="a bit rushed",
        neg_ov="slightly too slow"
    )
    h_text = qualitative_phrase(
        head,
        neg_un="the head was tilted too little",
        neg_ov="the head was tilted too deeply"
    )

    if d_text and h_text:
        return f"The head nod was {d_text} and {h_text}. "
    elif d_text:
        return f"The head nod was {d_text}. "
    elif h_text:
        return f"The head {h_text}. "
    else:
        return ""


def describe_turn(data):
    dur = data.get("z_mean_duration")
    d_text = qualitative_phrase(
        dur,
        neg_un="too quickly",
        neg_ov="too slowly"
    )
    if not d_text:
        return ""
    return f"The turn was made {d_text}. "


def build_description_part(key, value, has_detailed_bow):
    """Return a single description sentence for a metrics_summary key."""
    if not isinstance(value, dict):
        return ""

    if key.startswith("arm_stability") and key not in ["arm_stability_x", "arm_stability_y"]:
        return describe_arm_stability(key, value)

    if key.startswith("elbow_stability") and key not in ["elbow_stability"]:
        return describe_elbow_stability(key, value)

    if key.startswith("step") and key not in [
        "step_R_accented",
        "step_L_accented",
        "step_R_accented_side",
        "step_L_accented_side",
    ]:
        return describe_step(key, value, "Steps")

    if key.endswith("accented") and key not in [
        "step_R_accented_side",
        "step_L_accented_side",
    ]:
        return describe_step(key, value, "Accented steps")

    if key.startswith("accent"):
        return describe_accent(key, value)

    if key.endswith("side"):
        return describe_step(key, value, "Steps to the side")

    if key.startswith("bow") and not has_detailed_bow:
        return describe_bow(value)

    if key.startswith("bow") and key.endswith("lead"):
        return describe_bow_lead(key, value)

    if key.startswith("arms_up"):
        return describe_arms_up(value)

    if key.startswith("head"):
        return describe_head_nod(value)

    if key.startswith("turn"):
        return describe_turn(value)

    return ""


def build_soft_description_part(key, value, has_detailed_bow, fragment_name, z_score):
    """Force a mild natural-language description from the dominant fragment when needed."""
    if not fragment_name or z_score == 0 or not isinstance(value, dict):
        return ""

    adjusted_value = dict(value)
    adjusted_value[fragment_name] = 1.001 if z_score > 0 else -1.001
    return build_description_part(key, adjusted_value, has_detailed_bow)


# -------------------------
# generator tekstu opisowego
# -------------------------

def generate_description(
    metrics_summary,
    order_score=None,
    errors_detected=None,
    *,
    z_threshold=1.0,
    error_z_threshold=1.5,
    major_order_threshold=80,
    minor_order_threshold=100,
    emit_minor_order_text=True,
    order_issue_top_k=1,
    normal_top_k=2,
):
    """
    Zwraca:
      description -> opis ruchu (1-2 największe problemy),
      order_text  -> komentarz o sekwencji,
      top_info    -> lista nazw najgorszych segmentów dla debugu
    """
    EXCLUDED_KEYS = {"bow", "arm_stability_x", "arm_stability_y", "elbow_stability"}

    # 1. zbierz max |z| dla każdego segmentu
    z_scores = {}
    top_fragments = {}
    for key, subk, subv in iter_z_mean_metrics(metrics_summary, EXCLUDED_KEYS):
        if key not in top_fragments or abs(subv) > abs(top_fragments[key][1]):
            top_fragments[key] = (subk, subv)
            z_scores[key] = abs(subv)

    filtered = {k: v for k, v in z_scores.items() if v > z_threshold}
    top_keys_all = sorted(filtered, key=lambda k: filtered[k], reverse=True)
    ranked_keys_all = sorted(z_scores, key=lambda k: z_scores[k], reverse=True)

    # sprawdzamy czy mamy osobne bow_L_lead/bow_R_lead itd.
    has_detailed_bow = any(
        key.startswith("bow_") and key != "bow"
        for key in metrics_summary.keys()
    )

    # kolejność ruchów -> wpływa na to, ile feedbacku dajemy
    order_text = ""
    if order_score is not None:
        if order_score < major_order_threshold:
            order_text = "Some parts of the sequence were out of order."
            top_keys = top_keys_all[:order_issue_top_k]
        elif emit_minor_order_text and order_score < minor_order_threshold:
            order_text = "The sequence followed the correct order with minor deviations."
            top_keys = top_keys_all[:order_issue_top_k]
        else:
            top_keys = top_keys_all[:normal_top_k]
    else:
        top_keys = top_keys_all[:normal_top_k]

    forced_parts = {}

    if errors_detected and len(errors_detected) == 1:
        described_keys = set()
        for key in top_keys:
            value = metrics_summary.get(key, {})
            part = build_description_part(key, value, has_detailed_bow)
            if not part:
                fragment = top_fragments.get(key)
                if fragment is not None:
                    part = build_soft_description_part(
                        key,
                        value,
                        has_detailed_bow,
                        fragment[0],
                        fragment[1],
                    )
            if part:
                described_keys.add(key)
                forced_parts[key] = part

        for key in ranked_keys_all:
            if key in top_keys or len(described_keys) >= normal_top_k:
                continue

            value = metrics_summary.get(key, {})
            part = build_description_part(key, value, has_detailed_bow)
            if not part:
                fragment = top_fragments.get(key)
                if fragment is not None:
                    part = build_soft_description_part(
                        key,
                        value,
                        has_detailed_bow,
                        fragment[0],
                        fragment[1],
                    )
            if not part:
                continue

            top_keys.append(key)
            described_keys.add(key)
            forced_parts[key] = part

    # jeśli nie ma żadnych mocnych odchyleń
    if not top_keys:
        return "", order_text, []

    parts = []
    for key in top_keys:
        part = forced_parts.get(key)
        if not part:
            part = build_description_part(key, metrics_summary.get(key, {}), has_detailed_bow)
        if part:
            parts.append(part)
        if len(parts) >= normal_top_k:
            break

    description_text = "".join(parts).strip()
    top_info = []
    seen_top_info = set()

    for key in top_keys:
        fragment = top_fragments.get(key)
        if fragment is None:
            continue

        entry = format_top_info_entry(key, fragment[0], fragment[1])
        if entry not in seen_top_info:
            top_info.append(entry)
            seen_top_info.add(entry)

    if errors_detected:
        error_fragment_entries = sorted(
            (
                (key, subk, subv)
                for key, subk, subv in iter_z_mean_metrics(metrics_summary, EXCLUDED_KEYS)
                if abs(subv) >= error_z_threshold
            ),
            key=lambda item: (-abs(item[2]), item[0], item[1]),
        )

        for key, subk, subv in error_fragment_entries:
            entry = format_top_info_entry(key, subk, subv)
            if entry not in seen_top_info:
                top_info.append(entry)
                seen_top_info.add(entry)

    return description_text, order_text, top_info


# -------------------------
# prompt-train target
# -------------------------

def process_file(data):
    metrics = data.get("metrics_summary", {})
    order_score = data.get("order_score", None)
    errors = data.get("errors_detected", [])
    composite_score = data.get("composite_score", None)

    instruction = (
        "You are the teacher of the polish Polonaise dance. "
        "Based on observation of movements provide a short, supportive feedback "
        "with a tip for improvement."
    )

    description, order_text, top_info = generate_description(
        metrics,
        order_score,
        errors_detected=errors,
    )
    description = description.strip()

    if description == "":
        description = "The performance was very good."
    prompt = f"{instruction} Observations: {description} {order_text}".strip()

    record = {
        "prompt": prompt,
        "composite_score": composite_score,
        "order_score": order_score,
        "labels": errors,
        "top_info": top_info
    }

    return record


# -------------------------
# batch po katalogach
# -------------------------

def process_pattern_dir(pattern_dir: Path, out_base: Path):
    """Przetwarza wszystkie pliki w pattern_dir/windows/."""
    windows_dir = pattern_dir / "windows"
    if not windows_dir.exists():
        print(f"[WARN] No windows folder in {pattern_dir}")
        return

    out_pattern_dir = out_base / pattern_dir.name
    out_pattern_dir.mkdir(parents=True, exist_ok=True)

    window_files = sorted(windows_dir.glob("*.json"))
    if not window_files:
        print(f"[WARN] No window JSONs found in {windows_dir}")
        return

    for wf in window_files:
        try:
            with open(wf, "r", encoding="utf-8") as f:
                data = json.load(f)
            sample = process_file(data)
            out_path = out_pattern_dir / f"{wf.stem}_desc.json"
            with open(out_path, "w", encoding="utf-8") as out_f:
                json.dump(sample, out_f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ERROR] {wf}: {e}")


def main():
    ap = argparse.ArgumentParser(
        description="Convert window-level JSONs into supervised-friendly prompt records."
    )

    # wejście = katalog z wygenerowanymi window_*.json
    ap.add_argument(
        "--in_dir",
        type=Path,
        default=PROJECT_ROOT / "data/json/manual/supervised/training_data_with_accent",
        help="Input base directory (pattern subdirs with windows/)"
    )

    # wyjście = gdzie chcemy wrzucać _desc.json
    ap.add_argument(
        "--out_dir",
        type=Path,
        default=PROJECT_ROOT / "data/json/manual/supervised/training_data_descriptive",
        help="Output base directory (mirrors structure of in_dir)"
    )

    args = ap.parse_args()

    pattern_dirs = [p for p in args.in_dir.iterdir() if p.is_dir()]
    if not pattern_dirs:
        print(f"[WARN] No pattern directories in {args.in_dir}")
        return

    for pd in pattern_dirs:
        print(f"[INFO] Processing pattern {pd.name}...")
        process_pattern_dir(pd, args.out_dir)

    print(f"[OK] Done. Output written to {args.out_dir}")


if __name__ == "__main__":
    main()

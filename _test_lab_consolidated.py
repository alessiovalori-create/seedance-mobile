"""Throwaway consolidated end-to-end test for the LAB vision pipeline.

Runs every image-only analysis group against a single sample image using the
currently configured model (lab_vision.ACTIVE_MODEL), prints per-group summaries
and aggregate totals, and saves full results to JSON. Delete after LAB is validated.
"""
import os
import json
import time
import traceback
from datetime import datetime

from lab_vision import analyze_image, ACTIVE_MODEL
from lab_schemas import get_image_groups

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(ROOT, "data", "generated", "assets")
RESULTS_PATH = os.path.join(ROOT, "_test_lab_consolidated_results.json")


def _find_sample_image():
    exts = (".jpg", ".jpeg", ".png")
    for root, _dirs, files in os.walk(ASSETS_DIR):
        for name in sorted(files):
            if name.lower().endswith(exts):
                return os.path.join(root, name)
    return None


def main():
    image_path = _find_sample_image()
    if not image_path:
        print(f"ERROR: no .jpg/.jpeg/.png found under {ASSETS_DIR}. Stopping.")
        return
    print(f"[image] Using: {image_path}")

    groups = get_image_groups()

    print("=== LAB Consolidated Test ===")
    print(f"Model: {ACTIVE_MODEL}")
    print(f"Image: {image_path}")
    print(f"Groups to test: {len(groups)} image-only groups")
    print("============================")

    results = []
    for group in groups:
        gid = group["id"]
        try:
            res = analyze_image(
                image_path=image_path,
                system_prompt=group["system_prompt"],
                user_prompt=group["user_prompt"],
                json_schema=group["schema"],
                schema_name=group["schema_name"],
            )
        except Exception as e:
            print(f"\n[{gid}] ❌ UNEXPECTED EXCEPTION: {type(e).__name__}: {e}")
            traceback.print_exc()
            res = {
                "success": False,
                "model_used": ACTIVE_MODEL,
                "data": None,
                "raw_content": None,
                "error": f"Unhandled exception in test loop — {type(e).__name__}: {e}",
                "usage": None,
                "cost_usd": None,
                "duration_seconds": 0.0,
                "schema_mode": None,
            }

        res["group_id"] = gid
        results.append(res)

        icon = "✅" if res.get("success") else "❌"
        usage = res.get("usage") or {}
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        cost = res.get("cost_usd") or 0.0
        dur = res.get("duration_seconds") or 0.0
        mode = res.get("schema_mode")
        print(
            f"\n[{gid}] {icon} {mode} | tokens: {pt}/{ct} | "
            f"cost: ${cost:.6f} | duration: {dur:.2f}s"
        )
        if res.get("success"):
            print(json.dumps(res.get("data"), indent=2, ensure_ascii=False))
        else:
            print(f"  error: {res.get('error')}")

    # ── Aggregate totals ──
    attempted = len(results)
    successes = sum(1 for r in results if r.get("success"))
    failures = attempted - successes
    sum_pt = sum((r.get("usage") or {}).get("prompt_tokens", 0) for r in results)
    sum_ct = sum((r.get("usage") or {}).get("completion_tokens", 0) for r in results)
    total_cost = sum((r.get("cost_usd") or 0.0) for r in results)
    avg_dur = (sum((r.get("duration_seconds") or 0.0) for r in results) / attempted) if attempted else 0.0

    mode_dist = {"strict": 0, "fallback_prompt": 0, "fallback_extract": 0, "none": 0}
    for r in results:
        m = r.get("schema_mode")
        mode_dist[m if m in mode_dist else "none"] += 1

    print("\n=== AGGREGATE TOTALS ===")
    print(f"Groups attempted:   {attempted}")
    print(f"Successes/failures: {successes} / {failures}")
    print(f"Total prompt tokens:     {sum_pt}")
    print(f"Total completion tokens: {sum_ct}")
    print(f"Total cost (USD):        ${total_cost:.6f}")
    print(f"Average duration/call:   {avg_dur:.2f}s")
    print(
        "schema_mode distribution: "
        f"strict: {mode_dist['strict']}, "
        f"fallback_prompt: {mode_dist['fallback_prompt']}, "
        f"fallback_extract: {mode_dist['fallback_extract']}"
        + (f", none: {mode_dist['none']}" if mode_dist["none"] else "")
    )

    totals = {
        "groups_attempted": attempted,
        "successes": successes,
        "failures": failures,
        "sum_prompt_tokens": sum_pt,
        "sum_completion_tokens": sum_ct,
        "total_cost_usd": total_cost,
        "avg_duration_seconds": avg_dur,
        "schema_mode_distribution": mode_dist,
    }

    payload = {
        "image_path": image_path,
        "model": ACTIVE_MODEL,
        "timestamp": datetime.now().isoformat(),
        "results": results,
        "totals": totals,
    }
    try:
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"\n[saved] Full results → {RESULTS_PATH}")
    except Exception as e:
        print(f"\n[WARNING] Could not save results JSON: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()

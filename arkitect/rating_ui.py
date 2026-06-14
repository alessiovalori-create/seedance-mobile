"""Shared rating UI: three dots below thumbnails, gallery sort."""

from __future__ import annotations

import html as _html

import streamlit as st
import streamlit.components.v1 as components

from arkitect.ratings import (
    RATING_COLORS,
    UNRATED,
    VALID_RATINGS,
    clear_rating,
    get_rating,
    get_rating_for_item,
    toggle_rating,
)

RATING_LABELS = {
    "red": "Red — poor",
    "orange": "Orange — ok",
    "green": "Green — good",
    UNRATED: "Unrated",
}

RATING_DOT_ORDER = ("green", "orange", "red")
RATING_DOT_SIZE = 14
RATING_DOT_OPACITY_IDLE = 0.38
RATING_DOT_OPACITY_ACTIVE = 1.0

_RATING_BRIDGE_JS = """
function _ratingUpdateDots(btn, rating) {
    var row = btn && btn.closest ? btn.closest('.rating-dots-row') : null;
    if (!row) return;
    var wasActive = parseFloat(btn.style.opacity || '0') >= 0.95;
    row.querySelectorAll('.rating-dot-btn').forEach(function(b) {
        if (wasActive) {
            b.style.opacity = '0.38';
        } else {
            b.style.opacity = (b.getAttribute('data-rating') === rating) ? '1' : '0.38';
        }
    });
}
function _ratingPostBridge(bridgeLabel, payload) {
    var inp = window.parent.document.querySelector(
        'input[aria-label="' + bridgeLabel + '"]'
    );
    if (!inp) return;
    var ns = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value'
    ).set;
    ns.call(inp, payload);
    inp.dispatchEvent(new Event('input', {bubbles:true}));
    inp.dispatchEvent(new Event('change', {bubbles:true}));
    try {
        inp.dispatchEvent(new InputEvent('input', {
            bubbles: true, inputType: 'insertFromPaste', data: payload
        }));
    } catch (e) {}
    try { inp.focus({preventScroll:true}); } catch (e2) {}
    try { inp.blur(); } catch (e3) {}
}
"""


def _dot_style(rating: str, current: str | None) -> str:
    color = RATING_COLORS[rating]
    opacity = RATING_DOT_OPACITY_ACTIVE if current == rating else RATING_DOT_OPACITY_IDLE
    return (
        f"background:{color};opacity:{opacity};"
        f"width:{RATING_DOT_SIZE}px;height:{RATING_DOT_SIZE}px;"
        "border-radius:50%;border:none;padding:0;cursor:pointer;"
        "transition:opacity .15s ease;"
    )


def inject_rating_styles() -> None:
    if st.session_state.get("_rating_styles_injected"):
        return
    st.session_state["_rating_styles_injected"] = True
    st.markdown(
        """
        <style>
        .rating-dots-row{
            display:flex; gap:10px; justify-content:center; align-items:center;
            padding:6px 0 4px;
        }
        .rating-dots-inline{ justify-content:flex-start !important; padding:0 !important; gap:8px !important; }
        .rating-dot-btn:hover{ opacity:0.92 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def iframe_rating_dots_html(
    item_key: str,
    current: str | None,
    *,
    fn_name: str = "postRating",
    inline: bool = False,
) -> str:
    safe_key = _html.escape(item_key, quote=True)
    row_style = (
        "display:flex;gap:8px;justify-content:flex-start;align-items:center;padding:0;"
        if inline
        else ""
    )
    row_class = "rating-dots-row rating-dots-inline" if inline else "rating-dots-row"
    row_attr = f' class="{row_class}" style="{row_style}"' if inline else f' class="{row_class}"'
    parts = [f'<div{row_attr} onclick="event.stopPropagation();">']
    for rating in RATING_DOT_ORDER:
        style = _dot_style(rating, current)
        parts.append(
            f'<button type="button" class="rating-dot-btn" data-rating="{rating}" '
            f'style="{style}" '
            f'onclick="event.stopPropagation(); _ratingUpdateDots(this, \'{rating}\'); '
            f'{fn_name}(\'{safe_key}\', \'{rating}\', this);" '
            f'title="{_html.escape(RATING_LABELS[rating])}"></button>'
        )
    parts.append("</div>")
    return "".join(parts)


def _rating_bridge_script(fn_name: str, bridge_aria_label: str) -> str:
    return f"""
    <script>
    {_RATING_BRIDGE_JS}
    function {fn_name}(itemKey, rating, btn) {{
        if (!itemKey) return;
        var payload = itemKey + '|' + rating + '|' + Date.now();
        _ratingPostBridge('{bridge_aria_label}', payload);
    }}
    </script>
    """


def render_rating_dots(
    item_key: str,
    *,
    bridge_aria_label: str,
    fn_name: str = "postRating",
    current: str | None = None,
    item: dict | None = None,
    inline: bool = False,
) -> None:
    """Three dots below thumbnail (Streamlit native cards: Gallery videos, Assets)."""
    if not item_key:
        return
    inject_rating_styles()
    if current is None:
        current = get_rating_for_item(item) if item else get_rating(item_key)
    html = (
        iframe_rating_dots_html(item_key, current, fn_name=fn_name, inline=inline)
        + _rating_bridge_script(fn_name, bridge_aria_label)
    )
    components.html(html, height=26 if inline else 34, scrolling=False)


def render_gallery_sort_mode(key: str = "gal_sort_mode") -> str:
    """Gallery view: Rating (default) or Chronological."""
    if key not in st.session_state:
        st.session_state[key] = "Rating"
    return st.radio(
        "Gallery view",
        ["Rating", "Chronological"],
        horizontal=True,
        key=key,
        label_visibility="collapsed",
    )


def process_rating_bridge(raw: str) -> bool:
    """Parse bridge payload ``item_key|rating`` and persist. Returns True if handled."""
    raw = (raw or "").strip()
    if not raw or "|" not in raw:
        return False
    item_key, rating = raw.split("|", 1)
    item_key = item_key.strip()
    rating = rating.strip().split("|")[0].strip()
    if not item_key:
        return False
    if rating == "clear":
        clear_rating(item_key)
        return True
    if rating in VALID_RATINGS:
        toggle_rating(item_key, rating)
        return True
    return False

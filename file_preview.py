"""Open and preview files from the Streamlit UI."""

import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from typing import Optional

import streamlit as st

from duplicate_core import is_image_file, is_video_file


def open_file_in_system(path: str) -> bool:
    """Open file with the OS default application."""
    if not os.path.isfile(path):
        return False
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
        return True
    except Exception as e:
        st.error(f"Could not open file: {e}")
        return False


def extract_text_preview(path: str, max_chars: int = 2500) -> Optional[str]:
    """Extract readable text for preview (documents and plain text)."""
    from duplicate_core import extract_document_text

    text = extract_document_text(path)
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        return text[:max_chars] + "…"
    return text


def render_file_preview(path: str) -> None:
    """Inline preview inside Streamlit."""
    if not os.path.isfile(path):
        st.warning("File not found.")
        return

    name = os.path.basename(path)
    _, ext = os.path.splitext(path)
    ext = ext.lower()

    st.caption(f"`{path}`")

    if is_image_file(name):
        st.image(path, width="stretch")
        return

    if is_video_file(name):
        st.video(path)
        return

    if ext == ".pdf":
        try:
            with open(path, "rb") as f:
                st.pdf(f.read(), height=480)
        except Exception:
            st.info("PDF preview unavailable. Use **Open in app** below.")
            snippet = extract_text_preview(path, 1500)
            if snippet:
                st.text_area("Extracted text (sample)", snippet, height=200)
        return

    if ext in {".txt", ".md", ".csv", ".rtf"}:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                st.text_area("Content", f.read(8000), height=280)
        except Exception as e:
            st.error(str(e))
        return

    snippet = extract_text_preview(path, 2000)
    if snippet:
        st.text_area("Extracted text (sample)", snippet, height=280)
    else:
        st.info("No text preview for this file type. Use **Open in app** to view it.")


def render_file_row(path: str, size_label: str, key_prefix: str) -> None:
    """One file line with Open + Preview actions."""
    st.write(f"**{os.path.basename(path)}** — {size_label}")
    st.caption(path)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Open in app", key=f"{key_prefix}_open", width="stretch"):
            if open_file_in_system(path):
                st.toast("Opened with default application.")
    with c2:
        preview_key = f"{key_prefix}_preview"
        if st.button("Preview here", key=f"{key_prefix}_btn", width="stretch"):
            st.session_state.active_preview = path
            st.session_state.active_preview_key = preview_key

    if st.session_state.get("active_preview") == path:
        with st.container(border=True):
            render_file_preview(path)
            if st.button("Close preview", key=f"{key_prefix}_close"):
                st.session_state.active_preview = None
                st.session_state.active_preview_key = None

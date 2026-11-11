import os
import tempfile
import time

import streamlit as st
import tkinter as tk
from tkinter import filedialog

from duplicate_core import (
    ScanConfig,
    build_thumbnails_parallel,
    export_scan_report,
    format_bytes,
    is_image_file,
    move_files_safely,
    run_scan,
)
from file_preview import render_file_row

_FRAGMENT = getattr(st, "fragment", None)
GROUPS_PER_PAGE_DEFAULT = 12
EXPAND_WARN_THRESHOLD = 80


def _fragment(fn):
    if _FRAGMENT is not None:
        return _FRAGMENT(fn)
    return fn


def pick_folder_dialog(initial_path: str | None = None) -> str:
    root = tk.Tk()
    root.withdraw()
    if initial_path and os.path.isdir(initial_path):
        folder = filedialog.askdirectory(initialdir=initial_path)
    else:
        folder = filedialog.askdirectory()
    root.destroy()
    return folder or ""


def _selection_key(kind: str, group_idx: int, file_idx: int) -> str:
    return f"{kind}:{group_idx}:{file_idx}"


def _get_selected_paths() -> list[str]:
    paths = []
    selection_paths = st.session_state.get("selection_paths", {})
    file_selections = st.session_state.get("file_selections", {})
    for key, selected in file_selections.items():
        if selected and key in selection_paths:
            paths.append(selection_paths[key])
    return sorted(set(paths))


def _reset_selections_from_groups(
    exact_groups, similar_groups, video_groups, document_groups
):
    st.session_state.file_selections = {}
    st.session_state.selection_paths = {}

    for groups, kind in (
        (exact_groups, "exact"),
        (similar_groups, "similar"),
        (video_groups, "video"),
        (document_groups, "doc"),
    ):
        for g_idx, group in enumerate(groups, start=1):
            for f_idx, file_info in enumerate(group.files):
                key = _selection_key(kind, g_idx, f_idx)
                st.session_state.file_selections[key] = f_idx != 0
                st.session_state.selection_paths[key] = file_info.path


def _is_section_expanded(section: str) -> bool:
    return bool(st.session_state.get(f"expand_{section}", False))


def _render_expand_toolbar(section: str, group_count: int) -> None:
    """Expand all / Collapse all for a results section."""
    expanded = _is_section_expanded(section)
    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        if st.button("Expand all", key=f"btn_expand_{section}"):
            if group_count > EXPAND_WARN_THRESHOLD:
                st.session_state[f"expand_{section}"] = True
                st.session_state[f"expand_warn_{section}"] = True
            else:
                st.session_state[f"expand_{section}"] = True
                st.session_state[f"expand_warn_{section}"] = False
            st.rerun()
    with c2:
        if st.button("Collapse all", key=f"btn_collapse_{section}"):
            st.session_state[f"expand_{section}"] = False
            st.session_state[f"expand_warn_{section}"] = False
            st.rerun()
    with c3:
        state = "expanded" if expanded else "collapsed"
        st.caption(f"Groups are **{state}** ({group_count} total)")

    if st.session_state.get(f"expand_warn_{section}") and expanded:
        st.warning(
            f"Showing {group_count} open groups may be slow. "
            "Use **Groups per page** in the sidebar to load fewer at a time."
        )


def _sync_multiselect(kind: str, g_idx: int, group, selected_paths: list[str]) -> None:
    for f_idx, file_info in enumerate(group.files):
        key = _selection_key(kind, g_idx, f_idx)
        st.session_state.selection_paths[key] = file_info.path
        st.session_state.file_selections[key] = file_info.path in selected_paths


def _file_details(file_info) -> str:
    details = [format_bytes(file_info.size)]
    if file_info.width and file_info.height:
        details.append(f"{file_info.width}×{file_info.height}")
    return " · ".join(details)


def _group_heading(g_idx: int, group, noun: str) -> str:
    reclaim = sum(sorted((f.size for f in group.files), reverse=True)[1:])
    heading = (
        f"Group {g_idx} — {len(group.files)} {noun} · save {format_bytes(reclaim)}"
    )
    if group.match_distance is not None:
        heading += f" · distance {group.match_distance}"
    return heading


def _render_group_files_with_preview(
    group,
    kind: str,
    g_idx: int,
    *,
    show_image_thumb: bool = False,
    thumb_map: dict | None = None,
) -> list[str]:
    """List files with Open / Preview; return multiselect selection."""
    options = [f.path for f in group.files]
    default_selection = options[1:] if len(options) > 1 else []

    for f_idx, file_info in enumerate(group.files):
        if f_idx == 0:
            st.caption("Best copy — left out of the move list")
        if show_image_thumb and is_image_file(file_info.path):
            display = (thumb_map or {}).get(file_info.path) or file_info.path
            try:
                st.image(display, width=200)
            except Exception:
                pass
        render_file_row(
            file_info.path,
            _file_details(file_info),
            f"{kind}_{g_idx}_{f_idx}",
        )

    return st.multiselect(
        "Files to move",
        options=options,
        default=default_selection,
        key=f"{kind}_ms_{g_idx}",
    )


def _render_scan_summary():
    stats = st.session_state.get("scan_stats")
    if not stats:
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Files indexed", f"{stats.total_files:,}")
    total_groups = (
        stats.exact_groups
        + stats.similar_image_groups
        + stats.similar_video_groups
        + getattr(stats, "similar_document_groups", 0)
    )
    c2.metric("Duplicate groups", f"{total_groups:,}")
    c3.metric("Recoverable space", format_bytes(stats.reclaimable_bytes))
    c4.metric("Scan time", f"{stats.duration_seconds:.1f}s")

    with st.expander("Scan breakdown", expanded=False):
        st.write(
            f"- Exact duplicate groups: **{stats.exact_groups}**\n"
            f"- Similar image groups: **{stats.similar_image_groups}**\n"
            f"- Similar document groups: **{getattr(stats, 'similar_document_groups', 0)}**\n"
            f"- Similar video groups: **{stats.similar_video_groups}**\n"
            f"- Images: **{stats.total_images:,}** · Documents: "
            f"**{getattr(stats, 'total_documents', 0):,}** · Videos: **{stats.total_videos:,}**"
        )


@_fragment
def _render_exact_groups(groups, groups_per_page: int):
    st.subheader("Exact duplicate files")

    if not groups:
        st.info("No exact duplicate files found.")
        return

    st.caption(
        f"{len(groups)} group(s), largest savings first. "
        "The best copy is first and is not selected."
    )
    _render_expand_toolbar("exact", len(groups))

    expanded = _is_section_expanded("exact")
    total_pages = max(1, (len(groups) + groups_per_page - 1) // groups_per_page)
    page = st.number_input(
        "Page",
        min_value=1,
        max_value=total_pages,
        value=min(st.session_state.get("exact_page", 1), total_pages),
        key="exact_page_input",
    )
    st.session_state.exact_page = int(page)
    start = (int(page) - 1) * groups_per_page
    page_groups = groups[start : start + groups_per_page]

    for offset, group in enumerate(page_groups):
        g_idx = start + offset + 1
        with st.expander(
            _group_heading(g_idx, group, "files"),
            expanded=expanded,
        ):
            selected = _render_group_files_with_preview(group, "exact", g_idx)
            _sync_multiselect("exact", g_idx, group, selected)


@_fragment
def _render_similar_image_group(g_idx: int, group, thumb_map: dict, expanded: bool):
    with st.expander(
        _group_heading(g_idx, group, "images"),
        expanded=expanded,
    ):
        cols = st.columns(min(len(group.files), 4))
        for f_idx, file_info in enumerate(group.files):
            col = cols[f_idx % len(cols)]
            with col:
                display_path = thumb_map.get(file_info.path) or file_info.path
                try:
                    if is_image_file(file_info.path):
                        st.image(display_path, width="stretch")
                    keep = "Best copy" if f_idx == 0 else ""
                    st.caption(
                        f"{os.path.basename(file_info.path)}\n"
                        f"{_file_details(file_info)}"
                        + (f"\n{keep}" if keep else "")
                    )
                except Exception as e:
                    st.text(f"Preview unavailable ({e})")

                render_file_row(
                    file_info.path,
                    format_bytes(file_info.size),
                    f"similar_{g_idx}_{f_idx}",
                )

                key = _selection_key("similar", g_idx, f_idx)
                st.session_state.selection_paths[key] = file_info.path
                default = st.session_state.file_selections.get(key, f_idx != 0)
                checked = st.checkbox(
                    "Move",
                    value=default,
                    key=f"similar_cb_{g_idx}_{f_idx}",
                )
                st.session_state.file_selections[key] = checked


@_fragment
def _render_similar_image_groups(groups, groups_per_page: int):
    st.subheader("Similar images (pHash + dHash)")

    if not groups:
        st.info("No similar image groups found.")
        return

    st.caption(
        "A pair is grouped only when both hashes agree, and every photo in the "
        "group matches the others. Distance is the worse of the two hashes. "
        "Exact copies are listed only under exact duplicates."
    )

    _render_expand_toolbar("similar", len(groups))
    expanded = _is_section_expanded("similar")

    total_pages = max(1, (len(groups) + groups_per_page - 1) // groups_per_page)
    page = st.number_input(
        "Page",
        min_value=1,
        max_value=total_pages,
        value=min(st.session_state.get("similar_page", 1), total_pages),
        key="similar_page_input",
    )
    st.session_state.similar_page = int(page)
    st.caption(f"{len(groups)} group(s) · page {page} of {total_pages}")

    start = (int(page) - 1) * groups_per_page
    page_groups = groups[start : start + groups_per_page]
    thumb_map = st.session_state.get("thumb_map", {})

    for offset, group in enumerate(page_groups):
        _render_similar_image_group(start + offset + 1, group, thumb_map, expanded)


@_fragment
def _render_document_groups(groups, groups_per_page: int):
    st.subheader("Similar documents (same text content)")

    if not groups:
        st.info(
            "No similar document groups found. "
            "Supports PDF, Word (.docx), and text files with extractable content."
        )
        return

    st.caption(
        "Groups files whose **extracted text** matches (e.g. same PDF/Word copy, different names). "
        "Use **Preview here** or **Open in app** to compare."
    )
    _render_expand_toolbar("doc", len(groups))
    expanded = _is_section_expanded("doc")

    total_pages = max(1, (len(groups) + groups_per_page - 1) // groups_per_page)
    page = st.number_input(
        "Page",
        min_value=1,
        max_value=total_pages,
        value=min(st.session_state.get("doc_page", 1), total_pages),
        key="doc_page_input",
    )
    st.session_state.doc_page = int(page)
    start = (int(page) - 1) * groups_per_page
    page_groups = groups[start : start + groups_per_page]

    for offset, group in enumerate(page_groups):
        g_idx = start + offset + 1
        with st.expander(
            _group_heading(g_idx, group, "documents"),
            expanded=expanded,
        ):
            selected = _render_group_files_with_preview(group, "doc", g_idx)
            _sync_multiselect("doc", g_idx, group, selected)


@_fragment
def _render_video_groups(groups, groups_per_page: int):
    st.subheader("Similar videos (keyframe hash)")

    if not groups:
        st.info("No similar video groups found.")
        return

    _render_expand_toolbar("video", len(groups))
    expanded = _is_section_expanded("video")

    total_pages = max(1, (len(groups) + groups_per_page - 1) // groups_per_page)
    page = st.number_input(
        "Page",
        min_value=1,
        max_value=total_pages,
        value=min(st.session_state.get("video_page", 1), total_pages),
        key="video_page_input",
    )
    start = (int(page) - 1) * groups_per_page
    page_groups = groups[start : start + groups_per_page]

    for offset, group in enumerate(page_groups):
        g_idx = start + offset + 1
        with st.expander(
            _group_heading(g_idx, group, "videos"),
            expanded=expanded,
        ):
            selected = _render_group_files_with_preview(group, "video", g_idx)
            _sync_multiselect("video", g_idx, group, selected)


@_fragment
def _render_results(groups_per_page: int):
    if not st.session_state.get("scan_complete"):
        return

    _render_scan_summary()
    st.divider()
    _render_exact_groups(st.session_state.exact_groups, groups_per_page)
    _render_similar_image_groups(st.session_state.similar_groups, groups_per_page)
    _render_document_groups(
        st.session_state.get("similar_document_groups", []),
        groups_per_page,
    )
    _render_video_groups(st.session_state.similar_video_groups, groups_per_page)


def _phase_label(phase: str) -> str:
    return {
        "indexing": "Indexing folder…",
        "exact": "Finding exact duplicates…",
        "images": "Analyzing similar images…",
        "videos": "Analyzing similar videos…",
        "documents": "Analyzing similar documents…",
    }.get(phase, phase)


def _collect_image_paths_from_groups(similar_groups) -> list[str]:
    paths = []
    for group in similar_groups:
        for file_info in group.files:
            paths.append(file_info.path)
    return paths


def main():
    st.set_page_config(
        page_title="Duplicate Media Finder",
        page_icon="📂",
        layout="wide",
    )

    st.title("Duplicate & Similar Media Finder")
    st.caption(
        "Find exact duplicates and similar images, videos, and documents. "
        "Groups with the most recoverable space are first. The best copy stays "
        "unchecked. Preview or open files before moving them to `_duplicates_`."
    )

    defaults = {
        "exact_groups": [],
        "similar_groups": [],
        "similar_video_groups": [],
        "similar_document_groups": [],
        "selected_folder": os.getcwd(),
        "typed_folder": os.getcwd(),
        "scan_complete": False,
        "thumb_map": {},
        "file_selections": {},
        "selection_paths": {},
        "scan_stats": None,
        "confirm_move": False,
        "similar_page": 1,
        "exact_page": 1,
        "doc_page": 1,
        "video_page": 1,
        "expand_exact": False,
        "expand_similar": False,
        "expand_doc": False,
        "expand_video": False,
        "active_preview": None,
        "active_preview_key": None,
        "report_json": None,
        "report_name": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    with st.sidebar:
        st.header("Scan settings")
        max_workers = st.slider(
            "Parallel workers",
            min_value=1,
            max_value=16,
            value=8,
            help="More workers speed up hashing on SSDs; use fewer on HDDs.",
        )
        include_exact = st.checkbox("Exact duplicates (SHA-256)", value=True)
        include_images = st.checkbox("Similar images (pHash)", value=True)
        include_documents = st.checkbox(
            "Similar documents (PDF, Word, text)",
            value=True,
            help="Compares extracted text content. Scanned PDFs without text are skipped.",
        )
        include_videos = st.checkbox("Similar videos (slower)", value=False)
        groups_per_page = st.slider(
            "Groups per page",
            min_value=5,
            max_value=50,
            value=GROUPS_PER_PAGE_DEFAULT,
            help="Pagination for all result sections (faster than expanding hundreds at once).",
        )
        st.divider()
        st.markdown(
            "**Tips**\n"
            "- The first file in each group is the best copy and is not selected.\n"
            "- Downloads, Screenshots, and WhatsApp copies are ranked lower.\n"
            "- **Preview here** shows PDF/text; **Open in app** uses Word/Adobe/etc.\n"
            "- Re-scans use `.duplicate_cache.json`."
        )

    st.markdown("### Choose folder")
    col1, col2, col3 = st.columns([3, 1, 1])

    with col1:
        st.session_state.typed_folder = st.text_input(
            "Folder path",
            value=st.session_state.typed_folder,
        )

    with col2:
        if st.button("Apply path"):
            if os.path.isdir(st.session_state.typed_folder):
                st.session_state.selected_folder = st.session_state.typed_folder
            else:
                st.error("Not a valid folder.")

    with col3:
        if st.button("Browse…"):
            chosen = pick_folder_dialog(st.session_state.selected_folder)
            if chosen:
                st.session_state.selected_folder = chosen
                st.session_state.typed_folder = chosen

    folder_path = st.session_state.selected_folder
    st.code(folder_path, language=None)

    distance_threshold = st.slider(
        "Similarity threshold for images/videos (0 = strict, 10 = loose)",
        min_value=0,
        max_value=10,
        value=5,
    )

    if st.button("Scan folder", type="primary", width="stretch"):
        if not os.path.isdir(folder_path):
            st.error("Invalid folder path.")
        else:
            st.session_state.scan_complete = False
            st.session_state.active_preview = None
            st.session_state.report_json = None
            st.session_state.report_name = None
            progress = st.progress(0.0, text="Starting…")
            status = st.empty()
            started = time.perf_counter()

            config = ScanConfig(
                root_folder=folder_path,
                distance_threshold=distance_threshold,
                include_exact=include_exact,
                include_similar_images=include_images,
                include_similar_videos=include_videos,
                include_similar_documents=include_documents,
                max_workers=max_workers,
            )

            def on_progress(phase: str, done: int, total: int):
                label = _phase_label(phase)
                if total > 0:
                    progress.progress(done / total, text=f"{label} ({done}/{total})")
                else:
                    progress.progress(0.0, text=label)
                status.caption(label)

            scan_result = run_scan(config, progress_callback=on_progress)

            st.session_state.exact_groups = scan_result.exact_groups
            st.session_state.similar_groups = scan_result.similar_groups
            st.session_state.similar_video_groups = scan_result.similar_video_groups
            st.session_state.similar_document_groups = scan_result.similar_document_groups
            st.session_state.scan_stats = scan_result.stats
            _reset_selections_from_groups(
                scan_result.exact_groups,
                scan_result.similar_groups,
                scan_result.similar_video_groups,
                scan_result.similar_document_groups,
            )

            image_paths = _collect_image_paths_from_groups(scan_result.similar_groups)
            if image_paths:
                status.caption("Building preview thumbnails…")
                st.session_state.thumb_map = build_thumbnails_parallel(
                    image_paths,
                    folder_path,
                    max_workers=max_workers,
                    progress_callback=lambda d, t: progress.progress(
                        d / max(t, 1), text=f"Thumbnails {d}/{t}"
                    ),
                )
            else:
                st.session_state.thumb_map = {}

            progress.empty()
            status.empty()
            elapsed = time.perf_counter() - started
            st.session_state.scan_complete = True
            st.success(
                f"Scan finished in {elapsed:.1f}s. "
                f"Potential space to reclaim: **{format_bytes(scan_result.stats.reclaimable_bytes)}**."
            )

    if st.session_state.scan_complete:
        _render_results(groups_per_page)

        selected = _get_selected_paths()
        st.divider()
        col_a, col_b, col_c = st.columns(3)

        with col_a:
            if st.button("Preview selection"):
                if not selected:
                    st.info("No files selected.")
                else:
                    st.write(f"**{len(selected)}** file(s) selected:")
                    for path in selected[:50]:
                        st.text(path)
                    if len(selected) > 50:
                        st.caption(f"…and {len(selected) - 50} more")

        with col_b:
            if st.session_state.scan_stats and st.button("Prepare JSON report"):
                from duplicate_core import ScanResult

                report_name = f"duplicate_report_{int(time.time())}.json"
                tmp = tempfile.gettempdir()
                report_path = os.path.join(tmp, report_name)
                export_scan_report(
                    ScanResult(
                        exact_groups=st.session_state.exact_groups,
                        similar_groups=st.session_state.similar_groups,
                        similar_video_groups=st.session_state.similar_video_groups,
                        similar_document_groups=st.session_state.similar_document_groups,
                        stats=st.session_state.scan_stats,
                    ),
                    report_path,
                    root_folder=folder_path,
                )
                with open(report_path, encoding="utf-8") as f:
                    st.session_state.report_json = f.read()
                st.session_state.report_name = report_name

            if st.session_state.get("report_json"):
                st.download_button(
                    "Download report",
                    data=st.session_state.report_json,
                    file_name=(
                        st.session_state.get("report_name")
                        or "duplicate_report.json"
                    ),
                    mime="application/json",
                )

        with col_c:
            selected_size = 0
            for path in selected:
                try:
                    selected_size += os.path.getsize(path)
                except OSError:
                    pass
            st.metric("Selected to move", f"{len(selected)} files")
            st.caption(format_bytes(selected_size))

        st.checkbox(
            "I understand selected files will be moved out of their current location",
            key="confirm_move",
        )

        if st.button(
            "Move selected files",
            type="primary",
            disabled=not selected or not st.session_state.confirm_move,
        ):
            try:
                duplicates_folder = move_files_safely(selected, folder_path)
                st.success(f"Moved {len(selected)} file(s) to `{duplicates_folder}`")
                st.session_state.scan_complete = False
                st.info("Run **Scan folder** again to refresh results.")
            except OSError as e:
                st.session_state.scan_complete = False
                st.error(f"Could not move all selected files: {e}")


if __name__ == "__main__":
    main()

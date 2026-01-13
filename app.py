import os
import streamlit as st


import tkinter as tk
from tkinter import filedialog

from duplicate_core import (
    find_exact_duplicate_groups,
    find_similar_image_groups,
    find_similar_video_groups,
    is_image_file,
    move_files_safely,
)



# -----------------------------
# Helper for displaying groups
# -----------------------------


def pick_folder_dialog(initial_path: str | None = None) -> str:
    """Open a native folder selection dialog and return the chosen path."""
    root = tk.Tk()
    root.withdraw()  # hide main Tk window

    if initial_path and os.path.isdir(initial_path):
        folder = filedialog.askdirectory(initialdir=initial_path)
    else:
        folder = filedialog.askdirectory()

    root.destroy()
    return folder or ""




def show_exact_groups(groups):
    """
    Show exact duplicate groups.
    Return a list of file paths that the user selected.
    """
    st.subheader("🧬 Exact Duplicate Files (any type)")

    if not groups:
        st.info("No exact duplicate files found.")
        return []

    st.write(f"Found **{len(groups)}** exact duplicate group(s).")

    selected_paths = []

    for idx, group in enumerate(groups, start=1):
        with st.expander(f"Group {idx} — {len(group.files)} file(s)"):
            st.write("Files in this group:")
            for file_info in group.files:
                st.write(
                    f"`{file_info.path}`  —  **{file_info.size} bytes**"
                )

            options = [f.path for f in group.files]
            default_selection = options[1:] if len(options) > 1 else []

            selected_in_group = st.multiselect(
                "Select files in this group:",
                options=options,
                default=default_selection,
                key=f"exact_group_{idx}",
            )

            selected_paths.extend(selected_in_group)

    return selected_paths

def show_similar_image_groups(groups):
    """
    Show similar image groups with thumbnails.
    Allow selecting each image via a checkbox under the picture.
    Return a list of file paths that the user selected.
    """
    st.subheader("🖼️ Similar Image Groups (pHash)")

    if not groups:
        st.info("No similar image groups found.")
        return []

    st.write(f"Found **{len(groups)}** similar image group(s).")

    selected_paths = []

    for g_idx, group in enumerate(groups, start=1):
        st.markdown(f"**Group {g_idx} — {len(group.files)} image(s)**")

        cols = st.columns(len(group.files))

        for f_idx, (col, file_info) in enumerate(zip(cols, group.files)):
            with col:
                try:
                    if is_image_file(file_info.path):
                        # Show image stretched in the column
                        st.image(file_info.path, width="stretch")
                    # Show only the filename as caption
                    filename = os.path.basename(file_info.path)
                    st.caption(filename)
                except Exception as e:
                    st.text(f"Cannot display: {file_info.path} ({e})")

                # Default: select all except the first image in each group
                default_selected = f_idx != 0

                # Checkbox to decide whether to move this image
                checked = st.checkbox(
                    "Move this",
                    value=default_selected,
                    key=f"similar_img_{g_idx}_{f_idx}",
                )

                if checked:
                    selected_paths.append(file_info.path)

        st.markdown("---")

    return selected_paths


def show_similar_video_groups(groups):
    """
    Show similar video groups (text only for now).
    Return a list of file paths that the user selected.
    """
    st.subheader("🎞️ Similar Video Groups (keyframe pHash)")

    if not groups:
        st.info("No similar video groups found.")
        return []

    st.write(f"Found **{len(groups)}** similar video group(s).")

    selected_paths = []

    for idx, group in enumerate(groups, start=1):
        with st.expander(f"Video Group {idx} — {len(group.files)} file(s)"):
            options = [f.path for f in group.files]
            default_selection = options[1:] if len(options) > 1 else []

            for file_info in group.files:
                st.write(f"`{file_info.path}`  —  **{file_info.size} bytes**")

            selected_in_group = st.multiselect(
                f"Select videos in Group {idx}:",
                options=options,
                default=default_selection,
                key=f"video_group_{idx}",
            )

            selected_paths.extend(selected_in_group)

    return selected_paths


# -----------------------------
# Main Streamlit App
# -----------------------------

def main():
    st.title("📂 Duplicate & Similar Media Finder (Prototype)")
    st.write(
        "Select a folder, then scan for **exact duplicate files** and "
        "**visually similar images**.\n\n"
        "This version is **safe**: it only moves selected files into a "
        "duplicates folder. Nothing is permanently deleted."
    )

    # --- initialise session state for groups & folder paths ---
    if "exact_groups" not in st.session_state:
        st.session_state.exact_groups = []
    if "similar_groups" not in st.session_state:
        st.session_state.similar_groups = []
    if "similar_video_groups" not in st.session_state:
        st.session_state.similar_video_groups = []
    if "selected_folder" not in st.session_state:
        st.session_state.selected_folder = os.getcwd()
    if "typed_folder" not in st.session_state:
        st.session_state.typed_folder = st.session_state.selected_folder

    # --- Row: text input (manual) + Apply + Browse button ---
    st.markdown("### 🔎 Choose folder")

    col1, col2, col3 = st.columns([3, 1, 1])

    with col1:
        st.session_state.typed_folder = st.text_input(
            "Type or paste a folder path:",
            value=st.session_state.typed_folder,
            help="You can type a folder path here, or use the Browse button.",
        )

    with col2:
        if st.button("✅ Use typed path"):
            if os.path.isdir(st.session_state.typed_folder):
                st.session_state.selected_folder = st.session_state.typed_folder
            else:
                st.error("Typed path is not a valid folder.")

    with col3:
        if st.button("📁 Browse"):
            chosen = pick_folder_dialog(st.session_state.selected_folder)
            if chosen:
                st.session_state.selected_folder = chosen

    # --- Show the folder that will actually be scanned ---
    folder_path = st.session_state.selected_folder
    st.markdown("**Current folder to scan:**")
    st.code(folder_path)

    include_videos = st.checkbox(
        "Include videos in similarity scan (slower)", value=False
    )


    # --- Similarity threshold slider ---
    distance_threshold = st.slider(
        "Similarity threshold (pHash distance)",
        min_value=0,
        max_value=10,
        value=5,
        help=(
            "Lower = stricter (only almost identical images). "
            "Higher = more tolerant (more images grouped together)."
        ),
    )

    # --- Scan button: update groups in session_state ---
    
    if st.button("🔍 Scan Folder"):
        if not os.path.isdir(folder_path):
            st.error("❌ That is not a valid folder path.")
        else:
            # Exact duplicates
            with st.spinner("🔬 Scanning for exact duplicate files..."):
                st.session_state.exact_groups = find_exact_duplicate_groups(folder_path)

            # Similar images
            with st.spinner("🖼️ Scanning for visually similar images..."):
                st.session_state.similar_groups = find_similar_image_groups(
                    folder_path, distance_threshold
                )

            # Similar videos (optional)
            if include_videos:
                with st.spinner("🎞️ Scanning for visually similar videos..."):
                    st.session_state.similar_video_groups = find_similar_video_groups(
                        folder_path,
                        num_frames=5,
                        distance_threshold=distance_threshold,
                    )
            else:
                st.session_state.similar_video_groups = []

            st.success("✅ Scan completed. Scroll down to see results.")


    # --- Always render current groups from session_state ---
    exact_selected = show_exact_groups(st.session_state.exact_groups)
    similar_selected = show_similar_image_groups(st.session_state.similar_groups)
    video_selected = show_similar_video_groups(st.session_state.similar_video_groups)


    # --- Preview selected files ---
    if st.button("📋 Show selected files (preview only)"):
        # Combine selected from images, exact files, and videos
        all_selected = sorted(
            set(exact_selected + similar_selected + video_selected)
        )

        if not all_selected:
            st.info("No files selected yet.")
        else:
            st.success(f"You have selected {len(all_selected)} file(s):")
            for path in all_selected:
                st.write(f"`{path}`")


    # --- Move selected files safely ---
    
    if st.button("🗂 Move Selected Files"):
        # Combine selected from images, exact files, and videos
        all_selected = sorted(
            set(exact_selected + similar_selected + video_selected)
        )

        if not all_selected:
            st.warning("No files selected to move.")
        else:
            base_folder = folder_path

            if not os.path.isdir(base_folder):
                st.error("Base folder is not valid. Please enter or choose a valid folder.")
            else:
                st.info(f"{len(all_selected)} files will be moved to a duplicates folder.")
                duplicates_folder = move_files_safely(all_selected, base_folder)

                if duplicates_folder:
                    st.success(
                        f"Moved {len(all_selected)} file(s) into:\n`{duplicates_folder}`\n\n"
                        "Click **Scan Folder** again to refresh the groups."
                    )
                else:
                    st.error("Could not move files due to an error.")



if __name__ == "__main__":
    main()

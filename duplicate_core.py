
import os
import hashlib
import shutil
import time
import json

from dataclasses import dataclass
from typing import List, Literal, Dict, Any

from PIL import Image
import imagehash

import numpy as np
import cv2

# -----------------------------
# Basic Config / Constants
# -----------------------------

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v"}

CACHE_FILENAME = ".duplicate_cache.json"

GroupType = Literal["exact", "similar_image", "similar_video"]


# -----------------------------
# Data Models
# -----------------------------

@dataclass
class FileInfo:
    path: str
    size: int
    created_time: float  # timestamp (seconds since epoch)


@dataclass
class DuplicateGroup:
    group_type: GroupType
    files: List[FileInfo]
    # Later we can add: representative, similarity scores, etc.


# -----------------------------
# Helper Functions
# -----------------------------

def is_image_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename)
    return ext.lower() in IMAGE_EXTENSIONS

def is_video_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename)
    return ext.lower() in VIDEO_EXTENSIONS


def get_file_info(path: str) -> FileInfo:
    """Collect basic metadata for a file."""
    stats = os.stat(path)
    return FileInfo(
        path=path,
        size=stats.st_size,
        created_time=stats.st_ctime,
    )


def hash_file(file_path: str, chunk_size: int = 1024 * 1024) -> str:
    """Calculate SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()

def get_file_hash_cached(file_path: str, cache: Dict[str, Any]) -> str:
    """
    Get SHA-256 hash of file, using cache if possible.
    Cache key is the full file path, with size + mtime validation.
    """
    stats = os.stat(file_path)
    size = stats.st_size
    mtime = stats.st_mtime

    entry = cache.get(file_path)
    if entry:
        if (
            entry.get("size") == size
            and entry.get("mtime") == mtime
            and "sha256" in entry
        ):
            return entry["sha256"]

    # Need to recompute
    h = hash_file(file_path)
    cache[file_path] = {
        **(entry or {}),
        "size": size,
        "mtime": mtime,
        "sha256": h,
    }
    return h


def get_image_phash_cached(image_path: str, cache: Dict[str, Any]):
    """
    Get perceptual hash of image, using cache if possible.
    Returns an imagehash object or None.
    """
    stats = os.stat(image_path)
    size = stats.st_size
    mtime = stats.st_mtime

    entry = cache.get(image_path)
    if entry:
        if (
            entry.get("size") == size
            and entry.get("mtime") == mtime
            and "phash" in entry
        ):
            try:
                # phash stored as hex string
                return imagehash.hex_to_hash(entry["phash"])
            except Exception as e:
                print(f"Error restoring phash from cache for {image_path}: {e}")

    # Need to recompute
    ph = compute_phash(image_path)
    if ph is not None:
        cache[image_path] = {
            **(entry or {}),
            "size": size,
            "mtime": mtime,
            "phash": str(ph),  # imagehash objects stringify to hex
        }
    return ph


def compute_phash(image_path: str):
    """Compute perceptual hash (pHash) for an image."""
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            ph = imagehash.phash(img)
            return ph
    except Exception as e:
        print(f"Skipping {image_path}: cannot open image ({e})")
        return None



def extract_video_frame_hashes(video_path: str, num_frames: int = 5):
    """
    Extract perceptual hashes from a few key frames of a video.
    Returns a list of imagehash objects.
    """
    hashes = []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Skipping {video_path}: cannot open video.")
        return hashes

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if frame_count <= 0:
        cap.release()
        return hashes

    # Choose evenly spaced frame indices
    indices = np.linspace(0, frame_count - 1, num_frames, dtype=int)

    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        # Convert OpenCV frame (BGR) to PIL Image (RGB)
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            ph = imagehash.phash(img)
            hashes.append(ph)
        except Exception as e:
            print(f"Error hashing frame from {video_path}: {e}")
            continue

    cap.release()
    return hashes

def video_hash_distance(hashes1, hashes2) -> float | None:
    """
    Compute average Hamming distance between two lists of frame hashes.
    Returns None if no valid comparison is possible.
    """
    if not hashes1 or not hashes2:
        return None

    n = min(len(hashes1), len(hashes2))
    if n == 0:
        return None

    total = 0
    for i in range(n):
        total += (hashes1[i] - hashes2[i])

    return total / n

def _cache_path_for_root(root_folder: str) -> str:
    """Return the path to the cache file for a given root folder."""
    return os.path.join(root_folder, CACHE_FILENAME)


def load_cache(root_folder: str) -> Dict[str, Any]:
    """Load cache JSON from the root folder, or return empty dict if not present."""
    cache_path = _cache_path_for_root(root_folder)
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Could not load cache file {cache_path}: {e}")
        return {}


def save_cache(root_folder: str, cache: Dict[str, Any]) -> None:
    """Save cache JSON into the root folder."""
    cache_path = _cache_path_for_root(root_folder)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception as e:
        print(f"Could not save cache file {cache_path}: {e}")



# -----------------------------
# Core Engines
# -----------------------------

def find_exact_duplicate_groups(root_folder: str) -> List[DuplicateGroup]:
    """
    Find exact duplicate files (any type) using SHA-256.
    Returns a list of DuplicateGroup objects.
    Uses cache for speed.
    """
    cache = load_cache(root_folder)
    hash_map: Dict[str, List[str]] = {}

    for folder_path, _, file_names in os.walk(root_folder):
        for file_name in file_names:
            file_path = os.path.join(folder_path, file_name)

            try:
                file_hash = get_file_hash_cached(file_path, cache)
            except (PermissionError, OSError) as e:
                print(f"Skipping {file_path}: {e}")
                continue

            hash_map.setdefault(file_hash, []).append(file_path)

    # Save updated cache
    save_cache(root_folder, cache)

    groups: List[DuplicateGroup] = []

    for paths in hash_map.values():
        if len(paths) > 1:
            files_info = [get_file_info(p) for p in paths]
            group = DuplicateGroup(group_type="exact", files=files_info)
            groups.append(group)

    return groups


def find_similar_image_groups(root_folder: str, distance_threshold: int = 5) -> List[DuplicateGroup]:
    """
    Find visually similar images using pHash.
    Returns a list of DuplicateGroup objects.
    Uses cache for speed.
    """
    cache = load_cache(root_folder)
    images_with_hashes = []  # list of (path, phash)

    # Step 1: collect images + pHash
    for folder_path, _, file_names in os.walk(root_folder):
        for file_name in file_names:
            if not is_image_file(file_name):
                continue

            file_path = os.path.join(folder_path, file_name)
            ph = get_image_phash_cached(file_path, cache)
            if ph is not None:
                images_with_hashes.append((file_path, ph))

    print(f"Total images processed for similarity: {len(images_with_hashes)}")

    # Save updated cache
    save_cache(root_folder, cache)



    # Step 2: group using greedy algorithm
    groups: List[DuplicateGroup] = []
    used_indices = set()

    for i, (path_i, hash_i) in enumerate(images_with_hashes):
        if i in used_indices:
            continue

        current_paths = [path_i]
        used_indices.add(i)

        for j in range(i + 1, len(images_with_hashes)):
            if j in used_indices:
                continue

            path_j, hash_j = images_with_hashes[j]
            distance = hash_i - hash_j

            if distance <= distance_threshold:
                current_paths.append(path_j)
                used_indices.add(j)

        if len(current_paths) > 1:
            files_info = [get_file_info(p) for p in current_paths]
            group = DuplicateGroup(group_type="similar_image", files=files_info)
            groups.append(group)

    return groups

def find_similar_video_groups(
    root_folder: str,
    num_frames: int = 5,
    distance_threshold: float = 5.0,
) -> List[DuplicateGroup]:
    """
    Find visually similar videos using keyframe pHash.
    Returns a list of DuplicateGroup objects (group_type = 'similar_video').
    """
    videos_with_hashes = []  # list of (path, [frame_hashes])

    # Step 1: collect videos + frame hashes
    for folder_path, _, file_names in os.walk(root_folder):
        for file_name in file_names:
            if not is_video_file(file_name):
                continue

            file_path = os.path.join(folder_path, file_name)
            frame_hashes = extract_video_frame_hashes(file_path, num_frames=num_frames)

            if frame_hashes:
                videos_with_hashes.append((file_path, frame_hashes))

    print(f"Total videos processed for similarity: {len(videos_with_hashes)}")

    # Step 2: group using greedy algorithm
    groups: List[DuplicateGroup] = []
    used_indices = set()

    for i, (path_i, hashes_i) in enumerate(videos_with_hashes):
        if i in used_indices:
            continue

        current_paths = [path_i]
        used_indices.add(i)

        for j in range(i + 1, len(videos_with_hashes)):
            if j in used_indices:
                continue

            path_j, hashes_j = videos_with_hashes[j]
            dist = video_hash_distance(hashes_i, hashes_j)

            if dist is not None and dist <= distance_threshold:
                current_paths.append(path_j)
                used_indices.add(j)

        if len(current_paths) > 1:
            files_info = [get_file_info(p) for p in current_paths]
            group = DuplicateGroup(group_type="similar_video", files=files_info)
            groups.append(group)

    return groups



def move_files_safely(file_paths: list[str], base_folder: str) -> str:
    """
    Moves selected files into a new '_duplicates_<timestamp>' folder 
    inside the same base folder.
    
    Returns the path of the duplicates folder created.
    """
    if not file_paths:
        return ""

    # Create duplicates folder with timestamp
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    duplicates_folder = os.path.join(base_folder, f"_duplicates_{timestamp}")
    os.makedirs(duplicates_folder, exist_ok=True)

    moved_count = 0

    for file_path in file_paths:
        try:
            if os.path.exists(file_path):
                shutil.move(file_path, duplicates_folder)
                moved_count += 1
        except Exception as e:
            print(f"Error moving {file_path}: {e}")

    print(f"Moved {moved_count} files into {duplicates_folder}")
    return duplicates_folder


import os
import hashlib
import shutil
import time
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Literal, Any, Optional, Tuple

ProgressCallback = Callable[[str, int, int], None]

from PIL import Image
import imagehash

import numpy as np
import cv2

# -----------------------------
# Basic Config / Constants
# -----------------------------

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v"}
DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".rtf",
    ".md",
    ".csv",
}
TEXT_LIKE_EXTENSIONS = {".txt", ".md", ".csv", ".rtf"}

CACHE_FILENAME = ".duplicate_cache.json"
THUMB_CACHE_DIRNAME = ".duplicate_thumbs"
IMAGE_HASH_EDGE = 64
# Copies in these folders are listed after a cleaner original.
_KEEP_LAST_FOLDERS = {"whatsapp", "downloads", "screenshots", "telegram"}

# Folders / files to skip during scans
SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules", THUMB_CACHE_DIRNAME}
SKIP_FILE_NAMES = {CACHE_FILENAME}

GroupType = Literal["exact", "similar_image", "similar_video", "similar_document"]


# -----------------------------
# Data Models
# -----------------------------

@dataclass
class FileInfo:
    path: str
    size: int
    created_time: float  # timestamp (seconds since epoch)
    width: int = 0
    height: int = 0
    modified_time: float = 0.0


@dataclass
class DuplicateGroup:
    group_type: GroupType
    files: List[FileInfo]
    match_distance: Optional[int] = None


@dataclass
class MediaIndex:
    """Single-pass inventory of a folder (avoids repeated os.walk)."""

    root_folder: str
    all_paths: List[str]
    image_paths: List[str]
    video_paths: List[str]
    document_paths: List[str]
    sizes: Dict[str, int]

    @classmethod
    def build(cls, root_folder: str) -> "MediaIndex":
        all_paths: List[str] = []
        image_paths: List[str] = []
        video_paths: List[str] = []
        document_paths: List[str] = []
        sizes: Dict[str, int] = {}

        for file_path, is_image, is_video in iter_media_files(root_folder):
            try:
                size = os.path.getsize(file_path)
            except OSError as e:
                print(f"Skipping {file_path}: {e}")
                continue
            all_paths.append(file_path)
            sizes[file_path] = size
            if is_image:
                image_paths.append(file_path)
            if is_video:
                video_paths.append(file_path)
            if is_document_file(file_path):
                document_paths.append(file_path)

        return cls(
            root_folder, all_paths, image_paths, video_paths, document_paths, sizes
        )


@dataclass
class ScanConfig:
    root_folder: str
    distance_threshold: int = 5
    include_exact: bool = True
    include_similar_images: bool = True
    include_similar_videos: bool = False
    include_similar_documents: bool = True
    video_num_frames: int = 5
    max_workers: int = 8


@dataclass
class ScanStats:
    total_files: int = 0
    total_images: int = 0
    total_videos: int = 0
    exact_groups: int = 0
    similar_image_groups: int = 0
    similar_video_groups: int = 0
    similar_document_groups: int = 0
    total_documents: int = 0
    reclaimable_bytes: int = 0
    duration_seconds: float = 0.0


@dataclass
class ScanResult:
    exact_groups: List[DuplicateGroup] = field(default_factory=list)
    similar_groups: List[DuplicateGroup] = field(default_factory=list)
    similar_video_groups: List[DuplicateGroup] = field(default_factory=list)
    similar_document_groups: List[DuplicateGroup] = field(default_factory=list)
    stats: ScanStats = field(default_factory=ScanStats)
    index: Optional[MediaIndex] = None


# -----------------------------
# Helper Functions
# -----------------------------

def is_image_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename)
    return ext.lower() in IMAGE_EXTENSIONS

def is_video_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename)
    return ext.lower() in VIDEO_EXTENSIONS


def is_document_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename)
    return ext.lower() in DOCUMENT_EXTENSIONS


def _normalize_document_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_docx_text(path: str) -> Optional[str]:
    try:
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        parts = []
        for node in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
            if node.text:
                parts.append(node.text)
        return " ".join(parts)
    except Exception as e:
        print(f"DOCX extract failed {path}: {e}")
        return None


def _extract_pdf_text(path: str) -> Optional[str]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        parts = []
        for page in reader.pages[:30]:
            text = page.extract_text()
            if text:
                parts.append(text)
        return "\n".join(parts)
    except Exception as e:
        print(f"PDF extract failed {path}: {e}")
        return None


def extract_document_text(path: str) -> Optional[str]:
    """Extract plain text from supported document types."""
    _, ext = os.path.splitext(path)
    ext = ext.lower()

    if ext in TEXT_LIKE_EXTENSIONS:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read(500_000)
        except Exception as e:
            print(f"Text read failed {path}: {e}")
            return None

    if ext == ".docx":
        return _extract_docx_text(path)

    if ext == ".pdf":
        return _extract_pdf_text(path)

    if ext == ".doc":
        print(f"Legacy .doc not supported for text extract: {path}")
        return None

    return None


def get_file_info(path: str) -> FileInfo:
    """Collect basic metadata for a file."""
    stats = os.stat(path)
    return FileInfo(
        path=path,
        size=stats.st_size,
        created_time=stats.st_ctime,
        modified_time=stats.st_mtime,
    )


def _is_lower_priority_path(path: str) -> bool:
    parts = set(path.replace("\\", "/").lower().split("/"))
    return bool(parts & _KEEP_LAST_FOLDERS)


def order_files_for_keep(files: List[FileInfo]) -> List[FileInfo]:
    """Best copy first: cleaner folder, more pixels, larger file, newer mtime."""

    def _key(info: FileInfo) -> Tuple:
        pixels = (info.width or 0) * (info.height or 0)
        modified = info.modified_time or info.created_time
        return (
            1 if _is_lower_priority_path(info.path) else 0,
            -pixels,
            -info.size,
            -modified,
            info.path.lower(),
        )

    return sorted(files, key=_key)


def _files_for_paths(paths: List[str], cache: Dict[str, Any]) -> List[FileInfo]:
    files: List[FileInfo] = []
    for path in paths:
        info = get_file_info(path)
        entry = cache.get(path) or {}
        info.width = int(entry.get("width") or 0)
        info.height = int(entry.get("height") or 0)
        if entry.get("mtime"):
            info.modified_time = float(entry["mtime"])
        files.append(info)
    return order_files_for_keep(files)


def _group_reclaim_bytes(group: DuplicateGroup) -> int:
    if len(group.files) < 2:
        return 0
    sizes = sorted((f.size for f in group.files), reverse=True)
    return sum(sizes[1:])


def _sort_groups(groups: List[DuplicateGroup]) -> List[DuplicateGroup]:
    return sorted(groups, key=_group_reclaim_bytes, reverse=True)


def _without_exact_overlaps(
    similar_groups: List[DuplicateGroup],
    exact_groups: List[DuplicateGroup],
) -> List[DuplicateGroup]:
    """Drop similar groups that contain only files already shown as exact copies."""
    exact_sets = [frozenset(f.path for f in group.files) for group in exact_groups]
    kept: List[DuplicateGroup] = []
    for group in similar_groups:
        paths = frozenset(f.path for f in group.files)
        if any(paths <= exact_set for exact_set in exact_sets):
            continue
        kept.append(group)
    return kept


def _bind_cache(
    root_folder: str, cache: Optional[Dict[str, Any]]
) -> Tuple[Dict[str, Any], bool]:
    if cache is None:
        return load_cache(root_folder), True
    return cache, False


def format_bytes(num_bytes: int) -> str:
    """Human-readable size (e.g. 1.4 GB)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    units = ["KB", "MB", "GB", "TB"]
    value = float(num_bytes)
    for unit in units:
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} PB"


def quick_fingerprint(file_path: str, chunk_size: int = 65536) -> Optional[str]:
    """
    Fast partial fingerprint (size + head/tail samples).
    Used to skip full SHA-256 when same-size files differ at edges.
    """
    try:
        stats = os.stat(file_path)
    except OSError:
        return None

    size = stats.st_size
    hasher = hashlib.md5()
    hasher.update(str(size).encode("utf-8"))

    with open(file_path, "rb") as f:
        hasher.update(f.read(chunk_size))
        if size > chunk_size * 2:
            f.seek(-chunk_size, os.SEEK_END)
            hasher.update(f.read(chunk_size))
        elif size > chunk_size:
            hasher.update(f.read())

    return hasher.hexdigest()


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


def _prepare_image(img: Image.Image) -> Image.Image:
    """Small RGB image. pHash and dHash only need a tiny thumbnail."""
    img = img.convert("RGB")
    resample = getattr(Image, "Resampling", Image).LANCZOS
    img.thumbnail((IMAGE_HASH_EDGE, IMAGE_HASH_EDGE), resample)
    return img


def compute_image_signature(image_path: str):
    """
    Return (pHash, dHash, width, height) from a downscaled image.
    Both hashes must agree later, which drops lookalike-but-different photos.
    """
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            if (img.format or "").upper() == "JPEG":
                try:
                    img.draft("RGB", (IMAGE_HASH_EDGE, IMAGE_HASH_EDGE))
                except Exception:
                    pass
            small = _prepare_image(img)
            return imagehash.phash(small), imagehash.dhash(small), width, height
    except Exception as e:
        print(f"Skipping {image_path}: cannot open image ({e})")
        return None


def compute_phash(image_path: str):
    """Compute perceptual hash (pHash) for an image."""
    signature = compute_image_signature(image_path)
    if signature is None:
        return None
    return signature[0]



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
            img = _prepare_image(Image.fromarray(frame_rgb))
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


def _should_skip_dir(dir_name: str) -> bool:
    if dir_name in SKIP_DIR_NAMES:
        return True
    return dir_name.startswith("_duplicates_")


def iter_media_files(root_folder: str):
    """
    Walk root_folder once, yielding (full_path, is_image, is_video) for each file.
    Skips cache, thumb cache, and prior duplicate-move folders.
    """
    for folder_path, dir_names, file_names in os.walk(root_folder):
        dir_names[:] = [d for d in dir_names if not _should_skip_dir(d)]

        for file_name in file_names:
            if file_name in SKIP_FILE_NAMES:
                continue

            file_path = os.path.join(folder_path, file_name)
            yield file_path, is_image_file(file_name), is_video_file(file_name)


def _thumb_cache_dir(root_folder: str) -> str:
    return os.path.join(root_folder, THUMB_CACHE_DIRNAME)


def estimate_reclaimable_bytes(groups: List[DuplicateGroup]) -> int:
    """
    Bytes you could free by keeping one file per duplicate group
    (sum of all non-largest files in each group).
    """
    total = 0
    for group in groups:
        if len(group.files) < 2:
            continue
        sizes = sorted((f.size for f in group.files), reverse=True)
        total += sum(sizes[1:])
    return total


def build_thumbnails_parallel(
    image_paths: List[str],
    root_folder: str,
    max_workers: int = 8,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, str]:
    """Build UI thumbnails in parallel."""
    thumb_map: Dict[str, str] = {}
    paths = list(dict.fromkeys(image_paths))
    total = len(paths)
    if total == 0:
        return thumb_map

    workers = min(max_workers, max(1, total))
    done = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(ensure_thumbnail, p, root_folder): p for p in paths
        }
        for future in as_completed(futures):
            done += 1
            if progress_callback:
                progress_callback(done, total)
            path = futures[future]
            thumb = future.result()
            if thumb:
                thumb_map[path] = thumb

    return thumb_map


def export_scan_report(
    result: ScanResult,
    output_path: str,
    root_folder: str = "",
) -> str:
    """Write duplicate scan results to JSON for review or backup."""
    folder = root_folder or (result.index.root_folder if result.index else "")
    payload = {
        "root_folder": folder,
        "stats": {
            "total_files": result.stats.total_files,
            "total_images": result.stats.total_images,
            "total_videos": result.stats.total_videos,
            "exact_groups": result.stats.exact_groups,
            "similar_image_groups": result.stats.similar_image_groups,
            "similar_video_groups": result.stats.similar_video_groups,
            "similar_document_groups": result.stats.similar_document_groups,
            "reclaimable_bytes": result.stats.reclaimable_bytes,
            "duration_seconds": round(result.stats.duration_seconds, 2),
        },
        "groups": [],
    }

    for label, groups in (
        ("exact", result.exact_groups),
        ("similar_image", result.similar_groups),
        ("similar_video", result.similar_video_groups),
        ("similar_document", result.similar_document_groups),
    ):
        for idx, group in enumerate(groups, start=1):
            payload["groups"].append(
                {
                    "type": label,
                    "group_index": idx,
                    "match_distance": group.match_distance,
                    "files": [
                        {
                            "path": f.path,
                            "size": f.size,
                            "size_human": format_bytes(f.size),
                            "width": f.width,
                            "height": f.height,
                        }
                        for f in group.files
                    ],
                }
            )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return output_path


def ensure_thumbnail(
    image_path: str,
    root_folder: str,
    max_size: int = 240,
) -> Optional[str]:
    """
    Return path to a small cached JPEG thumbnail for UI display.
    Thumbnails are stored under root_folder/.duplicate_thumbs/.
    """
    try:
        stats = os.stat(image_path)
    except OSError:
        return None

    cache_dir = _thumb_cache_dir(root_folder)
    os.makedirs(cache_dir, exist_ok=True)

    safe_name = hashlib.sha256(image_path.encode("utf-8")).hexdigest()[:16]
    thumb_path = os.path.join(cache_dir, f"{safe_name}.jpg")

    if os.path.isfile(thumb_path):
        try:
            thumb_stat = os.stat(thumb_path)
            if thumb_stat.st_mtime >= stats.st_mtime:
                return thumb_path
        except OSError:
            pass

    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            resample = getattr(Image, "Resampling", Image).LANCZOS
            img.thumbnail((max_size, max_size), resample)
            img.save(thumb_path, "JPEG", quality=85, optimize=True)
        return thumb_path
    except Exception as e:
        print(f"Thumbnail failed for {image_path}: {e}")
        return None


class _BKTree:
    """BK-tree for fast Hamming-distance neighbor queries on perceptual hashes."""

    def __init__(self, distance_fn: Callable):
        self._distance_fn = distance_fn
        self._root: Optional[Tuple[int, Any]] = None  # (index, hash)
        self._children: Dict[Tuple[int, Any], Dict[int, Tuple[int, Any]]] = {}

    def add(self, index: int, item: Any) -> None:
        node = (index, item)
        if self._root is None:
            self._root = node
            return

        current = self._root
        while True:
            dist = self._distance_fn(item, current[1])
            children = self._children.setdefault(current, {})
            if dist in children:
                current = children[dist]
            else:
                children[dist] = node
                return

    def search(self, item: Any, threshold: int) -> List[int]:
        if self._root is None:
            return []

        results: List[int] = []
        stack = [self._root]

        while stack:
            current = stack.pop()
            dist = self._distance_fn(item, current[1])
            if dist <= threshold:
                results.append(current[0])

            low, high = dist - threshold, dist + threshold
            for child_dist, child in self._children.get(current, {}).items():
                if low <= child_dist <= high:
                    stack.append(child)

        return results


def _hash_pair_distance(items: List[Tuple], i: int, j: int) -> int:
    """Worse of the pHash and dHash distances. Both must be within threshold."""
    ph = int(items[i][1] - items[j][1])
    dh = int(items[i][2] - items[j][2])
    return max(ph, dh)


def _cluster_image_hashes(
    items: List[Tuple],
    distance_threshold: int,
) -> List[Tuple[List[int], int]]:
    """
    Group images that match on both hashes.
    A photo joins a group only when it is close to every member, so a chain
    of lookalikes does not collapse into one big group.
    """
    if len(items) < 2:
        return []

    tree = _BKTree(distance_fn=lambda a, b: a - b)
    for index, item in enumerate(items):
        tree.add(index, item[1])

    used = [False] * len(items)
    groups: List[Tuple[List[int], int]] = []

    for i in range(len(items)):
        if used[i]:
            continue
        cluster = [i]
        used[i] = True
        candidates = []
        for j in tree.search(items[i][1], distance_threshold):
            if j == i or used[j]:
                continue
            pair_distance = _hash_pair_distance(items, i, j)
            if pair_distance <= distance_threshold:
                candidates.append((pair_distance, j))
        candidates.sort()

        for _, j in candidates:
            if used[j]:
                continue
            if all(
                _hash_pair_distance(items, j, member) <= distance_threshold
                for member in cluster
            ):
                cluster.append(j)
                used[j] = True

        if len(cluster) < 2:
            continue

        worst = 0
        for left in range(len(cluster)):
            for right in range(left + 1, len(cluster)):
                worst = max(
                    worst,
                    _hash_pair_distance(items, cluster[left], cluster[right]),
                )
        groups.append((cluster, worst))

    return groups


def _cluster_videos(
    videos_with_hashes: List[Tuple[str, List[Any]]],
    distance_threshold: float,
) -> List[Tuple[List[int], int]]:
    """Group videos by average frame distance, using the first frame as a filter."""
    if len(videos_with_hashes) < 2:
        return []

    tree = _BKTree(distance_fn=lambda a, b: a - b)
    for index, (_, hashes) in enumerate(videos_with_hashes):
        if hashes:
            tree.add(index, hashes[0])

    used = [False] * len(videos_with_hashes)
    groups: List[Tuple[List[int], int]] = []
    candidate_limit = int(distance_threshold) + 4

    for i, (_, hashes_i) in enumerate(videos_with_hashes):
        if used[i] or not hashes_i:
            continue
        cluster = [i]
        used[i] = True
        candidates: List[Tuple[float, int]] = []
        for j in tree.search(hashes_i[0], candidate_limit):
            if j == i or used[j]:
                continue
            dist = video_hash_distance(hashes_i, videos_with_hashes[j][1])
            if dist is not None and dist <= distance_threshold:
                candidates.append((dist, j))
        candidates.sort()

        for _, j in candidates:
            if used[j]:
                continue
            hashes_j = videos_with_hashes[j][1]
            close_to_all = True
            for member in cluster:
                dist = video_hash_distance(hashes_j, videos_with_hashes[member][1])
                if dist is None or dist > distance_threshold:
                    close_to_all = False
                    break
            if close_to_all:
                cluster.append(j)
                used[j] = True

        if len(cluster) < 2:
            continue

        worst = 0.0
        for left in range(len(cluster)):
            for right in range(left + 1, len(cluster)):
                dist = video_hash_distance(
                    videos_with_hashes[cluster[left]][1],
                    videos_with_hashes[cluster[right]][1],
                )
                if dist is not None:
                    worst = max(worst, dist)
        groups.append((cluster, int(round(worst))))

    return groups


def _hash_file_with_local_cache(path: str, cache: Dict[str, Any]) -> Optional[str]:
    """Thread-safe read from shared cache; compute hash without writing shared cache."""
    try:
        stats = os.stat(path)
    except OSError as e:
        print(f"Skipping {path}: {e}")
        return None

    size = stats.st_size
    mtime = stats.st_mtime
    entry = cache.get(path)
    if entry:
        if (
            entry.get("size") == size
            and entry.get("mtime") == mtime
            and "sha256" in entry
        ):
            return entry["sha256"]

    try:
        return hash_file(path)
    except (PermissionError, OSError) as e:
        print(f"Skipping {path}: {e}")
        return None


def _signature_from_entry(entry: Dict[str, Any], size: int, mtime: float):
    if not entry:
        return None
    if (
        entry.get("size") == size
        and entry.get("mtime") == mtime
        and entry.get("phash")
        and entry.get("dhash")
        and entry.get("width")
        and entry.get("height")
    ):
        try:
            return (
                imagehash.hex_to_hash(entry["phash"]),
                imagehash.hex_to_hash(entry["dhash"]),
                int(entry["width"]),
                int(entry["height"]),
            )
        except Exception as err:
            print(f"Error restoring image hashes: {err}")
    return None


def _image_signature_job(payload: Tuple[str, Optional[Dict[str, Any]]]):
    """Process-pool worker. Returns a plain tuple so it can cross processes."""
    path, entry = payload
    try:
        stats = os.stat(path)
    except OSError as e:
        print(f"Skipping {path}: {e}")
        return None

    cached = _signature_from_entry(entry or {}, stats.st_size, stats.st_mtime)
    if cached is not None:
        ph, dh, width, height = cached
        return path, str(ph), str(dh), width, height

    signature = compute_image_signature(path)
    if signature is None:
        return None
    ph, dh, width, height = signature
    return path, str(ph), str(dh), width, height


def _merge_sha_cache(path: str, file_hash: str, cache: Dict[str, Any]) -> None:
    try:
        stats = os.stat(path)
    except OSError:
        return
    entry = cache.get(path) or {}
    cache[path] = {
        **entry,
        "size": stats.st_size,
        "mtime": stats.st_mtime,
        "sha256": file_hash,
    }


def _merge_image_cache(
    path: str,
    phash_hex: str,
    dhash_hex: str,
    width: int,
    height: int,
    cache: Dict[str, Any],
) -> None:
    try:
        stats = os.stat(path)
    except OSError:
        return
    entry = cache.get(path) or {}
    cache[path] = {
        **entry,
        "size": stats.st_size,
        "mtime": stats.st_mtime,
        "phash": phash_hex,
        "dhash": dhash_hex,
        "width": width,
        "height": height,
    }


def _hash_files_parallel(
    paths: List[str],
    cache: Dict[str, Any],
    max_workers: int = 8,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, List[str]]:
    """Hash many files in parallel; returns hash -> paths map."""
    hash_map: Dict[str, List[str]] = defaultdict(list)
    total = len(paths)
    done = 0

    if total == 0:
        return hash_map

    workers = min(max_workers, max(1, total))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_hash_file_with_local_cache, p, cache): p
            for p in paths
        }
        for future in as_completed(futures):
            done += 1
            if progress_callback:
                progress_callback(done, total)
            path = futures[future]
            file_hash = future.result()
            if file_hash:
                hash_map[file_hash].append(path)
                _merge_sha_cache(path, file_hash, cache)

    return hash_map


def _cache_snapshot(entry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not entry:
        return None
    keys = ("size", "mtime", "phash", "dhash", "width", "height")
    return {key: entry.get(key) for key in keys}


def _compute_image_signatures_parallel(
    paths: List[str],
    cache: Dict[str, Any],
    max_workers: int = 8,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[Tuple[str, Any, Any]]:
    """Hash images with pHash and dHash. Uses processes for larger folders."""
    results: List[Tuple[str, Any, Any]] = []
    total = len(paths)
    done = 0

    if total == 0:
        return results

    workers = min(max_workers, max(1, total))
    jobs = [(path, _cache_snapshot(cache.get(path))) for path in paths]
    use_processes = workers > 1 and total >= 12

    def _collect(executor) -> None:
        nonlocal done
        futures = {
            executor.submit(_image_signature_job, job): job[0] for job in jobs
        }
        for future in as_completed(futures):
            done += 1
            if progress_callback:
                progress_callback(done, total)
            result = future.result()
            if not result:
                continue
            path, phash_hex, dhash_hex, width, height = result
            _merge_image_cache(path, phash_hex, dhash_hex, width, height, cache)
            results.append(
                (
                    path,
                    imagehash.hex_to_hash(phash_hex),
                    imagehash.hex_to_hash(dhash_hex),
                )
            )

    if use_processes:
        try:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                _collect(executor)
            return results
        except Exception as e:
            print(f"Process pool unavailable ({e}); hashing images in threads.")
            results.clear()
            done = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        _collect(executor)
    return results


# -----------------------------
# Core Engines
# -----------------------------

def _exact_hash_candidates(
    index: MediaIndex,
    max_workers: int = 8,
) -> List[str]:
    """Files that share size and quick fingerprint with at least one other file."""
    size_map: Dict[int, List[str]] = defaultdict(list)
    for path in index.all_paths:
        size_map[index.sizes[path]].append(path)

    size_collisions = [paths for paths in size_map.values() if len(paths) > 1]
    if not size_collisions:
        return []

    candidates: List[str] = []
    workers = min(max_workers, max(1, len(size_collisions)))

    def _bucket(paths: List[str]) -> List[str]:
        quick_map: Dict[str, List[str]] = defaultdict(list)
        for path in paths:
            fp = quick_fingerprint(path)
            if fp:
                quick_map[fp].append(path)
        out: List[str] = []
        for bucket in quick_map.values():
            if len(bucket) > 1:
                out.extend(bucket)
        return out

    if len(size_collisions) < 32:
        for paths in size_collisions:
            candidates.extend(_bucket(paths))
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for bucketed in executor.map(_bucket, size_collisions):
                candidates.extend(bucketed)

    return candidates


def find_exact_duplicate_groups(
    root_folder: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    index: Optional[MediaIndex] = None,
    max_workers: int = 8,
    cache: Optional[Dict[str, Any]] = None,
) -> List[DuplicateGroup]:
    """
    Find exact duplicate files (any type) using SHA-256.
    Size + quick fingerprint pre-filter, then parallel SHA-256 with cache.
    """
    index = index or MediaIndex.build(root_folder)
    cache, owns_cache = _bind_cache(root_folder, cache)
    candidates = _exact_hash_candidates(index, max_workers=max_workers)

    hash_map = _hash_files_parallel(
        candidates,
        cache,
        max_workers=max_workers,
        progress_callback=progress_callback,
    )
    if owns_cache:
        save_cache(root_folder, cache)

    groups: List[DuplicateGroup] = []
    for paths in hash_map.values():
        if len(paths) > 1:
            groups.append(
                DuplicateGroup(
                    group_type="exact",
                    files=_files_for_paths(paths, cache),
                )
            )

    return _sort_groups(groups)


def find_similar_image_groups(
    root_folder: str,
    distance_threshold: int = 5,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    index: Optional[MediaIndex] = None,
    max_workers: int = 8,
    cache: Optional[Dict[str, Any]] = None,
) -> List[DuplicateGroup]:
    """
    Find visually similar images using pHash and dHash.
    Hashes a small thumbnail, then groups only photos that match on both.
    """
    index = index or MediaIndex.build(root_folder)
    cache, owns_cache = _bind_cache(root_folder, cache)

    images_with_hashes = _compute_image_signatures_parallel(
        index.image_paths,
        cache,
        max_workers=max_workers,
        progress_callback=progress_callback,
    )
    print(f"Total images processed for similarity: {len(images_with_hashes)}")
    if owns_cache:
        save_cache(root_folder, cache)

    groups: List[DuplicateGroup] = []
    for index_cluster, worst in _cluster_image_hashes(
        images_with_hashes, distance_threshold
    ):
        current_paths = [images_with_hashes[i][0] for i in index_cluster]
        groups.append(
            DuplicateGroup(
                group_type="similar_image",
                files=_files_for_paths(current_paths, cache),
                match_distance=worst,
            )
        )

    return _sort_groups(groups)

def get_video_frame_hashes_cached(
    video_path: str,
    cache: Dict[str, Any],
    num_frames: int = 5,
) -> List[Any]:
    """Keyframe pHashes with JSON cache (same pattern as images)."""
    stats = os.stat(video_path)
    size = stats.st_size
    mtime = stats.st_mtime

    entry = cache.get(video_path)
    if entry:
        if (
            entry.get("size") == size
            and entry.get("mtime") == mtime
            and entry.get("num_frames") == num_frames
            and "video_phashes" in entry
        ):
            try:
                return [
                    imagehash.hex_to_hash(h) for h in entry["video_phashes"]
                ]
            except Exception as e:
                print(f"Error restoring video hashes for {video_path}: {e}")

    frame_hashes = extract_video_frame_hashes(video_path, num_frames=num_frames)
    if frame_hashes:
        cache[video_path] = {
            **(entry or {}),
            "size": size,
            "mtime": mtime,
            "num_frames": num_frames,
            "video_phashes": [str(h) for h in frame_hashes],
        }
    return frame_hashes


def _video_frame_hashes_readonly(
    video_path: str,
    cache: Dict[str, Any],
    num_frames: int,
) -> List[Any]:
    """Read cached video hashes or compute without mutating shared cache."""
    try:
        stats = os.stat(video_path)
    except OSError:
        return []

    size = stats.st_size
    mtime = stats.st_mtime
    entry = cache.get(video_path)
    if entry:
        if (
            entry.get("size") == size
            and entry.get("mtime") == mtime
            and entry.get("num_frames") == num_frames
            and "video_phashes" in entry
        ):
            try:
                return [
                    imagehash.hex_to_hash(h) for h in entry["video_phashes"]
                ]
            except Exception as e:
                print(f"Error restoring video hashes for {video_path}: {e}")

    return extract_video_frame_hashes(video_path, num_frames=num_frames)


def _merge_video_cache(
    video_path: str,
    frame_hashes: List[Any],
    cache: Dict[str, Any],
    num_frames: int,
) -> None:
    if not frame_hashes:
        return
    try:
        stats = os.stat(video_path)
    except OSError:
        return
    entry = cache.get(video_path) or {}
    cache[video_path] = {
        **entry,
        "size": stats.st_size,
        "mtime": stats.st_mtime,
        "num_frames": num_frames,
        "video_phashes": [str(h) for h in frame_hashes],
    }


def _video_hashes_one(
    path: str,
    cache: Dict[str, Any],
    num_frames: int,
) -> Optional[Tuple[str, List[Any]]]:
    frame_hashes = _video_frame_hashes_readonly(path, cache, num_frames)
    if frame_hashes:
        return path, frame_hashes
    return None


def find_similar_video_groups(
    root_folder: str,
    num_frames: int = 5,
    distance_threshold: float = 5.0,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    index: Optional[MediaIndex] = None,
    max_workers: int = 4,
    cache: Optional[Dict[str, Any]] = None,
) -> List[DuplicateGroup]:
    """
    Find visually similar videos using keyframe pHash.
    Uses cache and parallel frame extraction where possible.
    """
    index = index or MediaIndex.build(root_folder)
    cache, owns_cache = _bind_cache(root_folder, cache)
    video_paths = index.video_paths
    videos_with_hashes: List[Tuple[str, List[Any]]] = []
    total = len(video_paths)
    done = 0

    if total == 0:
        return []

    # OpenCV video decode is heavy; limit workers to avoid thrashing disk.
    workers = min(max(1, max_workers // 2), 4, total)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _video_hashes_one, p, cache, num_frames
            ): p
            for p in video_paths
        }
        for future in as_completed(futures):
            done += 1
            if progress_callback:
                progress_callback(done, total)
            result = future.result()
            if result:
                path, frame_hashes = result
                videos_with_hashes.append((path, frame_hashes))
                _merge_video_cache(path, frame_hashes, cache, num_frames)

    print(f"Total videos processed for similarity: {len(videos_with_hashes)}")
    if owns_cache:
        save_cache(root_folder, cache)

    groups: List[DuplicateGroup] = []
    for index_cluster, worst in _cluster_videos(videos_with_hashes, distance_threshold):
        current_paths = [videos_with_hashes[i][0] for i in index_cluster]
        groups.append(
            DuplicateGroup(
                group_type="similar_video",
                files=_files_for_paths(current_paths, cache),
                match_distance=worst,
            )
        )

    return _sort_groups(groups)


def _document_text_hash_readonly(path: str, cache: Dict[str, Any]) -> Optional[str]:
    """SHA-256 of normalized text; reads cache only (thread-safe for workers)."""
    try:
        stats = os.stat(path)
    except OSError:
        return None

    size = stats.st_size
    mtime = stats.st_mtime
    entry = cache.get(path)
    if entry:
        if (
            entry.get("size") == size
            and entry.get("mtime") == mtime
            and "text_sha256" in entry
        ):
            return entry["text_sha256"]

    raw = extract_document_text(path)
    if not raw:
        return None

    normalized = _normalize_document_text(raw)
    if len(normalized) < 40:
        return None

    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _merge_document_text_cache(path: str, text_hash: str, cache: Dict[str, Any]) -> None:
    try:
        stats = os.stat(path)
    except OSError:
        return
    entry = cache.get(path) or {}
    cache[path] = {
        **entry,
        "size": stats.st_size,
        "mtime": stats.st_mtime,
        "text_sha256": text_hash,
    }


def _document_hash_one(path: str, cache: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    text_hash = _document_text_hash_readonly(path, cache)
    if text_hash:
        return path, text_hash
    return None


def find_similar_document_groups(
    root_folder: str,
    index: Optional[MediaIndex] = None,
    max_workers: int = 8,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cache: Optional[Dict[str, Any]] = None,
) -> List[DuplicateGroup]:
    """
    Find documents with the same extracted text content (PDF, Word, text files).
    Legacy .doc and scanned PDFs without text may be skipped.
    """
    index = index or MediaIndex.build(root_folder)
    cache, owns_cache = _bind_cache(root_folder, cache)
    hash_map: Dict[str, List[str]] = defaultdict(list)
    paths = index.document_paths
    total = len(paths)
    done = 0

    if total == 0:
        return []

    workers = min(max_workers, max(1, total))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_document_hash_one, p, cache): p for p in paths
        }
        for future in as_completed(futures):
            done += 1
            if progress_callback:
                progress_callback(done, total)
            result = future.result()
            if result:
                path, text_hash = result
                hash_map[text_hash].append(path)
                _merge_document_text_cache(path, text_hash, cache)

    if owns_cache:
        save_cache(root_folder, cache)

    groups: List[DuplicateGroup] = []
    for paths_in_group in hash_map.values():
        if len(paths_in_group) > 1:
            groups.append(
                DuplicateGroup(
                    group_type="similar_document",
                    files=_files_for_paths(paths_in_group, cache),
                )
            )

    print(f"Similar document groups found: {len(groups)}")
    return _sort_groups(groups)


def run_scan(
    config: ScanConfig,
    progress_callback: Optional[ProgressCallback] = None,
) -> ScanResult:
    """
    Professional entry point: one folder walk, phased duplicate detection, stats.
    progress_callback(phase, done, total) where phase is indexing|exact|images|videos.
    """
    started = time.perf_counter()
    root = config.root_folder

    if progress_callback:
        progress_callback("indexing", 0, 1)
    index = MediaIndex.build(root)
    if progress_callback:
        progress_callback("indexing", 1, 1)

    result = ScanResult(index=index)
    result.stats.total_files = len(index.all_paths)
    result.stats.total_images = len(index.image_paths)
    result.stats.total_videos = len(index.video_paths)
    result.stats.total_documents = len(index.document_paths)
    cache = load_cache(root)

    if config.include_exact:
        result.exact_groups = find_exact_duplicate_groups(
            root,
            index=index,
            max_workers=config.max_workers,
            cache=cache,
            progress_callback=(
                lambda d, t: progress_callback("exact", d, t)
                if progress_callback
                else None
            ),
        )

    if config.include_similar_images:
        result.similar_groups = find_similar_image_groups(
            root,
            config.distance_threshold,
            index=index,
            max_workers=config.max_workers,
            cache=cache,
            progress_callback=(
                lambda d, t: progress_callback("images", d, t)
                if progress_callback
                else None
            ),
        )
        if config.include_exact:
            result.similar_groups = _sort_groups(
                _without_exact_overlaps(result.similar_groups, result.exact_groups)
            )

    if config.include_similar_videos:
        result.similar_video_groups = find_similar_video_groups(
            root,
            num_frames=config.video_num_frames,
            distance_threshold=float(config.distance_threshold),
            index=index,
            max_workers=config.max_workers,
            cache=cache,
            progress_callback=(
                lambda d, t: progress_callback("videos", d, t)
                if progress_callback
                else None
            ),
        )

    if config.include_similar_documents:
        result.similar_document_groups = find_similar_document_groups(
            root,
            index=index,
            max_workers=config.max_workers,
            cache=cache,
            progress_callback=(
                lambda d, t: progress_callback("documents", d, t)
                if progress_callback
                else None
            ),
        )

    save_cache(root, cache)
    result.stats.exact_groups = len(result.exact_groups)
    result.stats.similar_image_groups = len(result.similar_groups)
    result.stats.similar_video_groups = len(result.similar_video_groups)
    result.stats.similar_document_groups = len(result.similar_document_groups)
    result.stats.reclaimable_bytes = estimate_reclaimable_bytes(
        result.exact_groups
        + result.similar_groups
        + result.similar_video_groups
        + result.similar_document_groups
    )
    result.stats.duration_seconds = time.perf_counter() - started
    return result


def move_files_safely(file_paths: list[str], base_folder: str) -> str:
    """
    Move selected files into a new '_duplicates_<timestamp>' folder
    inside the same base folder.

    Returns the path of the duplicates folder created.
    """
    if not file_paths:
        return ""

    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    folder_name = os.path.join(base_folder, f"_duplicates_{timestamp}")
    duplicates_folder = folder_name
    folder_suffix = 1
    while True:
        try:
            os.mkdir(duplicates_folder)
            break
        except FileExistsError:
            duplicates_folder = f"{folder_name}_{folder_suffix}"
            folder_suffix += 1

    moved_count = 0
    failures = []

    for file_path in file_paths:
        if not os.path.isfile(file_path):
            failures.append(f"{file_path}: file does not exist")
            continue

        filename = os.path.basename(file_path)
        destination = os.path.join(duplicates_folder, filename)
        stem, extension = os.path.splitext(filename)
        suffix = 2
        while os.path.lexists(destination):
            destination = os.path.join(
                duplicates_folder, f"{stem} ({suffix}){extension}"
            )
            suffix += 1

        try:
            shutil.move(file_path, destination)
            moved_count += 1
        except (OSError, shutil.Error) as e:
            failures.append(f"{file_path}: {e}")

    if failures:
        if moved_count == 0:
            os.rmdir(duplicates_folder)
        moved_to = f" Files moved to {duplicates_folder}." if moved_count else ""
        raise OSError(
            f"Moved {moved_count} of {len(file_paths)} files.{moved_to} "
            f"Failures: {'; '.join(failures)}"
        )

    return duplicates_folder

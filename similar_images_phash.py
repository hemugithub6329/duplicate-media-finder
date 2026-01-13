import os
from PIL import Image
import imagehash

# Extensions that we treat as images
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}


def is_image_file(filename: str) -> bool:
    """Check if file is an image using extension."""
    _, ext = os.path.splitext(filename)
    return ext.lower() in IMAGE_EXTENSIONS


def compute_phash(image_path: str):
    """
    Compute perceptual hash (pHash) for an image.
    Returns imagehash object or None if image fails to load.
    """
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")  # standardize format
            ph = imagehash.phash(img)
            return ph
    except Exception as e:
        print(f"Skipping {image_path}: cannot open image ({e})")
        return None


def find_similar_images(root_folder: str, distance_threshold: int = 5):
    """
    Find visually similar images using perceptual hash distance.
    distance_threshold:
        0–2 => almost identical images
        3–5 => similar images
        6–10 => loose matching
    """
    images = []  # list of (path, phash)

    # Step 1: collect all images + compute pHash
    for folder_path, _, files in os.walk(root_folder):
        for file_name in files:
            if not is_image_file(file_name):
                continue

            full_path = os.path.join(folder_path, file_name)
            ph = compute_phash(full_path)
            if ph is not None:
                images.append((full_path, ph))

    print(f"Total images processed: {len(images)}")

    # Step 2: group similar images based on pHash distance
    groups = []
    used = set()

    for i in range(len(images)):
        if i in used:
            continue

        path_i, hash_i = images[i]
        group = [path_i]
        used.add(i)

        for j in range(i + 1, len(images)):
            if j in used:
                continue

            path_j, hash_j = images[j]

            # Hamming distance between pHashes
            dist = hash_i - hash_j

            if dist <= distance_threshold:
                group.append(path_j)
                used.add(j)

        # Keep only groups with 2 or more items
        if len(group) > 1:
            groups.append(group)

    return groups


def main():
    folder_path = input("Enter folder path to scan for similar images: ").strip()

    if not os.path.isdir(folder_path):
        print("❌ Invalid folder path!")
        return

    threshold = 5  # You can tune this later
    print(f"\n🔍 Scanning for visually similar images (threshold = {threshold})...\n")

    groups = find_similar_images(folder_path, threshold)

    if not groups:
        print("✅ No similar image groups found.")
        return

    print(f"✅ Found {len(groups)} group(s) of similar images:\n")
    for idx, group in enumerate(groups, start=1):
        print(f"Group {idx}:")
        for path in group:
            print("   ", path)
        print()


if __name__ == "__main__":
    main()

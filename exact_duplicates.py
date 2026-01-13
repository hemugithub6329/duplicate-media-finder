import os
import hashlib


def hash_file(file_path, chunk_size=1024 * 1024):
    """
    Calculate SHA-256 hash of a file.
    - file_path: full path to the file
    - chunk_size: how many bytes to read at a time (default: 1 MB)
    """
    hasher = hashlib.sha256()

    # Open file in binary mode
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)

    return hasher.hexdigest()


def find_exact_duplicates(root_folder):
    """
    Walk through all files under root_folder,
    and group files that have the same hash.
    Returns a list of duplicate groups.
    """
    hash_map = {}  # hash_value -> list of file paths

    for folder_path, dir_names, file_names in os.walk(root_folder):
        for file_name in file_names:
            file_path = os.path.join(folder_path, file_name)

            try:
                file_hash = hash_file(file_path)
            except (PermissionError, OSError) as e:
                # Some files might not be readable (e.g., permission issues)
                print(f"Skipping {file_path}: {e}")
                continue

            # Add this file path into the map
            hash_map.setdefault(file_hash, []).append(file_path)

    # Keep only those entries where more than one file has same hash
    duplicate_groups = [
        paths for paths in hash_map.values() if len(paths) > 1
    ]

    return duplicate_groups


def main():
    # 1) Ask the user for folder path
    folder_path = input("Enter folder path to scan for exact duplicates: ").strip()

    # 2) Validate path
    if not os.path.isdir(folder_path):
        print("❌ That is not a valid folder path.")
        return

    print("\n🔍 Scanning for exact duplicate files...")
    print("   (This may take some time for large folders.)\n")

    # 3) Find duplicates
    duplicate_groups = find_exact_duplicates(folder_path)

    # 4) Show result
    if not duplicate_groups:
        print("✅ No exact duplicate files found.")
        return

    print(f"✅ Found {len(duplicate_groups)} duplicate group(s):\n")

    for idx, group in enumerate(duplicate_groups, start=1):
        print(f"Group {idx}:")
        for path in group:
            print("   ", path)
        print()  # blank line between groups


if __name__ == "__main__":
    main()

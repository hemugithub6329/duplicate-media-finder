from duplicate_core import (
    find_exact_duplicate_groups,
    find_similar_image_groups,
)


def pretty_print_groups(groups, title: str):
    print(f"\n===== {title} =====")
    if not groups:
        print("No groups found.")
        return

    print(f"Total groups: {len(groups)}\n")
    for idx, group in enumerate(groups, start=1):
        print(f"Group {idx} ({group.group_type}):")
        for file_info in group.files:
            print(f"   {file_info.path}  |  size={file_info.size} bytes")
        print()


def main():
    folder_path = input("Enter folder path to test core duplicate engine: ").strip()

    # Exact duplicates
    exact_groups = find_exact_duplicate_groups(folder_path)
    pretty_print_groups(exact_groups, "Exact Duplicate Groups")

    # Similar images
    similar_groups = find_similar_image_groups(folder_path, distance_threshold=5)
    pretty_print_groups(similar_groups, "Similar Image Groups (pHash)")


if __name__ == "__main__":
    main()

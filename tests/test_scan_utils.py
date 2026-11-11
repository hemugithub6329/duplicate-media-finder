import os
import tempfile
import unittest

import numpy as np
import imagehash

from duplicate_core import (
    DuplicateGroup,
    FileInfo,
    MediaIndex,
    ScanConfig,
    _cluster_image_hashes,
    _exact_hash_candidates,
    _without_exact_overlaps,
    estimate_reclaimable_bytes,
    format_bytes,
    is_document_file,
    move_files_safely,
    order_files_for_keep,
    quick_fingerprint,
    run_scan,
)


def _bits(n_true: int) -> imagehash.ImageHash:
    values = [False] * 64
    for index in range(n_true):
        values[index] = True
    return imagehash.ImageHash(np.array(values, dtype=bool).reshape(8, 8))


class TestFormatBytes(unittest.TestCase):
    def test_units(self):
        self.assertEqual(format_bytes(500), "500 B")
        self.assertIn("KB", format_bytes(2048))
        self.assertIn("MB", format_bytes(5 * 1024 * 1024))


class TestReclaimable(unittest.TestCase):
    def test_sums_non_largest(self):
        group = DuplicateGroup(
            group_type="exact",
            files=[
                FileInfo("/a", 100, 0),
                FileInfo("/b", 200, 0),
                FileInfo("/c", 50, 0),
            ],
        )
        self.assertEqual(estimate_reclaimable_bytes([group]), 150)


class TestQuickFingerprint(unittest.TestCase):
    def test_same_content_same_fp(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = os.path.join(tmp, "a.bin")
            p2 = os.path.join(tmp, "b.bin")
            with open(p1, "wb") as f:
                f.write(b"hello world" * 100)
            with open(p2, "wb") as f:
                f.write(b"hello world" * 100)
            self.assertEqual(quick_fingerprint(p1), quick_fingerprint(p2))

    def test_different_content_different_fp(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = os.path.join(tmp, "a.bin")
            p2 = os.path.join(tmp, "b.bin")
            with open(p1, "wb") as f:
                f.write(b"aaaa" * 1000)
            with open(p2, "wb") as f:
                f.write(b"bbbb" * 1000)
            self.assertNotEqual(quick_fingerprint(p1), quick_fingerprint(p2))


class TestExactCandidates(unittest.TestCase):
    def test_size_only_collision_gets_quick_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i in range(3):
                p = os.path.join(tmp, f"f{i}.bin")
                with open(p, "wb") as f:
                    f.write(os.urandom(128))
                paths.append(p)
            index = MediaIndex.build(tmp)
            candidates = _exact_hash_candidates(index)
            self.assertEqual(len(candidates), 0)


class TestImageGrouping(unittest.TestCase):
    def test_chain_does_not_merge_distant_photos(self):
        # A-B distance 4, B-C distance 4, A-C distance 8.
        near = _bits(0)
        middle = _bits(4)
        far = _bits(8)
        items = [
            ("a.jpg", near, near),
            ("b.jpg", middle, middle),
            ("c.jpg", far, far),
        ]
        groups = _cluster_image_hashes(items, distance_threshold=5)
        self.assertEqual(len(groups), 1)
        members = {items[i][0] for i in groups[0][0]}
        self.assertEqual(members, {"a.jpg", "b.jpg"})
        self.assertLessEqual(groups[0][1], 5)

    def test_both_hashes_must_agree(self):
        same = _bits(0)
        ph_close = _bits(2)
        dh_far = _bits(20)
        items = [
            ("a.jpg", same, same),
            ("b.jpg", ph_close, dh_far),
        ]
        self.assertEqual(_cluster_image_hashes(items, 5), [])


class TestKeepOrder(unittest.TestCase):
    def test_prefers_larger_image_outside_downloads(self):
        files = [
            FileInfo(r"C:\Users\Downloads\shot.jpg", 500, 0, width=100, height=100),
            FileInfo(r"C:\Photos\original.jpg", 400, 0, width=200, height=200),
        ]
        ordered = order_files_for_keep(files)
        self.assertTrue(ordered[0].path.endswith("original.jpg"))


class TestExactOverlap(unittest.TestCase):
    def test_drops_similar_group_that_is_only_exact_copies(self):
        exact = DuplicateGroup(
            "exact",
            [FileInfo("a.jpg", 10, 0), FileInfo("b.jpg", 10, 0)],
        )
        similar_same = DuplicateGroup(
            "similar_image",
            [FileInfo("a.jpg", 10, 0), FileInfo("b.jpg", 10, 0)],
        )
        similar_extra = DuplicateGroup(
            "similar_image",
            [
                FileInfo("a.jpg", 10, 0),
                FileInfo("b.jpg", 10, 0),
                FileInfo("c.jpg", 8, 0),
            ],
        )
        kept = _without_exact_overlaps([similar_same, similar_extra], [exact])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].files[-1].path, "c.jpg")


class TestRunScan(unittest.TestCase):
    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_scan(ScanConfig(root_folder=tmp))
            self.assertEqual(result.stats.total_files, 0)
            self.assertEqual(result.exact_groups, [])


class TestDocumentFormats(unittest.TestCase):
    def test_only_supported_document_formats_are_indexed(self):
        for extension in (".pdf", ".docx", ".txt", ".rtf", ".md", ".csv"):
            with self.subTest(extension=extension):
                self.assertTrue(is_document_file(f"document{extension}"))

        for extension in (".doc", ".odt", ".xlsx", ".xls", ".pptx", ".ppt"):
            with self.subTest(extension=extension):
                self.assertFalse(is_document_file(f"document{extension}"))


class TestSafeMove(unittest.TestCase):
    def test_preserves_files_with_colliding_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for folder, content in (("one", b"first"), ("two", b"second")):
                source_folder = os.path.join(tmp, folder)
                os.mkdir(source_folder)
                path = os.path.join(source_folder, "same.jpg")
                with open(path, "wb") as file:
                    file.write(content)
                paths.append(path)

            destination = move_files_safely(paths, tmp)
            moved = {}
            for name in os.listdir(destination):
                with open(os.path.join(destination, name), "rb") as file:
                    moved[name] = file.read()

            self.assertEqual(set(moved.values()), {b"first", b"second"})
            self.assertEqual(len(moved), 2)
            self.assertTrue(all(not os.path.exists(path) for path in paths))

    def test_reports_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "missing.txt")
            with self.assertRaisesRegex(OSError, "file does not exist"):
                move_files_safely([missing], tmp)


if __name__ == "__main__":
    unittest.main()

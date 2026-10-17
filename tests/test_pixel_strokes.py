"""Open structures remain open and independent image regions receive detail."""
import cv2
import numpy as np
import pytest

from camera_assistant.services.pixel_strokes import (
    MAX_EDGE_PIXELS,
    MAX_STROKES,
    edge_chains,
    structural_strokes,
)


def test_separate_open_lines_never_become_closed_shapes_or_cross_a_gap():
    edges = np.zeros((40, 60), dtype=np.uint8)
    edges[10, 5:23] = 255
    edges[30, 35:55] = 255
    chains = edge_chains(edges)
    assert len(chains) == 2
    for chain in chains:
        assert not np.array_equal(chain[0], chain[-1])
        assert len(set(chain[:, 0, 1])) == 1
        assert all(edges[y, x] for x, y in chain[:, 0])


def test_junction_does_not_join_unrelated_arms_with_diagonals():
    edges = np.zeros((31, 31), dtype=np.uint8)
    edges[15, 3:28] = 255
    edges[3:28, 15] = 255
    chains = edge_chains(edges)
    assert len(chains) == 4
    assert all(len(set(c[:, 0, 0])) == 1 or len(set(c[:, 0, 1])) == 1 for c in chains)


def test_closed_pixel_loop_keeps_its_actual_boundary():
    edges = np.zeros((40, 40), dtype=np.uint8)
    cv2.rectangle(edges, (8, 8), (30, 30), 255)
    chains = edge_chains(edges)
    assert len(chains) == 1
    assert np.array_equal(chains[0][0], chains[0][-1])


def test_blank_or_outside_mask_has_no_invented_detail():
    image = np.full((80, 100, 3), 240, dtype=np.uint8)
    assert structural_strokes(image, np.full((80, 100), 255, dtype=np.uint8)) == []
    cv2.circle(image, (50, 40), 20, (40, 40, 40), 2)
    assert structural_strokes(image, np.zeros((80, 100), dtype=np.uint8)) == []


def test_line_budget_still_keeps_small_features_in_distant_regions():
    image = np.full((180, 300, 3), 240, dtype=np.uint8)
    for y in range(8, 170, 5):
        cv2.line(image, (10, y), (130, y), (30, 30, 30), 1)
    cv2.circle(image, (250, 90), 8, (40, 40, 40), 1)
    strokes = structural_strokes(image, np.full((180, 300), 255, dtype=np.uint8))
    assert 0 < len(strokes) <= MAX_STROKES
    assert any(np.min(s[:, 0]) > 230 for s in strokes)
    assert all(2 <= len(s) <= 64 for s in strokes)


def test_adversarial_edge_count_is_bounded_before_graph_allocation():
    with pytest.raises(ValueError, match="密度"):
        edge_chains(np.full((200, MAX_EDGE_PIXELS//200+1), 255, dtype=np.uint8))


def test_flower_color_marks_keep_actual_centers_without_inventing_a_radial_icon():
    image = np.full((100, 100, 3), 240, dtype=np.uint8)
    cv2.circle(image, (35, 45), 3, (220, 170, 30), -1)
    cv2.circle(image, (60, 65), 3, (220, 170, 30), -1)
    strokes = structural_strokes(image, np.full((100, 100), 255, dtype=np.uint8), kind="flower")
    assert len(strokes) >= 2
    assert all(np.array_equal(p[0], p[-1]) for p in strokes[:2])
    centers = [p.mean(axis=0) for p in strokes[:2]]
    assert any(np.linalg.norm(c-[35, 45]) < 4 for c in centers)
    assert any(np.linalg.norm(c-[60, 65]) < 4 for c in centers)

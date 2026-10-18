import cv2
import numpy as np

from camera_assistant.services.pixel_small_objects import hole_matches_exterior, small_roi_mask


def test_retry_follows_observed_irregular_pixels_without_circle_or_roi_rectangle():
    rgb = np.full((200, 240, 3), (85, 135, 40), dtype=np.uint8)
    polygon = np.array([[40, 40], [58, 39], [63, 48], [56, 60], [45, 57], [39, 48]])
    cv2.fillPoly(rgb, [polygon], (30, 90, 180))
    mask, diag = small_roi_mask(rgb, [38/240, 37/200, 65/240, 63/200])
    assert diag['code'] == 'small_roi_contrast_seeded' and diag['candidates'] == 1
    assert mask[45, 50] and not mask[38, 39] and not mask[62, 64]
    assert mask.dtype == np.bool_ and mask.sum() < 27*26*.8


def test_same_colours_cannot_create_a_prop_and_large_roi_is_not_retried():
    rgb = np.full((120, 160, 3), (80, 140, 40), dtype=np.uint8)
    mask, diag = small_roi_mask(rgb, [.2, .2, .3, .3])
    assert mask is None and diag['code'] == 'small_roi_low_contrast'
    mask, diag = small_roi_mask(rgb, [.1, .1, .9, .9])
    assert mask is None and diag['code'] == 'small_roi_ineligible' and diag['candidates'] == 0


def test_exhausted_boundary_deadline_never_starts_native_retry():
    rgb = np.full((120, 160, 3), (80, 140, 40), dtype=np.uint8)
    rgb[25:36, 35:47] = (15, 60, 190)
    mask, diag = small_roi_mask(rgb, [.2, .2, .3, .3], budget=0)
    assert mask is None and diag['code'] == 'small_roi_budget_exceeded' and diag['candidates'] == 0


def test_grass_colour_gap_is_preserved_but_light_fur_cavity_is_only_a_detail():
    rgb = np.full((100, 100, 3), (90, 145, 45), dtype=np.uint8)
    selected = np.zeros((100, 100), np.uint8)
    selected[10:90, 20:80] = 255
    rgb[selected > 0] = (20, 25, 20)
    hole = np.array([[35, 40], [50, 40], [50, 70], [35, 70]], dtype=np.int32).reshape(-1, 1, 2)
    cv2.drawContours(rgb, [hole], -1, (90, 145, 45), cv2.FILLED)
    assert hole_matches_exterior(rgb, selected, hole)
    cv2.drawContours(rgb, [hole], -1, (225, 225, 225), cv2.FILLED)
    assert not hole_matches_exterior(rgb, selected, hole)

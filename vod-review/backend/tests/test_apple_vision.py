import numpy as np

from wisp_classifier import apple_vision, ocr


def test_multiline_reading_order_preserves_all_regions():
    regions = [
        dict(text='second line', left=0.1, top=0.5, height=0.1),
        dict(text='right', left=0.6, top=0.11, height=0.1),
        dict(text='left', left=0.1, top=0.1, height=0.1),
    ]
    assert apple_vision.reading_order(regions) == 'left right\nsecond line'
    assert apple_vision.reading_order([]) == ''


def test_mac_uses_vision_on_each_complete_crop(monkeypatch):
    monkeypatch.setattr(ocr.sys, 'platform', 'darwin')
    crops = [np.zeros((120,200,3),np.uint8), np.ones((90,150,3),np.uint8)]
    seen = []
    def recognize(crop):
        seen.append(crop)
        return 'First\nSecond' if len(seen) == 1 else ''
    monkeypatch.setattr(apple_vision, 'recognize_crop', recognize)
    def unexpected(*args):
        raise AssertionError('PaddleOCR must not run on the Apple Vision path')
    monkeypatch.setattr(ocr, 'recognize_images', unexpected)
    assert ocr.recognize_batch(crops) == ['First\nSecond', '']
    assert seen[0] is crops[0] and seen[1] is crops[1]
    assert ocr.recognize_batch([]) == []
    assert 'Apple Vision' in ocr.runtime_status()['recognition']

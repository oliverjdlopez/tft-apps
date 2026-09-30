"""Capture raw OCR output without interpreting it as a classification."""
import sys
from round_classifier.ocr import recognize_images


def runtime_status():
    if sys.platform == 'darwin':
        return {'text_detection': 'Apple Vision (integrated)',
                'recognition': 'Apple Vision (automatic compute selection)'}
    from round_classifier.ocr import runtime_status as recognition_status
    return {**recognition_status(), 'text_detection': 'Bypassed (whole crop OCR)'}


def recognize_batch(crops):
    if not crops:
        return []
    if sys.platform == 'darwin':
        from .apple_vision import recognize_crop
        return [recognize_crop(crop) for crop in crops]
    results = recognize_images(crops)
    if len(results) != len(crops):
        raise RuntimeError('OCR returned a different number of results than frames')
    # Keep raw text regardless of recognition confidence or round-label validity.
    texts = []
    for result in results:
        payload = result.json.get('res', result.json)
        texts.append(str(payload.get('rec_text', '')))
    return texts

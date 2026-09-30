"""Whole-crop, multiline OCR using the local Apple Vision framework."""
import cv2
import numpy as np


def reading_order(regions):
    """Group nearby baselines, then read rows top-to-bottom and left-to-right."""
    rows = []
    for region in sorted(regions, key=lambda r: (r['top'], r['left'])):
        center = region['top'] + region['height'] / 2
        row = next((row for row in rows
                    if abs(row[0]['top'] + row[0]['height'] / 2 - center)
                    <= min(row[0]['height'], region['height']) * 0.5), None)
        if row is None:
            rows.append([region])
        else:
            row.append(region)
    return '\n'.join(' '.join(r['text'] for r in sorted(row, key=lambda r: r['left']))
                     for row in rows)


def recognize_crop(crop):
    import objc
    import Vision
    from Foundation import NSData

    if crop.dtype != np.uint8 or crop.ndim != 3 or crop.shape[2] != 3 or not crop.size:
        raise ValueError('Apple Vision OCR requires a nonempty uint8 RGB crop')
    # Encode losslessly in memory; no image files or cloud services are involved.
    ok, encoded = cv2.imencode('.png', cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError('Could not encode OCR crop')
    with objc.autorelease_pool():
        data = NSData.dataWithBytes_length_(encoded.tobytes(), encoded.nbytes)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(['en-US'])
        request.setUsesLanguageCorrection_(False)
        request.setMinimumTextHeight_(0.0)
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, {})
        success, error = handler.performRequests_error_([request], None)
        if not success:
            raise RuntimeError(f'Apple Vision OCR failed: {error}')
        regions = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if not candidates:
                continue
            box = observation.boundingBox()
            regions.append(dict(text=str(candidates[0].string()), left=box.origin.x,
                                top=1 - box.origin.y - box.size.height, height=box.size.height))
        return reading_order(regions)

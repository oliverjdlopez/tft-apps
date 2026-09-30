from PIL import Image

from unit_id.preprocessing import letterbox, prepare_image


def test_letterbox_preserves_aspect_ratio_and_adds_padding():
    source = Image.new("RGB", (20, 10), "red")

    result = letterbox(source, 16)

    assert result.size == (16, 16)
    assert result.getpixel((8, 0)) == (0, 0, 0)
    assert result.getpixel((8, 8))[0] > 200
    assert prepare_image(source, 16).shape == (3, 16, 16)

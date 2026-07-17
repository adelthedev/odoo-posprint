import io

from PIL import Image

from odoo.tests import TransactionCase, tagged

from ..services import escpos

ESC_INIT = b"\x1b\x40"
GS_RASTER = b"\x1d\x76\x30"  # GS v 0
FEED_AND_CUT = b"\x1b\x64\x06\x1d\x56\x00"  # ESC d 6 + GS V 0 (python-escpos cut())
DRAWER_PULSE = b"\x1b\x70"  # ESC p


def _png_bytes(width, height, color=255):
    img = Image.new("L", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@tagged("post_install", "-at_install")
class TestEscposService(TransactionCase):

    def test_image_to_escpos_structure(self):
        payload = escpos.image_to_escpos(_png_bytes(576, 40))
        self.assertTrue(payload.startswith(ESC_INIT))
        self.assertIn(GS_RASTER, payload)
        self.assertTrue(payload.endswith(FEED_AND_CUT))

    def test_image_is_scaled_to_dot_width(self):
        # 100px-wide source scaled to 384 dots -> raster width = 384/8 = 48 bytes.
        payload = escpos.image_to_escpos(_png_bytes(100, 50), dots_per_line=384)
        # GS v 0 m xL xH yL yH: xL/xH are bytes-per-line little-endian.
        idx = payload.index(GS_RASTER)
        x_l, x_h = payload[idx + 4], payload[idx + 5]
        self.assertEqual(x_l + 256 * x_h, 48)

    def test_text_to_escpos(self):
        payload = escpos.text_to_escpos("hello\n")
        self.assertTrue(payload.startswith(ESC_INIT))
        self.assertIn(b"hello", payload)
        self.assertTrue(payload.endswith(FEED_AND_CUT))

    def test_cashdrawer_pulse(self):
        payload = escpos.cashdrawer_pulse()
        self.assertTrue(payload.startswith(ESC_INIT))
        self.assertIn(DRAWER_PULSE, payload)

"""Image -> ESC/POS conversion and CUPS submission.

All ESC/POS knowledge (raster command, feed, cut, cash-drawer pulse) lives here,
server-side, per design decision D1 of the plan. Submission goes through the
``lp`` CLI (cups-client) rather than pycups, per Phase 0 decision in FINDINGS.md:
same IPP result, no C extension.
"""

import io
import logging
import os
import re
import subprocess

from escpos.printer import Dummy
from PIL import Image

_logger = logging.getLogger(__name__)

ESC_INIT = b"\x1b\x40"  # ESC @: reset printer state before each job

LP_TIMEOUT = 15  # seconds; lp only talks to cupsd, never waits on the printer


def _cups_host():
    return os.environ.get("POS_PRINT_CUPS_HOST", "cups:631")


class CupsSubmissionError(Exception):
    pass


def _new_document():
    doc = Dummy()
    doc._raw(ESC_INIT)
    return doc


def image_to_escpos(image_bytes, dots_per_line=576):
    """Convert a rendered receipt image (PNG/JPEG bytes) to ESC/POS bytes.

    The image is scaled to the printer's dot width; python-escpos dithers to
    1-bit and emits GS v 0 raster commands, followed by feed + full cut.
    """
    img = Image.open(io.BytesIO(image_bytes))
    img = img.convert("L")
    if img.width != dots_per_line:
        height = max(1, round(img.height * dots_per_line / img.width))
        img = img.resize((dots_per_line, height), Image.LANCZOS)
    doc = _new_document()
    doc.image(img, impl="bitImageRaster")
    doc.cut()
    return doc.output


def text_to_escpos(text):
    """Plain-text receipt (used by the Test Print button)."""
    doc = _new_document()
    doc.text(text)
    doc.cut()
    return doc.output


def cashdrawer_pulse():
    """ESC p pulse on drawer pin 2."""
    doc = _new_document()
    doc.cashdraw(2)
    return doc.output


def submit_to_cups(queue_name, payload, title=None):
    """Submit raw bytes to a CUPS queue, return the CUPS job id.

    CUPS accepting the job while the printer is offline is success: the queue
    retries and the job prints when the printer comes back.
    """
    cmd = ["lp", "-h", _cups_host(), "-d", queue_name, "-o", "raw"]
    if title:
        cmd += ["-t", title]
    try:
        proc = subprocess.run(
            cmd, input=payload, capture_output=True, timeout=LP_TIMEOUT
        )
    except FileNotFoundError:
        raise CupsSubmissionError("cups-client (lp) is not installed on the Odoo server")
    except subprocess.TimeoutExpired:
        raise CupsSubmissionError("timed out submitting the job to CUPS")
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        _logger.error("lp failed for queue %s: %s", queue_name, err)
        raise CupsSubmissionError(err or "lp failed")
    # stdout: "request id is receipt-42 (1 file(s))"
    out = proc.stdout.decode(errors="replace")
    match = re.search(r"request id is \S+-(\d+)", out)
    return int(match.group(1)) if match else 0

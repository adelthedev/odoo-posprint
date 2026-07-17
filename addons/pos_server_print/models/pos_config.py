from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    # Cashier receipt printer, printed server-side through CUPS. Kitchen
    # printers stay on pos.printer/printer_ids like every other printer type.
    # pos.config loads all fields to the POS frontend (pos.load.mixin default),
    # so this id is available as pos.config.raw.server_receipt_printer_id.
    server_receipt_printer_id = fields.Many2one(
        'pos.printer',
        string='Server Receipt Printer',
        domain=[('printer_type', '=', 'server_cups')],
        help="Receipts are rendered in the browser, sent to Odoo and printed "
             "through the server's CUPS queue — no direct browser-to-printer "
             "connection needed.",
    )

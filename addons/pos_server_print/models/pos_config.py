from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    # Cashier receipt printers, printed server-side through CUPS. Kitchen
    # printers stay on pos.printer/printer_ids like every other printer type.
    # pos.config loads all fields to the POS frontend (pos.load.mixin default),
    # so these ids are available as pos.config.raw.server_receipt_printer_ids.
    # With one printer configured receipts print to it directly; with several,
    # the cashier picks one at print time.
    server_receipt_printer_ids = fields.Many2many(
        'pos.printer',
        'pos_config_server_receipt_printer_rel', 'config_id', 'printer_id',
        string='Server Receipt Printers',
        domain=[('printer_type', '=', 'server_cups')],
        help="Receipts are rendered in the browser, sent to Odoo and printed "
             "through the server's CUPS queue — no direct browser-to-printer "
             "connection needed. If several printers are listed, the cashier "
             "is asked which one to use at print time.",
    )

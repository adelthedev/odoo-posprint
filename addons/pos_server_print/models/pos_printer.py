import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain

from ..services import escpos


class PosPrinter(models.Model):
    _inherit = 'pos.printer'

    printer_type = fields.Selection(
        selection_add=[('server_cups', 'Print via the Odoo server (CUPS)')],
        ondelete={'server_cups': 'set default'},
    )
    cups_queue_name = fields.Char(
        string='CUPS Queue',
        help="Name of the raw CUPS queue on the print server (e.g. 'receipt' or 'kitchen').",
    )
    dots_per_line = fields.Integer(
        string='Dots per Line',
        default=576,
        help="Printer head width in dots. 576 for 80 mm paper at 203 dpi, 384 for 58 mm. "
             "Receipts are scaled to this width; if output is clipped or too narrow, "
             "adjust this value.",
    )
    has_cashdrawer = fields.Boolean(
        string='Cash Drawer Connected',
        help="A cash drawer is plugged into this printer's DK port (opened via ESC p pulse).",
    )

    @api.model
    def _load_pos_data_domain(self, data, config):
        # Stock POS only loads preparation printers (config.printer_ids); the
        # frontend also needs the server receipt printers for the print-time
        # picker (name shown in the selection popup).
        return Domain.OR([
            super()._load_pos_data_domain(data, config),
            [('id', 'in', config.server_receipt_printer_ids.ids)],
        ])

    @api.constrains('printer_type', 'cups_queue_name', 'dots_per_line')
    def _constrains_server_cups(self):
        for record in self:
            if record.printer_type != 'server_cups':
                continue
            if not record.cups_queue_name:
                raise ValidationError(_("CUPS Queue cannot be empty for a server-printed printer."))
            if record.dots_per_line <= 0:
                raise ValidationError(_("Dots per Line must be a positive number."))

    def action_test_print(self):
        """Fire a canned receipt through the full path: escpos service -> CUPS queue."""
        self.ensure_one()
        if self.printer_type != 'server_cups':
            raise UserError(_("Test Print is only available for server-printed (CUPS) printers."))
        text = (
            "pos_server_print TEST\n"
            f"Printer: {self.name}\n"
            f"Queue: {self.cups_queue_name}\n"
            f"Dots/line: {self.dots_per_line}\n"
            f"Time: {fields.Datetime.now()}\n"
        )
        payload = escpos.text_to_escpos(text)
        job = self.env['pos.print.job'].create({
            'printer_id': self.id,
            'payload_type': 'escpos',
            'payload': base64.b64encode(payload),
            'order_ref': 'TEST PRINT',
        })
        job.submit(payload)
        if job.state == 'error':
            raise UserError(_("Test print failed: %s", job.error))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("Test print submitted to queue '%s' (CUPS job %s).",
                             self.cups_queue_name, job.cups_job_id),
            },
        }

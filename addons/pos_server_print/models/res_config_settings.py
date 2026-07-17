from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_server_receipt_printer_id = fields.Many2one(
        related='pos_config_id.server_receipt_printer_id', readonly=False)

import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services import escpos


class PosPrintJob(models.Model):
    """Audit log of server print jobs.

    This is not a queue — CUPS is the queue. A row records what was sent, by
    whom, and what CUPS said; reprinting resubmits the stored payload as a new
    row so the original stays intact.
    """
    _name = 'pos.print.job'
    _description = 'POS Server Print Job'
    _order = 'id desc'

    name = fields.Char(compute='_compute_name')
    printer_id = fields.Many2one('pos.printer', required=True, ondelete='restrict', index=True)
    session_id = fields.Many2one('pos.session', ondelete='set null')
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    order_ref = fields.Char(help="Order reference this job was printed for, if any.")
    payload_type = fields.Selection(
        [('image', 'Image'), ('escpos', 'ESC/POS bytes')],
        required=True, default='image', readonly=True,
    )
    payload = fields.Binary(attachment=True, readonly=True,
                            help="The ESC/POS bytes as submitted to CUPS; used for reprints.")
    cups_job_id = fields.Integer(string='CUPS Job', readonly=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('submitted', 'Submitted'), ('error', 'Error')],
        default='draft', required=True, readonly=True, index=True,
    )
    error = fields.Text(readonly=True)

    @api.depends('printer_id', 'order_ref')
    def _compute_name(self):
        for job in self:
            parts = [job.printer_id.name or _("Print job"), f"#{job.id or 0}"]
            if job.order_ref:
                parts.append(job.order_ref)
            job.name = " ".join(parts)

    def submit(self, payload):
        """Submit the given ESC/POS bytes to this job's CUPS queue and record the result."""
        self.ensure_one()
        try:
            cups_job_id = escpos.submit_to_cups(
                self.printer_id.cups_queue_name, payload,
                title=self.order_ref or f"pos-print-job-{self.id}",
            )
        except escpos.CupsSubmissionError as e:
            self.sudo().write({'state': 'error', 'error': str(e)})
            return False
        self.sudo().write({'state': 'submitted', 'cups_job_id': cups_job_id})
        return True

    def action_reprint(self):
        self.ensure_one()
        if not self.payload:
            raise UserError(_("This job has no stored payload to reprint."))
        payload = self.with_context(bin_size=False).payload
        raw = base64.b64decode(payload)
        copy = self.copy({'payload': payload, 'user_id': self.env.uid,
                          'order_ref': self.order_ref, 'state': 'draft',
                          'cups_job_id': 0, 'error': False})
        copy.submit(raw)
        if copy.state == 'error':
            raise UserError(_("Reprint failed: %s", copy.error))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("Reprint submitted to queue '%s' (CUPS job %s).",
                             copy.printer_id.cups_queue_name, copy.cups_job_id),
            },
        }

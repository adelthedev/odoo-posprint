import base64
import binascii

from odoo import _
from odoo.exceptions import AccessError, ValidationError
from odoo.http import Controller, request, route

from ..services import escpos

OPEN_SESSION_STATES = ('opening_control', 'opened', 'closing_control')


class PosServerPrintController(Controller):

    @route('/pos_server_print/job', type='jsonrpc', auth='user', methods=['POST'])
    def print_job(self, printer_id, payload_type, data, order_ref=False):
        """Convert the payload to ESC/POS if needed and submit it to CUPS.

        Returns fast (plan D4): CUPS accepting the job is success even if the
        printer is offline — the queue retries. Only a CUPS submission failure
        is an error.
        """
        printer, session = self._get_validated_printer(printer_id)
        if payload_type not in ('image', 'escpos'):
            raise ValidationError(_("Unsupported payload type: %s", payload_type))
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, TypeError):
            raise ValidationError(_("Payload is not valid base64."))
        if not raw:
            raise ValidationError(_("Payload is empty."))

        if payload_type == 'image':
            try:
                payload = escpos.image_to_escpos(raw, printer.dots_per_line)
            except Exception:
                raise ValidationError(_("Payload could not be decoded as an image."))
        else:
            payload = raw

        job = request.env['pos.print.job'].sudo().create({
            'printer_id': printer.id,
            'session_id': session.id if session else False,
            'user_id': request.env.uid,
            'order_ref': order_ref or False,
            'payload_type': payload_type,
            'payload': base64.b64encode(payload),
        })
        # On failure, return the error instead of raising: raising would roll
        # back the transaction and lose the audit row recording the failure.
        job.submit(payload)
        return {'job_id': job.id, 'cups_job_id': job.cups_job_id,
                'state': job.state, 'error': job.error or False}

    @route('/pos_server_print/cashbox', type='jsonrpc', auth='user', methods=['POST'])
    def open_cashbox(self, printer_id):
        printer, session = self._get_validated_printer(printer_id)
        if not printer.has_cashdrawer:
            raise ValidationError(_("No cash drawer is configured on this printer."))
        payload = escpos.cashdrawer_pulse()
        job = request.env['pos.print.job'].sudo().create({
            'printer_id': printer.id,
            'session_id': session.id if session else False,
            'user_id': request.env.uid,
            'order_ref': 'CASHDRAWER',
            'payload_type': 'escpos',
            'payload': base64.b64encode(payload),
        })
        job.submit(payload)
        return {'job_id': job.id, 'cups_job_id': job.cups_job_id,
                'state': job.state, 'error': job.error or False}

    def _get_validated_printer(self, printer_id):
        """Plan D5: caller must be a POS user, the printer must be a server_cups
        printer attached to a POS config that currently has an open session.
        The client only ever references the printer record id — queue names and
        printer addresses never travel to the browser.
        """
        env = request.env
        if not env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_("You must be a Point of Sale user to print."))
        printer = env['pos.printer'].sudo().browse(int(printer_id))
        if not printer.exists() or printer.printer_type != 'server_cups':
            raise ValidationError(_("Unknown printer."))
        if printer.company_id and printer.company_id not in env.user.company_ids:
            raise AccessError(_("You are not allowed to use this printer."))
        configs = printer.pos_config_ids | env['pos.config'].sudo().search(
            [('server_receipt_printer_id', '=', printer.id)])
        session = env['pos.session'].sudo().search(
            [('config_id', 'in', configs.ids), ('state', 'in', OPEN_SESSION_STATES)],
            limit=1)
        if not session:
            raise AccessError(_("This printer has no open Point of Sale session."))
        return printer, session

import base64
import io
import json
from unittest.mock import patch

from PIL import Image

from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon

from ..services import escpos


@tagged('post_install', '-at_install')
class TestPosServerPrintController(TestPointOfSaleHttpCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.printer = cls.env['pos.printer'].create({
            'name': 'Server receipt printer',
            'printer_type': 'server_cups',
            'cups_queue_name': 'receipt',
        })
        cls.main_pos_config.server_receipt_printer_id = cls.printer
        cls.no_pos_user = cls.env['res.users'].create({
            'name': 'No PoS rights',
            'login': 'no_pos_user',
            'password': 'no_pos_user',
            'group_ids': [(4, cls.env.ref('base.group_user').id)],
        })

    def _rpc(self, url, params):
        payload = {'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1}
        response = self.url_open(
            url, data=json.dumps(payload), headers={'Content-Type': 'application/json'})
        return response.json()

    def _image_b64(self):
        img = Image.new('L', (200, 40), 255)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return base64.b64encode(buf.getvalue()).decode()

    def _print_params(self, **overrides):
        params = {
            'printer_id': self.printer.id,
            'payload_type': 'image',
            'data': self._image_b64(),
            'order_ref': 'POS/0001',
        }
        params.update(overrides)
        return params

    def test_print_job_happy_path(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.authenticate('pos_user', 'pos_user')
        with patch.object(escpos, 'submit_to_cups', return_value=42) as mock_submit:
            res = self._rpc('/pos_server_print/job', self._print_params())
        self.assertNotIn('error', res, res.get('error'))
        result = res['result']
        self.assertEqual(result['state'], 'submitted')
        self.assertEqual(result['cups_job_id'], 42)

        mock_submit.assert_called_once()
        queue_name, payload = mock_submit.call_args.args[:2]
        self.assertEqual(queue_name, 'receipt')
        self.assertTrue(payload.startswith(b'\x1b\x40'))
        self.assertIn(b'\x1d\x76\x30', payload)  # GS v 0 raster

        job = self.env['pos.print.job'].browse(result['job_id'])
        self.assertEqual(job.printer_id, self.printer)
        self.assertEqual(job.order_ref, 'POS/0001')
        self.assertEqual(job.state, 'submitted')
        self.assertEqual(job.session_id, self.main_pos_config.current_session_id)

    def test_cups_failure_returns_error_and_keeps_audit_row(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.authenticate('pos_user', 'pos_user')
        with patch.object(escpos, 'submit_to_cups',
                          side_effect=escpos.CupsSubmissionError('queue down')):
            res = self._rpc('/pos_server_print/job', self._print_params())
        self.assertNotIn('error', res, res.get('error'))
        result = res['result']
        self.assertEqual(result['state'], 'error')
        self.assertEqual(result['error'], 'queue down')
        job = self.env['pos.print.job'].browse(result['job_id'])
        self.assertTrue(job.exists())
        self.assertEqual(job.state, 'error')
        self.assertEqual(job.error, 'queue down')

    def test_no_open_session_rejected(self):
        self.authenticate('pos_user', 'pos_user')
        with patch.object(escpos, 'submit_to_cups', return_value=42) as mock_submit:
            res = self._rpc('/pos_server_print/job', self._print_params())
        self.assertIn('error', res)
        mock_submit.assert_not_called()
        self.assertFalse(self.env['pos.print.job'].search([('printer_id', '=', self.printer.id)]))

    def test_unknown_printer_rejected(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.authenticate('pos_user', 'pos_user')
        with patch.object(escpos, 'submit_to_cups', return_value=42) as mock_submit:
            res = self._rpc('/pos_server_print/job', self._print_params(printer_id=999999))
        self.assertIn('error', res)
        mock_submit.assert_not_called()

    def test_non_pos_user_rejected(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.authenticate('no_pos_user', 'no_pos_user')
        with patch.object(escpos, 'submit_to_cups', return_value=42) as mock_submit:
            res = self._rpc('/pos_server_print/job', self._print_params())
        self.assertIn('error', res)
        mock_submit.assert_not_called()

    def test_bad_payload_rejected(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.authenticate('pos_user', 'pos_user')
        with patch.object(escpos, 'submit_to_cups', return_value=42) as mock_submit:
            res = self._rpc('/pos_server_print/job', self._print_params(data='not-base64!!'))
            self.assertIn('error', res)
            res = self._rpc('/pos_server_print/job', self._print_params(payload_type='pdf'))
            self.assertIn('error', res)
        mock_submit.assert_not_called()

    def test_cashbox_requires_cashdrawer(self):
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.authenticate('pos_user', 'pos_user')
        params = {'printer_id': self.printer.id}
        with patch.object(escpos, 'submit_to_cups', return_value=7) as mock_submit:
            res = self._rpc('/pos_server_print/cashbox', params)
            self.assertIn('error', res)
            mock_submit.assert_not_called()

            self.printer.has_cashdrawer = True
            res = self._rpc('/pos_server_print/cashbox', params)
        self.assertNotIn('error', res, res.get('error'))
        self.assertEqual(res['result']['cups_job_id'], 7)
        _queue, payload = mock_submit.call_args.args[:2]
        self.assertIn(b'\x1b\x70', payload)  # ESC p drawer pulse

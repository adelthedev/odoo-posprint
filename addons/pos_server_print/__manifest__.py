# Part of pos_server_print. See PLAN-pos-server-print.md at the repo root.
{
    'name': 'POS Server Printing (CUPS)',
    'summary': 'Print POS receipts and kitchen tickets server-side through CUPS raw queues',
    'description': """
Server-side ESC/POS printing for the Point of Sale.

The browser sends the rendered receipt to Odoo over same-origin HTTP; the server
converts it to ESC/POS raster and submits it to a CUPS raw queue. No direct
browser-to-printer connection is needed, so tablets work regardless of browser
LAN-access restrictions.
""",
    'category': 'Sales/Point of Sale',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['point_of_sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/pos_printer_views.xml',
        'views/pos_print_job_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_server_print/static/src/**/*',
        ],
    },
    'installable': True,
}

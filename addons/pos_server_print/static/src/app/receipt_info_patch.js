import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { ReceiptHeader } from "@point_of_sale/app/screens/receipt_screen/receipt/receipt_header/receipt_header";

patch(PosOrder.prototype, {
    /**
     * @override The stock method keeps only the first word of the user's
     * name, so "POS 1" and "POS 2" both print as "Served by: POS". Print the
     * full name (employee first, should pos_hr ever be enabled).
     */
    getCashierName() {
        return this.employee_id?.name || this.user_id?.name;
    },
});

patch(ReceiptHeader.prototype, {
    /**
     * @override Prefix pos_restaurant's "Table 5, Guests: 2" line with the
     * floor, so dine-in receipts read "Main Floor, Table 5, Guests: 2".
     */
    get tableName() {
        const name = super.tableName;
        const floor = (this.order.table_id || this.order.self_ordering_table_id)?.floor_id?.name;
        return name && floor ? `${floor}, ${name}` : name;
    },
});

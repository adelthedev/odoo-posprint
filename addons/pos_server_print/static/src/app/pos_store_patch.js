import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { ServerPrinter } from "@pos_server_print/app/server_printer";

patch(PosStore.prototype, {
    /**
     * @override Preparation (kitchen) printers of type server_cups.
     */
    createPrinter(config) {
        if (config.printer_type === "server_cups") {
            return new ServerPrinter({ printerId: config.id });
        }
        return super.createPrinter(...arguments);
    },

    /**
     * @override Cashier receipt printer, mirroring how the stock code wires
     * the Epson ePOS printer here.
     */
    async afterProcessServerData() {
        await super.afterProcessServerData(...arguments);
        const printerId = this.config.raw.server_receipt_printer_id;
        if (printerId) {
            this.hardwareProxy.printer = new ServerPrinter({ printerId });
        }
    },
});

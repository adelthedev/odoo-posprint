import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
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
     * The config's server receipt printers, as loaded pos.printer records.
     */
    getServerReceiptPrinters() {
        const ids = this.config.raw.server_receipt_printer_ids || [];
        return ids.map((id) => this.models["pos.printer"].get(id)).filter(Boolean);
    },

    /**
     * @override Cashier receipt printer, mirroring how the stock code wires
     * the Epson ePOS printer here. With several printers configured the first
     * is the default; printReceipt() asks the cashier and swaps it per print.
     */
    async afterProcessServerData() {
        await super.afterProcessServerData(...arguments);
        const printers = this.getServerReceiptPrinters();
        if (printers.length) {
            this.hardwareProxy.printer = new ServerPrinter({ printerId: printers[0].id });
        }
    },

    /**
     * @override Ask which server printer to use when more than one is
     * configured. Cancelling the popup cancels the print.
     */
    async printReceipt() {
        const printers = this.getServerReceiptPrinters();
        if (printers.length > 1) {
            const printer = await makeAwaitable(this.dialog, SelectionPopup, {
                title: _t("Select the receipt printer"),
                list: printers.map((p) => ({ id: p.id, label: p.name, item: p })),
            });
            if (!printer) {
                return false;
            }
            this.hardwareProxy.printer = new ServerPrinter({ printerId: printer.id });
        }
        return await super.printReceipt(...arguments);
    },
});

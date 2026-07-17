import { _t } from "@web/core/l10n/translation";
import { ConnectionLostError, rpc } from "@web/core/network/rpc";
import { BasePrinter } from "@point_of_sale/app/utils/printer/base_printer";

/**
 * Printer whose transport is the Odoo server: the rendered receipt is POSTed
 * same-origin to /pos_server_print/job and the server pushes it through CUPS.
 * No retries and no state polling here — CUPS owns the queue.
 */
export class ServerPrinter extends BasePrinter {
    setup({ printerId }) {
        super.setup(...arguments);
        this.printerId = printerId;
    }

    /**
     * @override PNG instead of JPEG: lossless and smaller for B/W receipts.
     */
    processCanvas(canvas) {
        return canvas.toDataURL("image/png").replace("data:image/png;base64,", "");
    }

    /**
     * @override
     */
    async sendPrintingJob(img) {
        try {
            const res = await rpc("/pos_server_print/job", {
                printer_id: this.printerId,
                payload_type: "image",
                data: img,
            });
            if (res.state !== "submitted") {
                return { result: false, canRetry: true, errorCode: res.error };
            }
            return { result: true, jobId: res.job_id, cupsJobId: res.cups_job_id };
        } catch (error) {
            if (error instanceof ConnectionLostError) {
                // BasePrinter maps this to its offline error dialog.
                throw error;
            }
            return {
                result: false,
                canRetry: true,
                errorCode: error?.data?.message || error?.message,
            };
        }
    }

    /**
     * @override
     */
    openCashbox() {
        // Fire and forget, like the other printer classes.
        rpc("/pos_server_print/cashbox", { printer_id: this.printerId }).catch(() => {});
    }

    /**
     * @override Stock message talks about the IoT box; ours is the server.
     */
    getActionError() {
        return {
            successful: false,
            canRetry: true,
            message: {
                title: _t("Printing failed"),
                body: _t("Could not reach the print server. Please check your connection and retry."),
            },
        };
    }

    /**
     * @override
     */
    getResultsError(printResult) {
        return {
            successful: false,
            canRetry: true,
            errorCode: printResult?.errorCode,
            message: {
                title: _t("Printing failed"),
                body:
                    printResult?.errorCode ||
                    _t("The print server could not process the receipt."),
            },
        };
    }
}

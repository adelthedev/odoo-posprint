# POS Server Printing (CUPS)

Server-side ESC/POS printing for the Odoo 19 Point of Sale. The browser sends
the rendered receipt to Odoo over same-origin HTTP; the server converts it to
ESC/POS raster and submits it to a raw CUPS queue. No direct browser-to-printer
connection is needed, so tablets work regardless of browser LAN-access
restrictions.

## Setup overview

1. **CUPS queues** — one raw queue per physical printer. The `cups` container
   creates one queue per `PRINTER_<NAME>_URI` variable in `.env` (queue name =
   `<name>` lowercased: `PRINTER_BAR_URI=socket://192.168.1.52:9100` → queue
   `bar`). Add as many as you have printers. Removing a variable does **not**
   delete its queue — drop it with `lpadmin -x <queue>` or in the CUPS web UI.
2. **Printer records** — in the backend, create a `pos.printer` with type
   *"Print via the Odoo server (CUPS)"*, pointing at a queue name. Per printer:
   `dots_per_line` (576 for 80 mm paper at 203 dpi, 384 for 58 mm), cash-drawer
   flag, and a **Test Print** button that exercises the full path.
3. **Receipt printers** — Settings → Point of Sale → *Server Receipt Printers*:
   the list of printers this shop's cashier receipts may go to.
4. **Kitchen printers** — unchanged from stock Odoo: `pos.printer` records on
   the config's *Order Printers* list, routed by product category. They just
   gain the new `server_cups` type as a transport.

## Which prints go where

The POS frontend has a single "current receipt printer" slot
(`hardwareProxy.printer`); this module fills it and intercepts receipt
printing. The resulting behavior, by flow:

| Flow | Behavior |
|---|---|
| Receipt printing — Print Full Receipt, automatic printing, reprint from the Orders screen, restaurant bill | **One** configured printer: prints straight to it, no popup. **Several**: a *"Select the receipt printer"* popup asks the cashier on every print; cancelling the popup cancels the print. |
| Daily sale details report (hamburger menu) | Always the **default printer** — the *first* printer in the shop's *Server Receipt Printers* list. No popup. |
| Register-closing report (closing popup print button) | Same: always the default (first) printer, no popup. |
| Cash drawer pulse after a cash payment | Same slot, so the default (first) printer — only if that printer has *Cash Drawer Connected* set. |
| Kitchen / preparation tickets | Never affected by the receipt list: routed by product category to the config's order printers, as in stock Odoo. |

Rules of thumb that follow:

- **Order the *Server Receipt Printers* list deliberately** — the first entry
  is the silent default for management prints (sale details, closing report)
  and the cash drawer.
- The picker only ever offers printers from the shop's own list, not every
  CUPS queue: printer records carry rendering parameters (`dots_per_line`,
  queue name, drawer) that a bare queue name would not.
- Stock POS hides its print buttons entirely when no printer is wired; with at
  least one server receipt printer configured they always show.

## How it works (one paragraph)

The frontend patches `PosStore`: `createPrinter()` returns a `ServerPrinter`
for `server_cups` kitchen printers, `afterProcessServerData()` wires the first
configured receipt printer into `hardwareProxy.printer`, and `printReceipt()`
shows the selection popup when the shop lists more than one. `ServerPrinter`
POSTs the rendered receipt (PNG) to `/pos_server_print/job` with only the
`pos.printer` record id — queue names and addresses never reach the browser.
The controller validates the caller is a POS user and the printer belongs to a
config with an open session, converts the image to ESC/POS raster, records a
`pos.print.job` audit row (reprintable from the backend), and submits to CUPS.
CUPS owns queuing, serialization and retries; a job accepted by CUPS counts as
success even if the printer is momentarily offline.

## Operational notes

- Job history: *Point of Sale → Orders → Server Print Jobs* — every submission
  with payload, state and CUPS job id; failed or lost prints can be resubmitted
  with *Reprint*.
- Dev: `docker compose --profile dev up -d` adds an ESC/POS emulator; jobs land
  as `.bin` files in `./emulator-data/`. CUPS web UI: http://localhost:6631.
- Tests (fresh throwaway db each run; `--http-port` because the main server
  already binds 8069 in the container):

  ```sh
  docker exec odoo-db psql -U odoo -d postgres \
      -c 'DROP DATABASE IF EXISTS psp_test2 WITH (FORCE);'
  docker compose exec -T odoo odoo --db_host=db --db_user=odoo \
      --db_password=@fghanDish -d psp_test2 -i pos_server_print \
      --test-enable --test-tags=/pos_server_print --stop-after-init \
      --http-port=8899
  ```

  The suite covers the ESC/POS service, the controller's auth/validation, and
  the printer loading domain.

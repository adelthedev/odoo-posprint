# FINDINGS — pos_server_print implementation notes

Discovered facts recorded during implementation, per PLAN-pos-server-print.md.
Verified on 2026-07-17 against `odoo:19` image (Odoo Server 19.0-20260630, Ubuntu 24.04,
Python 3.12) and `debian:bookworm-slim` CUPS 2.4.x.

## Phase 0 — transport chain (verified working on Mac dev)

- **Raw queues on CUPS 2.4:** `-m raw` is deprecated. Creating the queue with **no
  `-m`/`-P` at all** (`lpadmin -p receipt -E -v socket://... -o printer-is-shared=true
  -o printer-error-policy=retry-job`) yields a filterless queue; submitting with
  `lp -o raw` passes bytes through untouched (verified byte-for-byte via emulator dump).
- **`printer-is-shared=true` is required**, not `false` as the plan sketched: the odoo
  container submits over IPP from another host, and cupsd rejects remote submission to
  non-shared queues with "The printer or class does not exist". Sharing is confined to
  the compose network (631 is only published to localhost).
- **`ServerAlias *` is required** in cupsd.conf: cupsd validates the HTTP `Host:` header
  and rejects requests addressed to `cups:631` ("invalid Host: field") without it.
- **Retry-on-offline:** with the queue's socket backend, a job submitted while the
  printer is unreachable stays in the queue and prints when the printer returns
  (verified: stopped emulator, submitted, restarted → job arrived ~5 s later).
  `ErrorPolicy retry-job` + `JobRetryInterval 15` + `JobRetryLimit 240` in cupsd.conf
  cover mid-job failures.
- **Ordering:** 5 jobs submitted in rapid succession arrive as 5 separate connections,
  in submission order, no interleaving (one TCP connection per job).
- **Submission from Python: `lp` subprocess, not pycups.** Decision per plan D2/module
  structure: `lp -h cups:631 -d <queue> -o raw <file>` via `subprocess` — avoids the
  pycups C extension; cups-client is in the odoo image. `lp` prints
  `request id is receipt-3 (1 file(s))` on success → parse the CUPS job id from stdout.
- **CUPS web UI:** published at `http://localhost:6631` (631 clashes with macOS's own
  cupsd on the dev Mac; port is `CUPS_WEB_PORT` in `.env`).
- **python-escpos pinned at 3.1** (latest stable on PyPI as of 2026-07); imports and
  generates bytes fine inside the odoo image (`escpos.printer.Dummy`).

## Phase 1 — Odoo 19 POS internals

All paths relative to `/usr/lib/python3/dist-packages/odoo/addons/` inside the image.
There is **no separate `pos_epson_printer` module in 19** — Epson ePOS support lives
directly in `point_of_sale`.

### Q1. Printer abstraction (JS)

- Base class: `point_of_sale/static/src/app/utils/printer/base_printer.js` —
  `BasePrinter` with `printReceipt(receiptEl)`, `sendPrintingJob(image)` (abstract),
  `openCashbox()` (abstract), `processCanvas(canvas)`, and error-shape helpers
  `getActionError() / getOfflineError() / getResultsError(printResult)`.
- Concrete: `epson_printer.js` (`EpsonPrinter extends BasePrinter`) and
  `hw_printer.js` (`HWPrinter`, IoT proxy) in the same directory.
- A printer's `sendPrintingJob(image)` must resolve to an object where
  `result: true` means success; `{result: false, errorCode, canRetry}` routes into
  `getResultsError()` and the POS shows `RetryPrintPopup`
  (`pos_printer_service.js` catches and offers Retry / Download).

### Q2. Receipt → bytes/pixels

Confirmed raster: `BasePrinter.printReceipt` calls
`htmlToCanvas(receipt, { addClass: "pos-receipt-print" })` (from
`app/services/render_service.js`), then `this.processCanvas(canvas)`.
Default `processCanvas` returns **base64 JPEG without the data-URI prefix**
(`canvas.toDataURL("image/jpeg")`). EpsonPrinter overrides it to build ePOS-XML with
dithered raster. → Our printer overrides `processCanvas` to emit base64 **PNG**
(lossless, smaller for B/W receipts) and POSTs it; server does image→ESC/POS (plan D1).

### Q3. Printer configuration (Python)

- `pos.printer` (`point_of_sale/models/pos_printer.py`): `printer_type` selection
  `[('iot', ...), ('epson_epos', ...)]`, `proxy_ip`, `epson_printer_ip`,
  `product_categories_ids` (kitchen routing), `pos_config_ids` m2m to configs.
  Reaches JS via `pos.load.mixin`: `_load_pos_data_domain` limits to
  `config.printer_ids`, `_load_pos_data_fields` whitelists
  `['id','name','proxy_ip','product_categories_ids','printer_type','epson_printer_ip']`.
- The **cashier receipt printer is separate**: `pos.config.epson_printer_ip` (+ boolean
  `other_devices`); `res.config.settings` exposes them as related fields
  (`pos_epson_printer_ip`, settings view block `id="pos_other_devices"` in
  `views/res_config_settings_views.xml`).
- `pos.config` uses the mixin default `_load_pos_data_fields → []`, and
  `_load_pos_data_read` does `read([], load=False)` → **every pos.config field is
  automatically available in JS** as `pos.config.raw.<field>`; new fields need no
  loader changes. m2o fields arrive as plain ids (`load=False`).

### Q4. Registering a new printer type end-to-end

- Kitchen/preparation printers: `pos_store.js` `setup()` (line ~451) iterates
  `this.models["pos.printer"]`, calls `this.createPrinter(printer.raw)` and pushes to
  `this.unwatched.printers`. `createPrinter(config)` (line ~1283) dispatches on
  `config.printer_type === "epson_epos"` else falls back to `HWPrinter`.
  → **patch `PosStore.prototype.createPrinter`** for `printer_type === "server_cups"`.
- Cashier receipt printer: `pos_store.js` `afterProcessServerData()` (line ~743):
  `if (this.config.other_devices && this.config.epson_printer_ip)
  this.hardwareProxy.printer = new EpsonPrinter(...)`.
  `hardware_proxy.printer` is what `pos_printer_service` uses for receipts, and
  `hardware_proxy.openCashbox()` calls `printer.openCashbox()` when
  `config.iface_cashdrawer` is set (connectionInfo starts at `"init"`, which passes the
  connected check when no IoT proxy is used).
  → **patch `afterProcessServerData`** to set `hardwareProxy.printer = new
  ServerPrinter(...)` when our config field is set.
- Backend form view to extend: `point_of_sale.view_pos_printer_form`
  (`views/pos_printer_view.xml`); fields toggle on `printer_type` via `invisible`.
- Assets bundle: `point_of_sale._assets_pos` (confirmed in `pos_restaurant`
  manifest); patches via `patch()` from `@web/core/utils/patch`.

### Q5. RPC convention

- JSON controllers in 19 use `type='jsonrpc'` (not `type='json'`; see
  `point_of_sale/controllers/main.py` `/pos/ping`).
- JS side calls them with `rpc(url, params)` from `@web/core/network/rpc` — carries the
  session cookie (same-origin), throws `RPCError` on server exceptions and
  `ConnectionLostError` when offline (BasePrinter already maps the latter).

### Implementation decisions derived from discovery

- New `printer_type` value **`server_cups`** on `pos.printer` + fields `cups_queue_name`,
  `dots_per_line` (default 576), `has_cashdrawer`.
- Cashier receipt printer: new m2o **`pos.config.server_receipt_printer_id`**
  (domain `printer_type = server_cups`), mirroring how `epson_printer_ip` lives on
  pos.config; loaded to JS automatically (Q3).
- Client only ever sends the **pos.printer record id** — queue names/IPs never reach
  the browser (plan D5).
- Controller validates: printer exists, is `server_cups`, and belongs to a pos.config
  (via `pos_config_ids` or as `server_receipt_printer_id`) that has an **open
  session** — not necessarily the caller's own session, since several
  cashiers/tablets legitimately share one session.
- CUPS server address comes from env `POS_PRINT_CUPS_HOST` (default `cups:631`).

## Phase 2–4 — implementation & test notes

- **`config/odoo.conf` quoting bug (pre-existing, surfaced by fixing the mount):** the
  compose file used to mount `./config` onto a path the official image never reads, so
  the file was inert. Once mounted at `/etc/odoo/odoo.conf`, the odoo:19 entrypoint
  no longer overrides db params that appear in the config file — Odoo reads them via
  configparser, which keeps quotes literally, so `db_password = "@fghanDish"` sent the
  quotes as part of the password → main server crash-looped on DB auth. Fix: no quotes
  in odoo.conf values.
- **Controller failure contract:** on CUPS submission failure the endpoint returns
  `{state: 'error', error}` instead of raising — raising rolls back the request
  transaction and would delete the `pos.print.job` audit row recording the failure
  (plan D3). The JS treats `state != 'submitted'` as a failed print (retry dialog).
- **Odoo 19 search-view grammar:** `<group expand="0" string="...">` inside `<search>`
  is rejected by the RelaxNG validator. Group-by blocks are a bare `<group>` with
  `<filter ... domain="[]" context="{'group_by': ...}"/>` (see stock
  `pos_order_view.xml`).
- **Running module tests** (fresh db each time; `--http-port` needed because the main
  server already binds 8069 inside the container; `WITH (FORCE)` because the main
  server holds pooled connections to the db):
  ```bash
  docker compose exec -T db psql -U odoo -d postgres -c "DROP DATABASE IF EXISTS psp_test2 WITH (FORCE);"
  docker compose exec -T odoo odoo --db_host=db --db_user=odoo --db_password=@fghanDish \
      -d psp_test2 -i pos_server_print --test-enable --test-tags=/pos_server_print \
      --stop-after-init --http-port=8899 --log-level=info
  ```
  Result 2026-07-17: **11 tests, 0 failed, 0 errors** (4 escpos-service unit tests,
  7 controller HTTP tests with CUPS mocked).
- **Deploy-time answers from the user (2026-07-17):** no cash drawer (the
  `/pos_server_print/cashbox` endpoint stays dormant behind `has_cashdrawer = False`);
  both printers are 80 mm, so the `dots_per_line` default of 576 is correct as-is.
- **Reconciled with `origin/master` commit `97deca5` ("make sure postgres data is
  preserved"):** production postgres data lives in the **named volume `odoo-db-data`**
  (not a `./postgres-data` bind mount) and the config dir is mounted as
  `./config:/etc/odoo`. The compose file here keeps both, so pulling this branch on
  prod does not touch the database volume. That commit had also already un-quoted
  the odoo.conf passwords, independently confirming the quoting bug below.
- **End-to-end verified on dev:** `pos.printer.action_test_print` from odoo shell →
  escpos service → `lp` → CUPS `receipt` queue → emulator received the canned receipt
  (CUPS job id recorded on the `pos.print.job` row). The POS JS bundle
  (`point_of_sale._assets_pos`) compiles with both module files included.

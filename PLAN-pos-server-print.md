# PLAN — `pos_server_print`: Server-side POS receipt printing for Odoo (WSL2 + CUPS)

> **Audience:** Claude Code, implementing this in the user's Odoo 19 Community dev environment.
> **Prime directive:** Do NOT assume Odoo internal file paths, class names, or method names from training
> data. Odoo's POS frontend changes significantly between versions. Every hook point marked
> `[DISCOVER]` must be verified by grepping the actual installed Odoo source before writing code
> that depends on it. Record findings in `FINDINGS.md` as you go.

---

## 1. Problem statement

- Odoo 19 Community runs inside WSL2 on a Windows PC. Tablets on the same Wi-Fi open Odoo POS
  in the browser (`http://<WINDOWS_LAN_IP>:8069`).
- Stock Odoo POS printing is **client-side**: the browser tries to connect directly to the
  ESC/POS printer. Chrome on Android blocks WebSocket/HTTP connections to LAN devices
  (Private Network Access enforcement, no user-facing opt-out anymore). Printing from tablets
  is therefore impossible with stock Odoo.
- Both printers (one receipt, one kitchen — confirm with user) are ESC/POS thermal printers
  connected via **Ethernet**, reachable on TCP port 9100 (JetDirect/raw).

## 2. Solution architecture

Move the printer transport server-side. The browser only talks to Odoo over normal same-origin
HTTP. CUPS (running inside WSL alongside Odoo) is the print spooler — it owns queuing,
serialization, retries, and job history, so we don't build a custom queue/worker.

```
Tablet browser (Chrome, any device)
    │  same-origin HTTP POST /pos_server_print/job   (receipt payload)
    ▼
Odoo 19 (WSL2)
    ├── custom module `pos_server_print`
    │     ├── JS: custom printer class registered in POS (replaces direct-to-printer transport)
    │     ├── controller: receives job, logs it, submits to CUPS
    │     └── models: printer config + job audit log
    ▼
CUPS (WSL2, raw queues)          ← the queue. One connection per printer, strict ordering.
    │  socket://<printer_ip>:9100
    ▼
ESC/POS printers (Ethernet)
```

Why CUPS raw queues instead of opening TCP sockets from Python:
- Cheap ESC/POS printers accept ~1 TCP connection at a time; concurrent jobs interleave or drop.
- CUPS serializes per-queue, retries when the printer is offline, keeps job history, and has a
  management UI at `http://localhost:631`. We'd otherwise reimplement all of that badly.
- "Raw" queues mean no driver/PPD/filtering — bytes pass through untouched, which is exactly
  right for ESC/POS.

## 2b. Dev/prod topology — THIS SHAPES EVERYTHING BELOW

Development happens on **macOS** (repo + Dockerfile pin all versions). Deployment is **Docker
inside WSL2 on the Windows PC** (confirmed by the user — not bare WSL).

Consequence: **CUPS must live inside the Docker composition, not on the WSL host.** Otherwise
dev and prod diverge and the module is only testable on-site. Target composition:

```
docker-compose.yml (identical dev & prod, differing only in .env)
├── odoo        (Odoo 19 + cups-client + python-escpos; submits jobs to the cups service
│                over IPP — `lp -h cups:631 -d receipt -o raw ...` or
│                pycups `cups.Connection(host="cups")`)
├── cups        (cupsd sidecar; entrypoint script creates raw queues from env vars:
│                PRINTER_RECEIPT_URI, PRINTER_KITCHEN_URI)
├── db          (postgres, already exists)
└── escpos-emulator   (DEV ONLY, compose profile `dev`: listens on :9100, dumps received
                       bytes to a shared volume and decodes ESC/POS raster to PNG so
                       receipts are visually inspectable without hardware)
```

Env-driven config, never hardcoded:

| Variable | Dev (Mac) | Prod (WSL) |
|---|---|---|
| `PRINTER_RECEIPT_URI` | `socket://escpos-emulator:9100` | `socket://<receipt_ip>:9100` |
| `PRINTER_KITCHEN_URI` | `socket://escpos-emulator:9100` | `socket://<kitchen_ip>:9100` |

Notes:
- Docker containers (Mac and WSL alike) have outbound NAT to the LAN, so in prod the `cups`
  container reaches the printers directly — no port mapping needed for printing. The only
  published port that matters for tablets is Odoo's 8069 (plus the existing Windows
  `netsh portproxy` from the LAN IP into WSL).
- The emulator can be trivial: a small Python service that accepts TCP on 9100, appends each
  connection's bytes to a timestamped file, and (nice-to-have) parses ESC/POS raster into a
  PNG per job. Even the dump-only version validates queuing/ordering; build the PNG decoding
  only if receipt-layout debugging demands it.
- Expose the `cups` container's 631 to localhost in both envs — the CUPS web UI is the ops
  dashboard for stuck jobs.

## 3. Environment facts (verify, don't trust)

| Fact | Where | How to verify |
|---|---|---|
| Odoo 19 CE, Dockerized, versions pinned in repo Dockerfile | dev + prod | inspect Dockerfile/compose |
| Prod is Docker-in-WSL2 | prod | confirmed by user |
| Containers can reach printers from WSL | prod, on-site | `docker compose exec cups nc -zv <PRINTER_IP> 9100` |
| Windows LAN IP is static | prod | router reservation — tablets depend on it |
| Tablets reach Odoo | prod | tablet browser loads `http://<WINDOWS_LAN_IP>:8069` |

The printer-reachability check is prod/on-site only (dev uses the emulator). If it fails
(VPN/firewall edge cases), fallback is WSL mirrored networking (`networkingMode=mirrored`
in `.wslconfig`). The whole architecture rests on that one check — it gates go-live, and
nothing in dev depends on it.

## 4. Settled facts and remaining unknowns

Settled — do not ask the user about these:
- **Transport:** both printers accept raw ESC/POS over TCP 9100 (confirmed against real
  hardware). No IPP, no drivers, no vendor SDKs.
- **Printer IPs:** deploy-time `.env` values only (Phase 5, on-site). Dev never needs them —
  everything runs against the emulator. Never referenced in code or asked for during dev.
- **Paper/dot width:** do NOT hardcode and do NOT block on knowing the models. Make it an
  integer field on the printer record, `dots_per_line`, default **576** (typical 80 mm @
  203 dpi). The escpos service scales the receipt image to this width. If output is clipped
  or narrow on the real hardware, it's a settings change, not a code change. (Common values:
  576 for 80 mm, 384 for 58 mm.)

Remaining unknowns (ask once, at deploy time, none block dev):
1. Cash drawer on the receipt printer? → determines whether the `ESC p` pulse
   endpoint/action gets built (it's small; can also be built speculatively behind a
   boolean field `has_cashdrawer` on the printer record and simply left disabled).
2. Actual paper width per printer → set `dots_per_line` if not 80 mm.

---

## Phase 0 — Environment setup (no Odoo code yet). Runs on the Mac.

1. Add the `cups` service to the compose file: a small image (debian/alpine base) with
   `cups` + `cups-client`, an entrypoint that runs `lpadmin` per env var then execs `cupsd -f`.
   Queue names: `receipt`, `kitchen` (shell-safe, no spaces).
   ```bash
   lpadmin -p receipt -E -v "$PRINTER_RECEIPT_URI" -o printer-is-shared=false -m raw
   lpadmin -p kitchen -E -v "$PRINTER_KITCHEN_URI" -o printer-is-shared=false -m raw
   ```
   Note: on newer CUPS, `-m raw` is deprecated — for raw passthrough queues the correct
   invocation may differ (omit `-m`, or `-o raw`). `[DISCOVER]` the right form for the CUPS
   version pinned in the image and record it in `FINDINGS.md`.
   Also configure cupsd to accept jobs from the compose network (`Listen 0.0.0.0:631` +
   allow rules) so the `odoo` container can submit remotely.
2. Add the `escpos-emulator` service (dev profile): TCP listener on 9100 dumping each
   connection's bytes to `/data/jobs/<timestamp>.bin` on a mounted volume.
3. Extend the `odoo` image: `cups-client` (for `lp`/`lpstat`) and `python-escpos`
   (pin the version in the Dockerfile). Decide pycups-over-IPP vs `lp -h cups:631`
   subprocess now — subprocess avoids a C dependency and is fine; document the choice.
4. Smoke test the full transport chain, Odoo not involved yet:
   ```bash
   docker compose exec odoo bash -c \
     "printf '\x1b\x40Hello from CUPS\n\n\n\x1d\x56\x00' > /tmp/t.bin && lp -h cups:631 -d receipt -o raw /tmp/t.bin"
   ```
   → a new `.bin` file must appear in the emulator volume containing exactly those bytes.
5. Test queue behavior against the emulator: stop the emulator container, submit a job,
   start it → job arrives (CUPS retried). Submit 5 jobs rapidly → 5 files, correct order,
   no interleaving within a file.

**Exit criteria (dev):** bytes flow odoo-container → cups → emulator; retry-on-offline and
ordering confirmed. **Prod validation of the same chain against real printers happens in
Phase 5 on-site** — including a physical print of the same `/tmp/t.bin` before installing
the module there.

## Phase 1 — Discovery in the installed Odoo 19 source `[DISCOVER]`

Goal: find the real extension points. Grep the actual addons path (find it via
`odoo-bin --help` config or `python3 -c "import odoo; print(odoo.__path__)"` etc.).

Questions to answer (write answers + file paths into `FINDINGS.md`):

1. **Printer abstraction (JS):** Where does the POS define its printer classes/interface?
   Look for a base printer class and concrete implementations (there will be at least an
   Epson ePOS one and an IoT one). Search terms: `printReceipt`, `sendPrintingJob`,
   `openCashbox`, `epos`, `hw_printer`, `printer_service`, under
   `addons/point_of_sale/static/src/`.
2. **How the receipt becomes bytes/pixels:** Modern Odoo POS renders the receipt to an image
   (canvas → raster) for ePOS-style printers rather than composing ESC/POS text commands.
   Confirm this for v19 and identify the exact artifact available at the interception point
   (canvas? base64 PNG? something else?). This decides our payload format (see Phase 2, D1).
3. **Printer configuration (Python):** How are printers modeled? `pos.printer` model —
   its `printer_type` selection field, how kitchen "order printers" bind to product
   categories, and where the *receipt* (cashier) printer is configured on `pos.config`
   (it may be separate from `pos.printer`). How does config reach the JS side (pos session
   load params)?
4. **How to register a new printer type end-to-end:** Find how existing types
   (e.g. `epson_epos`) plug in — selection value on the model, config UI, JS factory that
   instantiates the right printer class for the type. Our module mirrors that pattern with a
   new type (e.g. `server_cups`).
5. **RPC convention:** What the POS JS uses for backend calls in v19 (ORM service /
   `rpc` helper / fetch) so our POST matches house style and carries session auth.

**Exit criteria:** `FINDINGS.md` documents each answer with concrete file paths and code
excerpts from the local source. No implementation before this exists.

## Phase 2 — The Odoo module `pos_server_print`

### Design decisions (already made — implement, don't relitigate)

- **D1. Payload format:** Reuse Odoo's existing receipt rendering. The JS printer class
  captures whatever the stock renderer produces (per Phase 1 Q2 — almost certainly a raster
  image) and POSTs it. The **server** converts image → ESC/POS raster using `python-escpos`
  (`pip3 install python-escpos`), appends feed + cut, and submits to CUPS. Rationale: zero
  receipt-layout code duplicated in JS; ESC/POS quirks (raster commands, cut, drawer pulse)
  live in one place in Python where they're testable. If Phase 1 reveals the client already
  produces final ESC/POS bytes cheaply, a raw-bytes passthrough mode is acceptable too —
  support `payload_type: "image" | "escpos"` in the endpoint from day one.
- **D2. Queue:** CUPS only. No custom job worker, no cron drain, no direct TCP from Python.
- **D3. Audit:** Every job gets a row in a new model `pos.print.job` (printer, session, order
  ref, payload attachment or hash, CUPS job id, state, error text, timestamps). This is for
  audit + reprint, not for queuing — CUPS is the queue. Reprint = resubmit stored payload.
- **D4. Endpoint returns fast:** submit to CUPS, return `{job_id, cups_job_id}` immediately.
  Never block the cashier UI on printer state.
- **D5. Auth:** controller is `auth='user'`; validate the caller has an open POS session and
  that the target printer belongs to that session's config. Printer IPs / queue names never
  reach the client — the client only references Odoo printer record IDs.

### Module structure

```
pos_server_print/
├── __manifest__.py            # depends: point_of_sale; assets: POS bundle additions
├── __init__.py
├── models/
│   ├── pos_printer.py         # extend pos.printer (and pos.config if Phase 1 Q3 says the
│   │                          #   receipt printer lives there): add selection value
│   │                          #   'server_cups' + char cups_queue_name + int dots_per_line
│   │                          #   (default 576) + bool has_cashdrawer;
│   │                          #   expose to POS session load params
│   └── pos_print_job.py       # audit log model + reprint action
├── controllers/
│   └── main.py                # POST /pos_server_print/job
│                              # GET  /pos_server_print/job/<id>/status   (v1.1, optional)
│                              # POST /pos_server_print/cashbox            (only if drawer)
├── services/
│   └── escpos.py              # image→ESC/POS raster + feed + cut (+ drawer pulse) via
│                              #   python-escpos; submit to CUPS (pycups or `lp` subprocess —
│                              #   pick ONE; subprocess `lp -d <queue> -o raw` is fine and
│                              #   avoids a C dependency, decide and document)
├── static/src/
│   └── app/server_printer.js  # printer class implementing the interface found in Phase 1;
│                              #   captures rendered receipt, POSTs to controller;
│                              #   + registration/factory patch for type 'server_cups'
├── views/
│   ├── pos_printer_views.xml  # show cups_queue_name when type == server_cups; Test Print btn
│   └── pos_print_job_views.xml# job log list/form + Reprint button
└── tests/
    └── test_controller.py     # see Phase 4
```

### Controller contract

```
POST /pos_server_print/job        (json)
{
  "printer_id": <int, pos.printer id or config-receipt-printer ref per Phase 1 Q3>,
  "payload_type": "image" | "escpos",
  "data": "<base64>",
  "order_ref": "POS/0087",        # optional, for audit
}
→ 200 {"job_id": 17, "cups_job_id": 123, "state": "submitted"}
→ 4xx on auth/validation failure; 500 with error text if CUPS submission fails
   (CUPS accepting a job while the printer is offline is SUCCESS — it will retry; that is
   the desired behavior, do not treat it as an error)
```

### JS behavior

- Implement the printer interface exactly as stock printers do (per FINDINGS), so the rest of
  the POS (print buttons, order flow, kitchen dispatch) needs zero changes.
- On print: obtain rendered receipt → base64 → POST → resolve the promise the POS expects.
  On HTTP failure: reject with a user-visible message (Odoo POS already shows printer error
  dialogs with retry — reuse that path, `[DISCOVER]` how errors are surfaced).
- Keep it dumb. No retries in JS (CUPS retries), no printer state polling in v1.

## Phase 3 — Config & UX polish

- Settings UX: selecting type `server_cups` shows the queue name field; a **Test Print**
  button on the printer record fires a canned receipt through the full path (controller →
  escpos service → CUPS). This is the main ops/debug tool — build it early, not last.
- Job log menu under POS config (filter by state/date/printer, Reprint button).
- Optional v1.1: status endpoint reading CUPS job state, so failed jobs show in the log with
  CUPS's error message.

## Phase 4 — Testing matrix

| Test | Expected |
|---|---|
| Unit: image → ESC/POS conversion | correct raster header, ends with feed+cut; snapshot-test bytes |
| Unit: controller auth (no POS session / wrong printer id) | 403 / 404, no CUPS submission |
| Single tablet prints receipt | physical print < ~2 s |
| Two tablets print simultaneously to same printer | both print, sequential, no interleaving |
| Kitchen order → kitchen printer, receipt → receipt printer | correct routing by category |
| Printer powered off, print attempted | POS shows success (job queued); prints on power-on |
| Odoo restarted with jobs in CUPS queue | jobs unaffected (CUPS owns them) |
| WSL restarted | CUPS service auto-starts (systemd); queues persist |
| Reprint from job log | identical physical output |
| 80 mm vs actual paper width | no clipping (depends on printer model input from user) |

## Phase 5 — Deployment checklist

- [ ] Static LAN IP for the Windows PC (router reservation)
- [ ] Static IPs (or reservations) for both printers
- [ ] Prod `.env` written on-site: real `PRINTER_*_URI` values; dev profile (emulator) NOT enabled
- [ ] `docker compose exec cups nc -zv <printer_ip> 9100` succeeds for both printers
- [ ] Transport smoke test from Phase 0 step 4 produces a **physical** receipt on both printers
- [ ] WSL + Docker + compose stack start on boot with nobody logged in (Task Scheduler
      `wsl -d <distro>` + `restart: unless-stopped` on services) — verify with a cold reboot
- [ ] `netsh portproxy` rule for 8069 persists across reboots (it does, but verify) + firewall rule
- [ ] CUPS queues `receipt`/`kitchen` exist post-reboot (entrypoint recreates them — verify idempotent)
- [ ] Module installed, printers configured in Odoo, test print from a tablet after full cold boot

## Non-goals (v1)

- No QZ Tray, no IoT Box, no React Native involvement in the print path.
- No customer-facing display, no scale, no ePOS peripherals other than (maybe) cash drawer.
- No printer status dashboard — CUPS web UI at `:631` covers ops needs.

## Known risks

1. **Odoo 19 POS internals differ from assumptions** — mitigated by Phase 1 discovery-first.
2. **Raster conversion size/speed** — an 80 mm receipt raster is small; if conversion is ever
   slow, pre-scale the image to printer dot width (576 dots for typical 80 mm/203 dpi) client-side.
3. **CUPS raw queue setup varies by CUPS version** — resolved in Phase 0 before code exists.
4. **WSL networking edge cases** (VPNs, Docker interfering with NAT) — Phase 0 gate.

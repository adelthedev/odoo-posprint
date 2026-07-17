# Deploying pos_server_print to production

First-time install on the production machine (WSL2). Production has never run
an earlier version of this module, so this is a clean install — no migration.

## 1. Pull the code

```sh
git pull   # after merging the posprint branch into master
```

Brings the module, the updated `docker-compose.yml` and the CUPS entrypoint.

## 2. Write the production .env

Copy `.env.example` to `.env` if not already present. One
`PRINTER_<NAME>_URI` per physical printer — the queue is named `<name>`
lowercased. Do **not** enable the `dev` profile.

```sh
PRINTER_RECEIPT_URI=socket://<receipt-printer-ip>:9100
PRINTER_KITCHEN_URI=socket://<kitchen-printer-ip>:9100
# add more printers as needed, e.g.:
# PRINTER_BAR_URI=socket://<bar-printer-ip>:9100
```

Check each printer is reachable from the host first: `nc -zv <ip> 9100`.

## 3. Rebuild and restart

```sh
docker compose build
docker compose up -d
docker exec odoo-cups lpstat -v   # one queue per .env entry, correct URIs
```

## 4. Install and configure the module

```sh
docker compose exec -T odoo odoo --db_host=db --db_user=odoo \
    --db_password=@fghanDish -d <prod-db> -i pos_server_print \
    --stop-after-init --http-port=8899
docker restart odoo-app
```

Then in the backend:

1. Create one `pos.printer` per queue, type *"Print via the Odoo server
   (CUPS)"*: queue name from step 2, 576 dots/line (80 mm), no cash drawer.
   Use **Test Print** on each — paper must come out.
2. Settings → Point of Sale → *Server Receipt Printers*: assign the receipt
   printer(s). First in the list is the default for reports/cash drawer.
3. Kitchen printer: add it to the config's *Order Printers* with its product
   categories, as usual.

Finally print a real receipt from a POS session and reboot the machine once to
confirm everything comes back up (cold-boot check from the Phase 5 checklist
in `PLAN-pos-server-print.md`).

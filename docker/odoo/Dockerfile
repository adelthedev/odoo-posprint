FROM odoo:19

USER root

# cups-client: `lp`/`lpstat` to submit jobs to the cups sidecar over IPP.
# python-escpos: image -> ESC/POS raster conversion in pos_server_print.
RUN apt-get update \
    && apt-get install -y --no-install-recommends cups-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --break-system-packages --no-cache-dir python-escpos==3.1

USER odoo

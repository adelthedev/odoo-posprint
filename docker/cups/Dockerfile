FROM debian:bookworm-slim

# cups 2.4.x (bookworm). cups-client provides lpadmin/lpstat for the entrypoint.
RUN apt-get update \
    && apt-get install -y --no-install-recommends cups cups-client \
    && rm -rf /var/lib/apt/lists/*

COPY cupsd.conf /etc/cups/cupsd.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 631

ENTRYPOINT ["/entrypoint.sh"]

"""Dev-only ESC/POS printer emulator.

Listens on TCP 9100 like a JetDirect/raw thermal printer and dumps each
connection's bytes to /data/jobs/<timestamp>-<seq>.bin. One connection is
handled at a time, mimicking cheap ESC/POS hardware (which is exactly why CUPS
must serialize jobs) — a second concurrent connection waits in the accept
backlog, it is not interleaved.
"""

import datetime
import itertools
import os
import socket

JOBS_DIR = os.environ.get("JOBS_DIR", "/data/jobs")
PORT = int(os.environ.get("PORT", "9100"))


def main():
    os.makedirs(JOBS_DIR, exist_ok=True)
    seq = itertools.count(1)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", PORT))
    server.listen(16)
    print(f"escpos-emulator listening on :{PORT}, dumping to {JOBS_DIR}")

    while True:
        conn, addr = server.accept()
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S.%f")
        path = os.path.join(JOBS_DIR, f"{ts}-{next(seq):04d}.bin")
        total = 0
        with conn, open(path, "wb") as f:
            conn.settimeout(30)
            while True:
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    break
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
        print(f"job from {addr[0]}: {total} bytes -> {path}")


if __name__ == "__main__":
    main()

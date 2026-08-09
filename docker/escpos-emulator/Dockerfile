FROM python:3.12-slim

COPY emulator.py /emulator.py

EXPOSE 9100
VOLUME /data/jobs

CMD ["python", "-u", "/emulator.py"]

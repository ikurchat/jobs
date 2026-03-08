FROM rnix/openssl-gost:latest

RUN apk add --no-cache python3 py3-pip socat curl && \
    pip3 install --break-system-packages flask gunicorn

COPY proxy.py /app/proxy.py

WORKDIR /app
EXPOSE 8443

CMD ["python3", "proxy.py"]

FROM rnix/openssl-gost:latest AS gost

FROM python:3.11-slim

# Copy GOST-enabled curl with all its dependencies
COPY --from=gost /usr/bin/curl /usr/local/bin/gost-curl
COPY --from=gost /usr/local/curl/lib/ /usr/local/curl/lib/
COPY --from=gost /usr/local/ssl/lib/libssl.so* /usr/local/ssl/lib/
COPY --from=gost /usr/local/ssl/lib/libcrypto.so* /usr/local/ssl/lib/
COPY --from=gost /usr/local/ssl/lib/engines-1.1/ /usr/local/ssl/lib/engines-1.1/
COPY --from=gost /usr/local/ssl/lib/engines-3/ /usr/local/ssl/lib/engines-3/
COPY --from=gost /usr/local/ssl/openssl.cnf /usr/local/ssl/openssl.cnf

ENV LD_LIBRARY_PATH=/usr/local/curl/lib:/usr/local/ssl/lib
ENV OPENSSL_CONF=/usr/local/ssl/openssl.cnf

# Create wrapper script for curl
RUN echo '#!/bin/sh\nLD_LIBRARY_PATH=/usr/local/curl/lib:/usr/local/ssl/lib OPENSSL_CONF=/usr/local/ssl/openssl.cnf exec /usr/local/bin/gost-curl "$@"' > /usr/local/bin/curl && \
    chmod +x /usr/local/bin/curl

COPY proxy.py /app/proxy.py

WORKDIR /app
EXPOSE 8443

CMD ["python3", "proxy.py"]

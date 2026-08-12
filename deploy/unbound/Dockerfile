# Gate C: a local caching/forwarding DNS resolver for the production stack's
# own containers, deliberately minimal (alpine's own unbound package, not a
# third-party image) so its config path is something this repo controls and
# can verify, not something borrowed on trust from an unpinned upstream image.
#
# This is infrastructure DNS for the containers themselves (apt, Caddy's ACME
# lookups, general system resolution) — it is NOT part of the scanner's own
# accuracy path. app/scanner/dns_records.py already pins its own resolver to
# 1.1.1.1/8.8.8.8/9.9.9.9 explicitly, bypassing whatever the container's
# system resolver is (see that file's docstring — this was Gate A's DNS
# blind-spot fix), so a slow or unreachable Unbound container never degrades
# scan accuracy, only general container DNS latency.
FROM alpine:3.20

RUN apk add --no-cache unbound

COPY unbound.conf /etc/unbound/unbound.conf

EXPOSE 53/udp 53/tcp

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=5 \
    CMD unbound-control -c /etc/unbound/unbound.conf status || exit 1

USER unbound

CMD ["unbound", "-d", "-c", "/etc/unbound/unbound.conf"]

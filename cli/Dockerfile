FROM golang:1.26-alpine@sha256:2389ebfa5b7f43eeafbd6be0c3700cc46690ef842ad962f6c5bd6be49ed82039 AS builder

WORKDIR /app
COPY ./ .

ARG TARGETARCH
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} go build -ldflags="-s -w" -o virchow-cli .
RUN mkdir -p /home/virchow/.config

FROM scratch

COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder --chown=65534:65534 /home/virchow /home/virchow

COPY --from=builder /app/virchow-cli /virchow-cli

ENV HOME=/home/virchow
ENV XDG_CONFIG_HOME=/home/virchow/.config

USER 65534:65534

ENTRYPOINT ["/virchow-cli"]

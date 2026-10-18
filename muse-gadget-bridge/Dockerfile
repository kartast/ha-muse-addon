# Muse Gadget Bridge add-on image.
#
# Mirrors the upstream installer (linux/install.sh in the vendored SDK):
# system Python + distro dbus/gi/cryptography, a venv built with
# --system-site-packages so it can see them, the musegadget package installed
# with --no-deps, then the hash-pinned requirements.lock (websockets).
# Differences from a bare-metal install: no systemd (s6 runs the service),
# no bluetoothd in the container (the host's BlueZ is used over D-Bus), and
# the SDK token arrives via the add-on options instead of install flags.
ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base-debian:bookworm
FROM $BUILD_FROM

ARG UV_VERSION=0.9.9
ARG BUILD_ARCH

ENV PYTHONUNBUFFERED=1 \
    MUSEGADGET_STATE_DIR=/data/musegadget \
    MUSEGADGET_SOCKET=/run/musegadget/musegadget.sock \
    MUSEGADGET_RUN_AS=muse

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# python3-dbus / python3-gi / python3-cryptography come from the distro,
# exactly as upstream requires. bluez is NOT installed: bluetoothd stays on
# the host and the bridge talks to it over the host D-Bus (host_dbus: true).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 \
      python3-dbus \
      python3-gi \
      python3-cryptography \
      curl \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system muse \
 && useradd --system --gid muse --home-dir /home/muse --create-home muse

# Vendored Muse Linux Device SDK (see sdk/VENDOR.md), with the ha.*
# Home Assistant commands added to src/musegadget/executor.py.
COPY sdk /usr/src/musegadget-sdk

RUN curl -fsSL "https://astral.sh/uv/${UV_VERSION}/install.sh" \
      | env UV_INSTALL_DIR=/opt/musegadget/bin UV_NO_MODIFY_PATH=1 sh \
 && /opt/musegadget/bin/uv venv --quiet \
      --python /usr/bin/python3 --system-site-packages /opt/musegadget/venv \
 && /opt/musegadget/bin/uv pip install --quiet \
      --python /opt/musegadget/venv/bin/python --no-deps /usr/src/musegadget-sdk \
 && DATA_DIR="$(/opt/musegadget/venv/bin/python -c 'import musegadget, os; print(os.path.join(os.path.dirname(musegadget.__file__), "data"))')" \
 && /opt/musegadget/bin/uv pip install --quiet \
      --python /opt/musegadget/venv/bin/python --require-hashes -r "$DATA_DIR/requirements.lock" \
 && ln -sf /opt/musegadget/venv/bin/musegadget /usr/local/bin/musegadget \
 && rm -rf /usr/src/musegadget-sdk /root/.cache

COPY run.sh /opt/musegadget/run.sh
RUN chmod a+x /opt/musegadget/run.sh

COPY rootfs /
RUN chmod a+x /etc/s6-overlay/s6-rc.d/musegadget/run

LABEL io.hass.type="addon" \
      io.hass.arch="${BUILD_ARCH}" \
      io.hass.version="0.1.0"

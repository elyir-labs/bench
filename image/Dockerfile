# The image builder's host: Debian Trixie arm64 with rpi-image-gen (docs/image.md). Native on an Apple
# Silicon Mac or a Pi; elsewhere Docker emulates arm64.
FROM debian:trixie
ARG RIG_COMMIT=aa329d4
RUN apt-get update -q && apt-get install -y -q --no-install-recommends git sudo ca-certificates curl xz-utils \
 && git clone -q https://github.com/raspberrypi/rpi-image-gen.git /opt/rpi-image-gen \
 && git -C /opt/rpi-image-gen checkout -q "$RIG_COMMIT" \
 && cd /opt/rpi-image-gen && ./install_deps.sh && rm -rf /var/lib/apt/lists/*
# a release's OS bundle (image/build.sh): its root filesystem, compressed
RUN apt-get update -q && apt-get install -y -q --no-install-recommends zstd mtools && rm -rf /var/lib/apt/lists/*

#!/bin/bash
# Try elyir-bench-layout (the first boot's two OS slots and /data) on pretend cards of several sizes, in a
# throwaway privileged container: the built image is written onto a sparse file, slot A is mounted as if
# it were running, and the result is checked. Needs a built image in the elyir-imagework volume.
#
#   image/test-layout.sh            32, 16 and 8 GB cards
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
docker run --rm --privileged -v elyir-imagework:/work:ro \
  -v "$ROOT/image/layer/elyir-bench-printer.d/customize.overlay/usr/local/sbin/elyir-bench-layout:/layout:ro" \
  elyir-imagegen bash -euc '
  apt-get -qq update >/dev/null && apt-get -qq install -y cloud-guest-utils fdisk e2fsprogs util-linux >/dev/null
  img=$(ls /work/elyir/image-*/*.img | head -1)
  # Docker has no udev: device nodes for the partitions of a loop device come from /sys, here and (through a
  # stand-in udevadm on PATH) after elyir-bench-layout adds slot B and /data
  mkdir -p /shim && cat > /shim/udevadm <<"SH"
#!/bin/sh
for p in /sys/class/block/loop*p*; do [ -e "/dev/${p##*/}" ] || mknod "/dev/${p##*/}" b $(tr ":" " " < "$p/dev"); done
SH
  printf "#!/bin/sh\nexit 0\n" > /shim/systemctl   # no systemd in a container: daemon-reload is a no-op
  chmod 755 /shim/udevadm /shim/systemctl; export PATH=/shim:$PATH
  for gb in 32 16 8; do
    echo "== a $gb GB card"
    rm -f /card && truncate -s ${gb}G /card && dd if="$img" of=/card conv=notrunc,sparse bs=4M status=none
    dev=$(losetup -fP --show /card); sleep 1; udevadm
    mkdir -p /mnt/a && mount ${dev}p2 /mnt/a
    mkdir -p /home/pi/printer_data/config && echo kept > /home/pi/printer_data/config/printer.cfg
    : > /etc/fstab; rm -rf /var/lib/elyir-bench /data
    ELYIR_BENCH_LAYOUT_ROOT=${dev}p2 bash /layout 2>&1 | sed "s/^/   /"
    sfdisk -l $dev | grep "^/dev" | sed "s/^/   /"
    lsblk -no NAME,SIZE,LABEL $dev | sed "s/^/   /"
    echo "   slot A filesystem: $(df -h /mnt/a | tail -1 | awk "{print \$2}")"
    if [ -e ${dev}p4 ]; then
      echo "   printer.cfg through the bind mount: $(cat /home/pi/printer_data/config/printer.cfg)"
      grep -c astro-data /etc/fstab | sed "s/^/   fstab lines: /"
      umount /home/pi/printer_data /data
    fi
    umount /mnt/a; losetup -d $dev; rm -f ${dev}p*; rm -rf /home/pi/printer_data
  done'

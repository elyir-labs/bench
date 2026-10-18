#!/bin/bash
# The root and the boot partition by PARTUUID (<disk signature>-<partition>), as stock Raspberry Pi OS
# names them and elyir-bench-os reads them (docs/os-slots.md). genimage runs this before each filesystem.
set -eu
LABEL="$1"
DISK="${IGconf_image_disksig#0x}"
case $LABEL in
   ROOT)
      cat << EOF2 > "$IMAGEMOUNTPATH/etc/fstab"
proc            /proc           proc    defaults          0       0
PARTUUID=$DISK-01  /boot/firmware  vfat    defaults          0       2
PARTUUID=$DISK-02  /               ext4    defaults,noatime  0       1
EOF2
      ;;
   BOOT)
      sed -i "s|root=[^ ]*|root=PARTUUID=$DISK-02 rootfstype=ext4|" "$IMAGEMOUNTPATH/cmdline.txt"
      ;;
esac

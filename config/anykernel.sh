#!/sbin/sh
properties() { '
kernel.string=e1s DZG1 ReSukiSU
do.devicecheck=1
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=e1s
device.name2=e1sxxx
supported.versions=
supported.patchlevels=
supported.vendorpatchlevels=
'; }

BLOCK=boot
IS_SLOT_DEVICE=0
RAMDISK_COMPRESSION=auto
PATCH_VBMETA_FLAG=0
NO_VBMETA_PARTITION_PATCH=1

. tools/ak3-core.sh

split_boot
flash_boot

#!/bin/sh -e
# Copyright 2024 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later

if [ "$1" != "CALLED_FROM_PMB" ]; then
	echo "ERROR: this script is only meant to be called by pmbootstrap"
	exit 1
fi

CHROOT="$2"

test -n "$CHROOT"
test -f "$CHROOT"/in-pmbootstrap

if [ -L "$CHROOT"/bin ]; then
	echo "ERROR: chroot has merged usr already: $CHROOT"
	exit 1
fi

# /bin -> /usr/bin
rsync -a "$CHROOT"/bin/ "$CHROOT"/usr/bin/
rm -rf "$CHROOT"/bin
ln -s usr/bin "$CHROOT"/bin

# /sbin -> /usr/bin
rsync -a "$CHROOT"/sbin/* "$CHROOT"/usr/bin/
rm -rf "$CHROOT"/sbin
ln -s usr/bin "$CHROOT"/sbin

# /lib -> /usr/lib
rsync -a "$CHROOT"/lib/* "$CHROOT"/usr/lib/
rm -rf "$CHROOT"/lib
ln -s usr/lib "$CHROOT"/lib

# /usr/sbin -> /usr/bin
rsync -a "$CHROOT"/usr/sbin/* "$CHROOT"/usr/bin/
rm -rf "$CHROOT"/usr/sbin
ln -s bin "$CHROOT"/usr/sbin

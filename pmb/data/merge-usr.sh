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

dir_is_empty() {
	local dir="$1"
	local i

	for i in "$dir"/*; do
		if [ "$i" = "$dir/*" ]; then
			return 0
		else
			return 1
		fi
	done
}

merge() {
	local src="$1"
	local dest="$2"
	local dir

	cd "$CHROOT/$src"

	for dir in $(find . -type d | sort -r); do
		mkdir -p "$CHROOT/$dest/$dir"

		# for sym in $(find . -type l | sort -r); do
		# 	# Determine the symlink target dir (either ../usr/{bin,lib,sbin} or ../{bin,lib,sbin} when src=usr/sbin)
		# 	# or continue if this symlink doesn't match these patterns
		# 	target="../usr/$src"
		# 	sym_target="$(readlink "$sym")"
		# 	if echo "$sym_target" | grep -q "../usr/$dest"; then
		# 		target="../$dest"
		# 	elif ! echo "$sym_target" | grep -q "$target"; then
		# 		continue
		# 	fi

		# 	target_dir="$(dirname "$sym_target")"
		# 	new_target="$(echo "$sym_target" | sed "s|${target_dir}/||")"
		# 	echo "Fixing relative symlink: $sym (-> $sym_target) -> $new_target"
		# 	ln -sf "$new_target" "$CHROOT/$dest/$sym"
		# 	rm "$sym"
		# done

		if ! dir_is_empty "$dir"; then
			mv "$dir"/* "$CHROOT/$dest/$dir"
		fi

		if [ "$dir" != "." ]; then
			rmdir "$dir"
		fi
	done

	cd "$CHROOT"
	rmdir "$src"

	ln -s "$dest" "$CHROOT/$src"
}

merge bin usr/bin
merge sbin usr/bin
merge lib usr/lib
merge usr/sbin bin

# Stupid usr symlink to fix some relative symlinks
ln -s . "$CHROOT"/usr/usr

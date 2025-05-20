#!/bin/sh -e
# Description: lint all markdown files
# https://postmarketos.org/pmb-ci

if [ "$(id -u)" = 0 ]; then
	set -x
	apk add npm
	exec su "${TESTUSER:-build}" -c "sh -e $0"
fi

MDL="markdownlint-cli"
if ! command -v "$MDL" >/dev/null; then
	MDL="$HOME/node_modules/markdownlint-cli/markdownlint.js"
	if ! command -v "$MDL" >/dev/null; then
		(cd ~;
		 set -x;
		 npm install markdownlint-cli)
	fi
fi
if ! command -v "$MDL" >/dev/null; then
	echo "ERROR: failed to find/install markdownlint"
	exit 1
fi

find . -name '*.md' |
while read -r file; do
	echo "mdl: $file"
	if ! "$MDL" --disable MD059 -- "$file"; then
		echo
		echo "markdown lint failed!"
		exit 1
	fi
done

#!/bin/sh -e
# Description: static type checking for python scripts
# https://postmarketos.org/pmb-ci

if [ "$(id -u)" = 0 ]; then
	set -x
	wget https://gitlab.postmarketos.org/postmarketOS/ci-common/-/raw/master/install_mypy.sh
	sh ./install_mypy.sh py3-argcomplete
	exec su "${TESTUSER:-build}" -c "sh -e $0"
fi

set -x

python -m mypy pmbootstrap.py

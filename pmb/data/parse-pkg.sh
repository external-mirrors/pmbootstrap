#!/bin/sh

# parse-pkg.sh: APKBUILD -> JSON parser
# This parses APKBUILD files to determine info
# ahead of time about the package that WOULD be
# built if abuild were invoked.
#
# Since APKBUILD files are literally shell scripts
# they can be fully dynamic, producing different
# output depending on the input.
#
# This script parses them by sourcing them just
# like abuild does, so it's also necessary to
# set any appropriate environment variables

# Print ALL variables when we run set
# not just environment variables
set -a

if [ -z "$1" ]; then
	echo "Usage: $0 ./APKBUILD" >&2
	exit 1
fi

APKBUILD=$(realpath $1)

cleanup() {
	rm $ignore_file
	rm -rf $tmpdir
}

trap cleanup EXIT

# Set up a temporary directory to run in
# to reduce the chance of the APKBUILD
# creating random files...
tmpdir=$(mktemp -d)
cd $tmpdir
chmod -w .

# We need to declare variables here that we don't want
# to be exported so they get included in the ignore file
is_first_line=
inside_var=
ignore_file=$(mktemp)
subpkgname=
# the name of the subpkg function
subpkgsplit=
i=
# Try to minimise the chance of a subpackage messing with your filesystem
srcdir="$(pwd)"
basedir="$(pwd)"
# Record the variables used by this script and environment variables
# so we can filter them out
set > $ignore_file

subpkg_set() {
	subpkgname=${1%%:*}

	local _splitarch=${1#*:}
	[ "$_splitarch" = "$1" ] && _splitarch=""

	subpkgsplit=${_splitarch%%:*}

	if [ -z "$subpkgsplit" ]; then
		case $subpkgname in
			*-bash-completion) subpkgsplit=bashcomp ;;
			*-zsh-completion) subpkgsplit=zshcomp ;;
			*-fish-completion) subpkgsplit=fishcomp ;;
			*) subpkgsplit="${subpkgname##*-}" ;;
		esac
	fi

	subpkgarch=${_splitarch#*:}
	if [ "$subpkgarch" = "$_splitarch" -o -z "$subpkgarch" ]; then
		case "$subpkgname" in
		*-doc | *-openrc | *-lang | *sh-completion | *-pyc) subpkgarch="noarch" ;;
		*) subpkgarch="$pkgarch" ;;
		esac
	fi
}

function parse_urldecode() { : "${*//+/ }"; echo -e "${_//%/\\x}"; }

# Source the APKBUILD itself
. $APKBUILD >/dev/null 2>&1

function dump_vars() {
	# stdin: output of "set" command
	local is_first_line
	local name
	local val
	local key
	local sep
	local v
	is_first_line=true
	while read -r var; do
		name=${var%%=*}
		# Check that $name isn't an ignored variable and that the line we
		# read in matches the format "MY_VAR='"
		if grep -q "^${name}=" $ignore_file || echo "$var" | grep -qv "^${name}='"; then
			continue
		fi
		# Rewrite the subpackages variable so we can use
		# the "subpackages" key to refer to the actual
		# subpackage objects
		if [ "$name" = "subpackages" ]; then
			key="subpackage_names"
		else
			key="$name"
		fi
		val="$(eval echo "\$$name" | jq -Rja .)"
		val="${val:1:-1}"
		if [ "$name" = "source" ]; then
			val="$(parse_urldecode "$val")"
		fi
		# Add a comma for the previous property
		if ! $is_first_line; then
			printf ",\n"
		fi
		printf "\"$key\": "
		# Handle strings vs lists
		case "$name" in
		arch|options|checkdepends|depends|makedepends*|source|subpackages|install_if|install|triggers|_pmb_recommends|_pmb_groups|_pmb_select|_pmb_default|pkggroups|pkgusers|replaces)
			printf "["
			sep=
			for v in $val; do
				printf "$sep\"$v\""
				sep=", "
			done
			printf "]"
			;;
		*)
			printf "\"$val\""
			;;
		esac
		is_first_line=false
	done
	printf "$1\n"
}

# Now handle the subpackages.
# The only way to figure out what variables
# they set is to run the function... but we
# REALLY don't want it to do random stuff in our
# environment so override some builtins

install() {
	:
}
mv() {
	:
}
touch() {
	:
}
cp() {
	:
}
amove() {
	:
}
mkdir() {
	:
}
ln() {
	:
}
rm() {
	:
}
rmdir() {
	:
}

printf "{\n"
set | dump_vars ,

printf "\"subpackages\": {\n"
is_first_line=true
for i in $subpackages; do
	if ! $is_first_line; then
		printf ",\n"
	fi
	subpkg_set $i
	printf "\"$subpkgname\": {\n"
	cmd=$(cat <<-END
	(unset \$(set | grep "='" | cut -d= -f1);
	IFS="$IFS"
	PATH="$PATH"
	ignore_file="$ignore_file"
	pkgname=${pkgname};
	pkgver=${pkgver};
	pkgrel=${pkgrel};
	subpkg_set $i;
	$subpkgsplit >/dev/null 2>&1;
	unset pkgname pkgver pkgrel;
	set | dump_vars)
	END
	)
	eval "$cmd"
	printf "}"
	is_first_line=false
done
printf "\n}\n"

printf "\n}\n"

import os
import glob
from typing import Generator, List

import pmb.config

def pkgrepo_paths() -> List[str]:
    # XXX: this should be enforced by API!
    return pmb.config.aports

def pkgrepo_default_path() -> str:
    """
    Get the first pkgrepo path that isn't a special "extra-repo".
    """
    for aports in pkgrepo_paths():
        if "extra-repos" not in aports:
            return aports
    raise RuntimeError(f"No valid default aports path found: {pkgrepo_paths()}")

def pkgrepo_names(ignore_extras: bool = False) -> List[str]:
    """
    Return a list of all the package repository names.
    """
    names = pkgrepo_paths()
    if ignore_extras:
        names = list(filter(lambda x: "extra-repos" not in x, names))
    names = [os.path.basename(x) for x in names]
    #if not pmb.config.is_systemd_selected(args):

def pkgrepo_path(name: str) -> str:
    """
    Return the absolute path to the package repository with the given name.
    """
    for aports in pkgrepo_paths():
        if os.path.basename(aports) == name:
            return aports
    raise RuntimeError(f"aports '{name}' not found")

def pkgrepo_name_from_subdir(subdir: str) -> str:
    """
    Return the name of the package repository for the given directory.
    e.g. "pmaports" for "$WORKDIR/pmaports/main/foobar"
    """
    for aports in pkgrepo_paths():
        if subdir.startswith(aports):
            return os.path.basename(aports)
    raise RuntimeError(f"aports subdir '{subdir}' not found")

def pkgrepo_glob_one(path: str) -> str | None:
    """
    Search for the file denoted by path in all aports repositories.
    path can be a glob.
    """
    for repo in pkgrepo_paths():
        g = glob.glob(os.path.join(repo, path))
        if not g:
            continue
        g = list(filter(lambda x: not x.startswith(os.path.join(repo, "extra-repos")), g))

        if len(g) != 1:
            raise RuntimeError(f"{path} found multiple matches in {repo}")
        if g:
            return os.path.join(repo, g[0])

    return None


def pkgrepo_iglob(path: str, recursive=False) -> Generator[str, None, None]:
    """
    Yield each matching glob over each aports repository.
    """
    for repo in pkgrepo_paths():
        for g in glob.iglob(os.path.join(repo, path), recursive=recursive):
            if g.startswith(os.path.join(repo, "extra-repos")):
                continue
            yield os.path.join(repo, g)


def pkgrepo_iter_package_dirs() -> Generator[str, None, None]:
    """
    Yield each matching glob over each aports repository.
    Detect duplicates within the same aports repository but otherwise
    ignore all but the first. This allows for overriding packages.
    """
    seen = dict(map(lambda a: (a, []), pkgrepo_paths()))
    for repo in pkgrepo_paths():
        print(f"Checking repo: {os.path.basename(repo)}")
        for g in glob.iglob(os.path.join(repo, "**/*/APKBUILD"), recursive=True):
            if g.startswith(os.path.join(repo, "extra-repos")):
                continue
            g = os.path.dirname(g)
            pkg = os.path.basename(g)
            if pkg in seen[repo]:
                raise RuntimeError(f"Package {pkg} found in multiple aports "
                               "subfolders. Please put it only in one folder.")
            if pkg in [x for li in seen.values() for x in li]:
                continue
            seen[repo].append(pkg)
            yield os.path.join(repo, g)

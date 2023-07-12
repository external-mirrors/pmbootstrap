import os
import glob
from typing import Generator, List

import pmb.config

def pkgrepo_paths() -> List[str]:
    # XXX: this should be enforced by API!
    return pmb.config.get("aports").split(",")

def pkgrepo_default_path() -> str:
    return pkgrepo_paths()[0]

def pkgrepo_names() -> List[str]:
    """
    Return a list of all the package repository names.
    """
    return [os.path.basename(aports) for aports in pkgrepo_paths()]

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
    for aports in pkgrepo_paths():
        g = glob.glob(os.path.join(aports, path))
        if not g:
            continue

        if len(g) != 1:
            raise RuntimeError(f"{path} found multiple matches in {aports}")
        if g:
            return os.path.join(aports, g[0])

    return None


def pkgrepo_iglob(path: str, recursive=False) -> Generator[str, None, None]:
    """
    Yield each matching glob over each aports repository.
    """
    for aports in pkgrepo_paths():
        for g in glob.iglob(os.path.join(aports, path), recursive=recursive):
            yield os.path.join(aports, g)


def pkgrepo_iter_package_dirs() -> Generator[str, None, None]:
    """
    Yield each matching glob over each aports repository.
    Detect duplicates within the same aports repository but otherwise
    ignore all but the first. This allows for overriding packages.
    """
    seen = dict(map(lambda a: (a, []), pkgrepo_paths()))
    for repo in pkgrepo_paths():
        for g in glob.iglob(os.path.join(repo, "**/*/APKBUILD"), recursive=True):
            g = os.path.dirname(g)
            pkg = os.path.basename(g)
            if pkg in seen[repo]:
                raise RuntimeError(f"Package {pkg} found in multiple aports "
                               "subfolders. Please put it only in one folder.")
            if pkg in [x for li in seen.values() for x in li]:
                continue
            seen[repo].append(pkg)
            yield os.path.join(repo, g)

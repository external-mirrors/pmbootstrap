import os
import glob
from pathlib import Path
from collections.abc import Generator

import pmb.config
from pmb.core.context import get_context
from pmb.meta import Cache
from pmb.types import WithExtraRepos


@Cache("with_extra_repos")
def pkgrepo_paths(with_extra_repos: WithExtraRepos = "default") -> list[Path]:
    config = get_context().config
    paths = list(map(lambda x: Path(x), config.aports))
    if not paths:
        raise RuntimeError("No package repositories specified?")

    with_systemd = False

    match with_extra_repos:
        case "disabled":
            return paths
        case "enabled":
            with_systemd = True
        case "default":
            with_systemd = pmb.config.is_systemd_selected(config)

    out_paths = []
    for p in paths:
        # This isn't very generic, but we don't plan to add new extra-repos...
        if (p / "extra-repos/systemd").is_dir() and with_systemd:
            out_paths.append(p / "extra-repos/systemd")
        out_paths.append(p)

    return out_paths


@Cache()
def pkgrepo_default_path() -> Path:
    return pkgrepo_paths(with_extra_repos="disabled")[0]


def pkgrepo_names(with_extra_repos: WithExtraRepos = "default") -> list[str]:
    """
    Return a list of all the package repository names. We REQUIRE
    that the last repository is "pmaports", though the directory
    may be named differently. So we hardcode the name here.
    """
    names = [aports.name for aports in pkgrepo_paths(with_extra_repos)]
    names[-1] = "pmaports"
    return names


def pkgrepo_name(path: Path) -> str:
    """
    Return the name of the package repository with the given path. This
    MUST be used instead of "path.name" as we need special handling
    for the pmaports repository.
    """
    if path == get_context().config.aports[-1]:
        return "pmaports"

    return path.name


def pkgrepo_path(name: str) -> Path:
    """
    Return the absolute path to the package repository with the given name.
    """
    # The pmaports repo is always last, and we hardcode the name.
    if name == "pmaports":
        return get_context().config.aports[-1]

    for aports in pkgrepo_paths():
        if aports.name == name:
            return aports
    raise RuntimeError(f"aports '{name}' not found")


def pkgrepo_name_from_subdir(subdir: Path) -> str:
    """
    Return the name of the package repository for the given directory.
    e.g. "pmaports" for "$WORKDIR/pmaports/main/foobar"
    """
    for aports in pkgrepo_paths():
        if subdir.is_relative_to(aports):
            return pkgrepo_name(aports)
    raise RuntimeError(f"aports subdir '{subdir}' not found")


def pkgrepo_glob_one(path: str) -> Path | None:
    """
    Search for the file denoted by path in all aports repositories.
    path can be a glob.
    """
    for aports in pkgrepo_paths():
        g = glob.glob(os.path.join(aports, path), recursive=True)
        if not g:
            continue

        if len(g) != 1:
            raise RuntimeError(f"{path} found multiple matches in {aports}")
        if g:
            return aports / g[0]

    return None


def pkgrepo_iglob(path: str, recursive: bool = False) -> Generator[Path, None, None]:
    """
    Yield each matching glob over each aports repository.
    """
    for repo in pkgrepo_paths():
        for g in glob.iglob(os.path.join(repo, path), recursive=recursive):
            pdir = Path(g)
            # Skip extra-repos when not parsing the extra-repo itself
            if "extra-repos" not in repo.parts and "extra-repos" in pdir.parts:
                continue
            yield pdir


def pkgrepo_iter_package_dirs(
    with_extra_repos: WithExtraRepos = "default",
) -> Generator[Path, None, None]:
    """
    Yield each matching glob over each aports repository.
    Detect duplicates within the same aports repository but otherwise
    ignore all but the first. This allows for overriding packages.
    """
    seen: dict[str, list[str]] = dict(map(lambda a: (a, []), pkgrepo_names(with_extra_repos)))
    for repo in pkgrepo_paths(with_extra_repos):
        for g in glob.iglob(os.path.join(repo, "**/*/APKBUILD"), recursive=True):
            pdir = Path(g).parent
            # Skip extra-repos when not parsing the extra-repo itself
            if "extra-repos" not in repo.parts and "extra-repos" in pdir.parts:
                continue
            pkg = os.path.basename(pdir)
            if pkg in seen[pkgrepo_name(repo)]:
                raise RuntimeError(
                    f"Package {pkg} found in multiple aports "
                    "subfolders. Please put it only in one folder."
                )
            if pkg in [x for li in seen.values() for x in li]:
                continue
            seen[pkgrepo_name(repo)].append(pkg)
            yield pdir


def pkgrepo_relative_path(path: Path) -> tuple[Path, Path]:
    """
    Return the path relative to the first aports repository.
    """
    for aports in pkgrepo_paths():
        # Cheeky hack to let us jump from an extra-repo to the
        # main aports repository it's a part of
        if path != aports and path.is_relative_to(aports):
            return aports, path.relative_to(aports)
    raise RuntimeError(f"Path '{path}' not in aports repositories")

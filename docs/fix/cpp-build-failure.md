<!-- Canonical: https://getpatchrail.com/fix/cpp-build-failure -->

# C/C++ native build failures — undefined reference / No such file

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/cpp-build-failure](https://getpatchrail.com/fix/cpp-build-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
fatal error: foo.h: No such file or directory
undefined reference to `symbol'
collect2: error: ld returned 1 exit status
CMake Error
use of undeclared identifier
```

## What actually happened

Triage by phase, which the signatures encode: configure (CMake Error) — CMake couldn't find a dependency, compiler, or generator; nothing compiled at all. Compile ("fatal error: foo.h: No such file or directory", "was not declared in this scope" / "use of undeclared identifier" — GCC and Clang dialects of the same thing) — a missing header is almost always a missing system package or include path on the CI image, not a code bug. Link ("undefined reference to", "collect2: error: ld returned", "undefined symbols for architecture") — every object compiled, but a symbol is missing: an unlinked library, wrong link order, a missing extern "C", or an architecture mismatch (common since CI fleets went multi-arch).

## Fix it

1. Find the first error; make/ninja with parallel jobs interleave output and the bottom of the log is rarely the cause. "ninja: build stopped" and "make: *** [target] Error N" are just the messengers.
2. Configure phase: read the CMake error — it names the missing package; install its dev package on the runner or pass the right -D<PKG>_ROOT.
3. Missing header: map header → system package (pg_config.h → libpq-dev etc.) and add it to the CI image. Don't vendor the header to "fix" it.
4. Linker undefined reference: demangle the symbol (c++filt), find which library provides it, ensure it's in the link line after the objects that use it.
5. undefined symbols for architecture: print the arch of every linked artifact (lipo -info / file *.o) — clean and rebuild any stale ones from the other architecture.

## Prevent it

- Build in a pinned container image with all dev packages explicit. "The runner image updated" is the top non-code cause of native build breakage.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```

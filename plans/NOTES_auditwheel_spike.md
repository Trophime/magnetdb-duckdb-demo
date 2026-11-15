# Spike: can the magnettools wheel be made self-contained with auditwheel?

Companion to [PLAN_magnettools_release_pipeline.md](PLAN_magnettools_release_pipeline.md)
— decides between method **(b1)** (wheel needs `libmagnettools1` from apt) and
**(a)** (self-contained wheel repaired by `auditwheel`).

Status: **not run yet**.

## Questions answered by the spike

1. Does `auditwheel` have a policy for trixie's glibc (2.41), i.e. can it
   produce a `manylinux_2_41_x86_64` (or lower) wheel?
2. Does the repaired wheel work on a machine **without** MagnetTools libraries
   and **without** `LD_LIBRARY_PATH`, and give the same numbers?

## Approach

No C++ build and no access to euler needed: reuse the module already compiled
in the local image `trophime/magnettools:trixie` (deb `python3-magnettools`
1.2.1-1). Its `.so` files are byte-identical to what a real build of that
version produces, so the auditwheel result transfers directly.

1. **Pack** — wrap the installed `magnettools/` package (`.so` + `.py`) into a
   wheel by hand (`dist-info` written manually, zipped with `wheel pack`).
   A plain setuptools build would tag it `py3-none-any`, which auditwheel
   refuses.
2. **Show + repair** — `auditwheel show`, then `auditwheel repair` (bundles
   the external `.so` into `magnettools.libs/`, rewrites RPATHs to `$ORIGIN`).
3. **Keep results** — everything lands in `$OUT` (bind-mounted, owned by you).
4. **Clean test** — install the repaired wheel in `python:3.13-slim` (no
   MagnetTools, no `LD_LIBRARY_PATH`), check `ldd`, run a computation, compare
   with the reference computed with the deb.
5. **Host test (optional)** — same on this Ubuntu host (glibc 2.43) in a uv
   venv with Python 3.13.

Nothing is published; the test wheel lacks dependency metadata (fine for an
import test — the real release builds it with scikit-build-core from
`pyproject.toml.in`).

## Known facts (from inspecting `trophime/magnettools:trixie`)

| Item | Value |
|---|---|
| glibc | 2.41 (Debian 13) |
| Module | `/usr/lib/python3/dist-packages/magnettools/magnettools.cpython-313-x86_64-linux-gnu.so` |
| RUNPATH | `/usr/lib/x86_64-linux-gnu:/lib:/usr/lib/x86_64-linux-gnu/MagnetTools` (direct deps only — `libmagnetfield` → `libutils` still needs `LD_LIBRARY_PATH` today) |
| External libs to bundle | `libmagnetfield.so.1`, `libutils.so.1`, `libcooling.so.1` (1.4 MB total), `libgsl.so.28`, `libgslcblas.so.0`, `libfreesteam.so.2`, `libboost_filesystem.so.1.83.0`, `libboost_iostreams.so.1.83.0`, `libz`, `libbz2`, `liblzma`, `libzstd` |
| Versions | deb `1.2.1-1`, but `magnettools/__version.py` says `1.2.0` |
| Package imports | numpy, pandas, scipy, mpmath, matplotlib, mplcursors, tabulate |
| Image size | 2.1 GB (the deb pulls the full scientific Python stack) |
| Host | Ubuntu, glibc 2.43, Python **3.14** (a cp313 wheel needs a 3.13 interpreter → uv), no `uv` installed |

## Prerequisites

- Docker (this workstation: Docker 29.9, buildx 0.38).
- Local image `trophime/magnettools:trixie`.
- Internet access to Docker Hub (`python:3.13-slim`) and PyPI.
- **Not** needed: LNCMI network/VPN, apt-depot key.

## Commands

### 0. Setup

```bash
OUT="$HOME/auditwheel-spike"        # any directory outside git repos
mkdir -p "$OUT/repaired"

# computation used both for the reference and the clean test
# (from my-magnettools/Python/tests/test-basic.py)
cat > "$OUT/check.py" <<'PY'
import magnettools as mt

r1, r2, h = 75.0e-3, 100.0e-3, 50.0e-3
j, fill, rho = 125.201888e6, 1, 1.7241379310345e-08
a = mt.BitterMagnet(r2, r1, h, j, 0.076, fill, rho)
b = mt.BitterMagnet(r2, r1, h, j, -0.076, fill, rho)
print("file:", mt.__file__)
print("B_a(0,0):", a.MagneticField(0.0, 0.0))
print("L_a:", a.Inductance())
print("M_ab:", mt.Mutual(a, b))
PY
```

### 1–3. Pack, show, repair, reference (in `trophime/magnettools:trixie`)

```bash
docker run --rm -i --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$OUT:/out" \
  --entrypoint bash trophime/magnettools:trixie -s <<'EOF'
set -euo pipefail
PKG=/usr/lib/python3/dist-packages/magnettools
VER=$(python3 -c "exec(open('$PKG/__version.py').read()); print(version)")
echo "module version: $VER (deb: $(dpkg-query -W -f='${Version}' python3-magnettools))"

# reference numbers with the deb-installed module
/usr/bin/python3 /out/check.py | tee /out/reference.txt

# tools in a throwaway venv (system pip is PEP 668 managed)
python3 -m venv /tmp/tools
/tmp/tools/bin/pip install --quiet wheel auditwheel patchelf
export PATH=/tmp/tools/bin:$PATH
auditwheel --version

# 1. pack the installed package into a platform wheel
STAGE=/tmp/stage
DI=$STAGE/magnettools-$VER.dist-info
mkdir -p "$DI"
cp -r "$PKG" "$STAGE/"
rm -rf "$STAGE/magnettools/__pycache__"
printf 'Metadata-Version: 2.1\nName: magnettools\nVersion: %s\n' "$VER" > "$DI/METADATA"
printf 'Wheel-Version: 1.0\nGenerator: manual\nRoot-Is-Purelib: false\nTag: cp313-cp313-linux_x86_64\n' > "$DI/WHEEL"
wheel pack "$STAGE" -d /out
WHL=/out/magnettools-$VER-cp313-cp313-linux_x86_64.whl

# 2. show: which libs are external, which manylinux tag is reachable
export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/MagnetTools
auditwheel show "$WHL" | tee /out/auditwheel-show.txt
PLAT=$(grep -oE 'constrains the platform tag to "manylinux_[0-9]+_[0-9]+_x86_64"' /out/auditwheel-show.txt \
       | grep -oE 'manylinux_[0-9_]+x86_64' || true)
PLAT=${PLAT:-manylinux_2_41_x86_64}
echo "repair target: $PLAT"

# 2. repair: bundle external libs, rewrite RPATHs
auditwheel repair --plat "$PLAT" -w /out/repaired "$WHL" 2>&1 | tee /out/auditwheel-repair.txt

# 3. record what ended up in the wheel
python3 -m zipfile -l /out/repaired/magnettools-*.whl | tee /out/repaired-content.txt
EOF
```

### 4. Clean test (`python:3.13-slim`, no MagnetTools, no `LD_LIBRARY_PATH`)

```bash
docker run --rm -i -v "$OUT:/out:ro" python:3.13-slim bash -s <<'EOF' | tee "$OUT/test.log"
set -euo pipefail
pip install --quiet --root-user-action=ignore /out/repaired/magnettools-*.whl \
    numpy pandas scipy mpmath matplotlib mplcursors tabulate
echo "LD_LIBRARY_PATH='${LD_LIBRARY_PATH:-}'"
SO_DIR=$(python -c "import importlib.util, os; print(os.path.dirname(importlib.util.find_spec('magnettools').origin))")
if ldd "$SO_DIR"/magnettools*.so | grep 'not found'; then
    echo "FAIL: unresolved libraries"; exit 1
fi
echo "ldd: all libraries resolved"
python /out/check.py
EOF

# same numbers as the deb-installed module?
diff <(grep -E '^(B_a|L_a|M_ab)' "$OUT/reference.txt") \
     <(grep -E '^(B_a|L_a|M_ab)' "$OUT/test.log") && echo "RESULTS IDENTICAL"
```

### 5. Host test (optional, needs uv for Python 3.13)

```bash
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh   # user-local install
uv venv --python 3.13 "$OUT/hostvenv"                               # downloads a 3.13 interpreter
uv pip install --python "$OUT/hostvenv/bin/python" "$OUT"/repaired/magnettools-*.whl \
    numpy pandas scipy mpmath matplotlib mplcursors tabulate
"$OUT/hostvenv/bin/python" "$OUT/check.py"
```

## Reading the results

| Observation | Meaning | Next |
|---|---|---|
| `auditwheel-show.txt` constrains to `manylinux_2_XX` with XX ≤ 41, repair succeeds | Risk 1 cleared | continue |
| Show only reaches `linux_x86_64`, or repair fails with "too-recent versioned symbols" / unknown policy | auditwheel has no policy for glibc 2.41 | build on **bookworm** (glibc 2.36, also covers Ubuntu 24.04) or a manylinux image |
| Step 4: `ldd` reports `not found` | a library was not bundled | inspect `auditwheel-repair.txt`, `repaired-content.txt` |
| Step 4: `ImportError: undefined symbol` | ABI mismatch between bundled libs | inspect which lib; may need bundling exclusions |
| Step 4: import OK, `RESULTS IDENTICAL` | Risk 2 cleared — **(a) is viable** | add variant (a) to the plan |
| Numbers differ | unexpected (same `.so`) | investigate before going further |

Also note from `repaired-content.txt`: `magnettools.libs/` will contain
`libgsl` and `libfreesteam` (GPL) — see the licensing question in the plan;
it applies to the public (b1) image as well.

## Cleanup

```bash
rm -rf "$OUT"
docker image rm python:3.13-slim     # optional
```

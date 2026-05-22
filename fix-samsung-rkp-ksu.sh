#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "[1/5] Fix override_creds const mismatch..."

python3 - <<'PY'
from pathlib import Path

p = Path("include/linux/cred.h")
s = p.read_text()

old = "#define override_creds(x) rkp_override_creds(&x)"
new = "#define override_creds(x) rkp_override_creds((struct cred **)&(x))"

if old in s:
    s = s.replace(old, new)
    print("patched include/linux/cred.h")
else:
    print("override_creds pattern not found or already patched")

p.write_text(s)
PY


echo "[2/5] Add missing RKP mount helper prototypes..."

python3 - <<'PY'
from pathlib import Path

p = Path("include/linux/mount.h")
s = p.read_text()

add = """
extern void rkp_set_mnt_flags(struct vfsmount *mnt, int flags);
extern void rkp_reset_mnt_flags(struct vfsmount *mnt, int flags);
"""

if "rkp_set_mnt_flags" not in s:
    if "\n#endif" not in s:
        raise SystemExit("Could not find final #endif in include/linux/mount.h")

    head, tail = s.rsplit("\n#endif", 1)
    s = head + add + "\n#endif" + tail
    print("patched include/linux/mount.h")
else:
    print("RKP mount prototypes already present")

p.write_text(s)
PY


echo "[3/5] Remove unsupported GCC warning flags from KernelSU..."

grep -RIl -- "-Wno-gcc-compat\|-Wno-int-conversion" drivers/kernelsu 2>/dev/null | \
  xargs -r sed -i \
    -e 's/-Wno-gcc-compat//g' \
    -e 's/-Wno-int-conversion//g'


echo "[4/5] Fix KernelSU ns_get_path return type issue..."

python3 - <<'PY'
from pathlib import Path

p = Path("drivers/kernelsu/infra/su_mount_ns.c")
s = p.read_text()

old = "long ret = ns_get_path(&ns_path, pid1_task, &mntns_operations);"
new = "void *ret = ns_get_path(&ns_path, pid1_task, &mntns_operations);"

if old in s:
    s = s.replace(old, new)
    print("patched ret type")
else:
    print("ret type pattern not found or already patched")

old_block = """if (ret) {
        return ret;
    }"""

new_block = """if (IS_ERR(ret)) {
        return PTR_ERR(ret);
    }"""

if old_block in s:
    s = s.replace(old_block, new_block, 1)
    print("patched error handling block")
else:
    print("exact error handling block not found, check manually")

p.write_text(s)
PY


echo "[5/5] Show patched lines..."

grep -n "override_creds\|rkp_override_creds" include/linux/cred.h || true
grep -n "rkp_set_mnt_flags\|rkp_reset_mnt_flags" include/linux/mount.h || true
grep -n "ns_get_path\|IS_ERR(ret)\|PTR_ERR(ret)" drivers/kernelsu/infra/su_mount_ns.c || true

echo
echo "Done."

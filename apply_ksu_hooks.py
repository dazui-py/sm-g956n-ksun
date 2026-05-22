#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(".").resolve()

FILES = [
    "fs/exec.c",
    "fs/open.c",
    "fs/read_write.c",
    "fs/stat.c",
    "kernel/reboot.c",
]

def die(msg):
    print(f"[ERRO] {msg}")
    sys.exit(1)

def read(path):
    p = ROOT / path
    if not p.exists():
        die(f"ficheiro não encontrado: {p}")
    return p.read_text(errors="replace")

def write(path, data):
    p = ROOT / path
    p.write_text(data)
    print(f"[OK] {path}")

def replace_once(data, old, new, file):
    if old not in data:
        die(f"padrão não encontrado em {file}")
    return data.replace(old, new, 1)

def insert_before(data, marker, block, file):
    if block.strip() in data:
        return data
    if marker not in data:
        die(f"marcador não encontrado em {file}")
    return data.replace(marker, block + marker, 1)

def patch_exec():
    file = "fs/exec.c"
    s = read(file)

    proto = """#ifdef CONFIG_KSU
__attribute__((hot))
extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
			       void *argv, void *envp, int *flags);
#endif

"""

    s = insert_before(s, "int do_execve(struct filename *filename,", proto, file)

    old = """	struct user_arg_ptr argv = { .ptr.native = __argv };
	struct user_arg_ptr envp = { .ptr.native = __envp };
	return do_execveat_common(AT_FDCWD, filename, argv, envp, 0);
"""

    new = """	struct user_arg_ptr argv = { .ptr.native = __argv };
	struct user_arg_ptr envp = { .ptr.native = __envp };
	int ksu_execve_dfd = AT_FDCWD;
	int ksu_execve_flags = 0;
#ifdef CONFIG_KSU
	ksu_handle_execveat(&ksu_execve_dfd, &filename, &argv, &envp, &ksu_execve_flags);
#endif
	return do_execveat_common(ksu_execve_dfd, filename, argv, envp, ksu_execve_flags);
"""

    if "ksu_execve_dfd" not in s:
        s = replace_once(s, old, new, file)

    old = """	struct user_arg_ptr envp = {
		.is_compat = true,
		.ptr.compat = __envp,
	};
	return do_execveat_common(AT_FDCWD, filename, argv, envp, 0);
"""

    new = """	struct user_arg_ptr envp = {
		.is_compat = true,
		.ptr.compat = __envp,
	};
	int ksu_compat_execve_dfd = AT_FDCWD;
	int ksu_compat_execve_flags = 0;
#ifdef CONFIG_KSU
	ksu_handle_execveat(&ksu_compat_execve_dfd, &filename, &argv, &envp, &ksu_compat_execve_flags);
#endif
	return do_execveat_common(ksu_compat_execve_dfd, filename, argv, envp, ksu_compat_execve_flags);
"""

    if "ksu_compat_execve_dfd" not in s:
        s = replace_once(s, old, new, file)

    write(file, s)

def patch_open():
    file = "fs/open.c"
    s = read(file)

    proto = """#ifdef CONFIG_KSU
__attribute__((hot))
extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user,
				int *mode, int *flags);
#endif

"""

    s = insert_before(s, "/*\n * access() needs to use the real uid/gid", proto, file)

    old = """	unsigned int lookup_flags = LOOKUP_FOLLOW;

	if (mode & ~S_IRWXO)"""
    new = """	unsigned int lookup_flags = LOOKUP_FOLLOW;

#ifdef CONFIG_KSU
	ksu_handle_faccessat(&dfd, &filename, &mode, NULL);
#endif

	if (mode & ~S_IRWXO)"""

    if "ksu_handle_faccessat(&dfd, &filename, &mode, NULL);" not in s:
        s = replace_once(s, old, new, file)

    write(file, s)

def patch_read_write():
    file = "fs/read_write.c"
    s = read(file)

    proto = """#ifdef CONFIG_KSU
extern bool ksu_vfs_read_hook __read_mostly;
extern __attribute__((cold)) int ksu_handle_sys_read(unsigned int fd,
				char __user **buf_ptr, size_t *count_ptr);
#endif

"""

    s = insert_before(s, "SYSCALL_DEFINE3(read, unsigned int, fd, char __user *, buf, size_t, count)", proto, file)

    old = """	struct fd f = fdget_pos(fd);
	ssize_t ret = -EBADF;

	if (f.file) {"""

    new = """	struct fd f = fdget_pos(fd);
	ssize_t ret = -EBADF;

#ifdef CONFIG_KSU
	if (unlikely(ksu_vfs_read_hook))
		ksu_handle_sys_read(fd, &buf, &count);
#endif

	if (f.file) {"""

    if "ksu_handle_sys_read(fd, &buf, &count);" not in s:
        s = replace_once(s, old, new, file)

    write(file, s)

def patch_stat():
    file = "fs/stat.c"
    s = read(file)

    proto = """#ifdef CONFIG_KSU
__attribute__((hot))
extern int ksu_handle_stat(int *dfd, const char __user **filename_user,
				int *flags);
#endif

"""

    s = insert_before(s, "#if !defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_SYS_NEWFSTATAT)", proto, file)

    old = """	struct kstat stat;
	int error;

	error = vfs_fstatat(dfd, filename, &stat, flag);"""

    new = """	struct kstat stat;
	int error;

#ifdef CONFIG_KSU
	ksu_handle_stat(&dfd, &filename, &flag);
#endif

	error = vfs_fstatat(dfd, filename, &stat, flag);"""

    if "ksu_handle_stat(&dfd, &filename, &flag);" not in s:
        s = replace_once(s, old, new, file)

    write(file, s)

def patch_reboot():
    file = "kernel/reboot.c"
    s = read(file)

    proto = """#ifdef CONFIG_KSU
extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd,
				 void __user **arg);
#endif

"""

    s = insert_before(s, "SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,", proto, file)

    old = """	char buffer[256];
	int ret = 0;

	/* We only trust the superuser with rebooting the system. */"""

    new = """	char buffer[256];
	int ret = 0;

#ifdef CONFIG_KSU
	ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);
#endif

	/* We only trust the superuser with rebooting the system. */"""

    if "ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);" not in s:
        s = replace_once(s, old, new, file)

    write(file, s)

def main():
    for f in FILES:
        if not (ROOT / f).exists():
            die(f"falta: {ROOT / f}")

    patch_exec()
    patch_open()
    patch_read_write()
    patch_stat()
    patch_reboot()

    print("\nFeito.")
    print("Agora testa:")
    print("  git diff --check")
    print("  git diff -- fs/exec.c fs/open.c fs/read_write.c fs/stat.c kernel/reboot.c")
    print("\nPara criar o patch final:")
    print("  git diff -- fs/exec.c fs/open.c fs/read_write.c fs/stat.c kernel/reboot.c > patches/ksu-hooks.patch")

if __name__ == "__main__":
    main()

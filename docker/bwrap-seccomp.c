#define _GNU_SOURCE
#include <errno.h>
#include <linux/sched.h>
#include <seccomp.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

/*
 * Applied by bubblewrap after its mount and namespace setup. The outer Docker
 * seccomp profile has to allow these setup syscalls, so deny them again for the
 * untrusted agent process. Keep ordinary process/thread creation available.
 */
int main(void) {
  scmp_filter_ctx filter = seccomp_init(SCMP_ACT_ALLOW);
  if (filter == NULL) {
    perror("seccomp_init");
    return 1;
  }

  const char *denied[] = {
      "bpf",          "fsconfig",    "fsmount",     "fsopen",
      "keyctl",       "mount",       "mount_setattr",
      "move_mount",   "open_tree",   "perf_event_open", "pivot_root",
      "setns",        "umount2",     "unshare",
  };
  for (size_t i = 0; i < sizeof(denied) / sizeof(denied[0]); ++i) {
    int syscall_nr = seccomp_syscall_resolve_name(denied[i]);
    if (syscall_nr >= 0 &&
        seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), syscall_nr, 0) < 0) {
      fprintf(stderr, "could not deny syscall %s\n", denied[i]);
      seccomp_release(filter);
      return 1;
    }
  }

  int clone3 = seccomp_syscall_resolve_name("clone3");
  if (clone3 >= 0 &&
      seccomp_rule_add(filter, SCMP_ACT_ERRNO(ENOSYS), clone3, 0) < 0) {
    fprintf(stderr, "could not make clone3 fall back to clone\n");
    seccomp_release(filter);
    return 1;
  }

  const unsigned int namespace_flags[] = {
      CLONE_NEWNS, CLONE_NEWCGROUP, CLONE_NEWUTS, CLONE_NEWIPC,
      CLONE_NEWUSER, CLONE_NEWPID, CLONE_NEWNET,
  };
  for (size_t i = 0; i < sizeof(namespace_flags) / sizeof(namespace_flags[0]); ++i) {
    if (seccomp_rule_add(filter, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(clone), 1,
                         SCMP_A0(SCMP_CMP_MASKED_EQ, namespace_flags[i],
                                 namespace_flags[i])) < 0) {
      fprintf(stderr, "could not deny clone namespace flag 0x%x\n",
              namespace_flags[i]);
      seccomp_release(filter);
      return 1;
    }
  }

  int result = seccomp_export_bpf(filter, STDOUT_FILENO);
  if (result < 0) perror("seccomp_export_bpf");
  seccomp_release(filter);
  return result < 0 ? 1 : 0;
}

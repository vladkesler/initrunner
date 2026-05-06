# Sandbox Backend Comparison

This page compares InitRunner's sandbox backends against the harder isolation primitives you can layer on top of the Docker backend. Use it to pick the right tradeoff for a given role, and to answer the "but does it support microVMs?" question without hand-waving.

For the operational config reference, see [Runtime Sandbox](sandbox.md). For per-backend deep-dives, see [Bubblewrap](bubblewrap.md), [Docker](docker-sandbox.md), and [SSH](ssh-sandbox.md).

## Isolation classes, not interchangeable

The choices below are not all the same kind of thing. Three distinct isolation classes show up in this matrix:

- **Container.** Shares the host kernel. Isolation comes from Linux namespaces, cgroups, seccomp, and capability dropping. This is `runc` (Docker's default) and `bwrap`.
- **Userspace kernel.** A user-space process intercepts and reimplements the syscall surface. The host kernel is still underneath but the guest only touches it through a narrow, audited boundary. This is gVisor (`runsc`). It is **not** a microVM.
- **microVM.** A real guest kernel runs inside a lightweight hypervisor. Container-like UX, VM-grade isolation, ~125ms cold start. This is Kata Containers (Firecracker, QEMU, or Cloud Hypervisor under the hood) and bare Firecracker.

Calling everything "a sandbox" hides the part that matters. A vendor saying "we have microVMs" without naming the runtime usually means Kata or Firecracker; a vendor saying "we have gVisor sandboxes" is in a different (and weaker, but cheaper and faster) class.

## Backends and runtimes at a glance

| Backend / runtime | Class | Shares host kernel | Cold start | Linux only | Daemon | Native InitRunner support |
|---|---|---|---|---|---|---|
| `bwrap` | Container | yes | ~fork+exec | yes | no | first-class |
| `docker` (runtime: `runc`) | Container | yes | ~200-500ms | no (also macOS, Windows) | yes (Docker) | first-class |
| `docker` (runtime: `runsc`) | Userspace kernel | partial (syscall boundary) | ~250-700ms | yes | yes (Docker) | via `docker.runtime` |
| `docker` (runtime: `kata-runtime` / `kata-qemu` / `kata-fc` / `kata-clh`) | microVM | no | ~100-300ms | yes | yes (Docker + Kata) | via `docker.runtime` |
| Bare Firecracker | microVM | no | ~125ms | yes (KVM required) | none | not in v1 (see below) |
| `ssh` | Remote execution, not isolation | n/a | network-bound | n/a | no | first-class for remote runs |

A few things this matrix doesn't capture in cells:

- **`runc` vs `bwrap` isolation strength is roughly equivalent at the kernel-attack-surface level.** They differ on operational shape (daemon vs no daemon, image vs host filesystem, cross-platform vs Linux-only), not on the size of the kernel they share with you.
- **gVisor's cost isn't latency, it's compatibility.** Some syscalls aren't implemented; some are slower. Most general-purpose code runs fine; numerical kernels and io_uring-heavy workloads need testing.
- **Kata's cost isn't latency either.** It's host setup. KVM, nested virt if you're already inside a VM, and a kernel image that works for your guest. On a clean Linux host it's an apt-get and a daemon restart; on a CI runner inside a VM it can be a multi-hour yak shave.
- **Bare Firecracker is great for serverless platforms and a poor fit for "swap in for one tool call."** You own the rootfs, the jailer, the vsock plumbing, and the lifecycle. We'd take it on if a design partner needs daemon-free microVMs and accepts the cost; otherwise Kata-on-Docker covers the same threat model with code we already have.

## Use X when...

**Use `bwrap` when** you're on Linux, you don't have or want a Docker daemon, and the audit chain + ABAC layer above the sandbox is your real defense. This is the right default for most personal and CI use. Fast, no daemon, no image pulls.

**Use plain Docker (`runc`) when** you need cross-platform (macOS or Windows dev hosts), pinned OS images, or bridge networking with a user-defined network. Same kernel-isolation strength as `bwrap`, different operational shape.

**Use Docker + `runsc` (gVisor) when** you're running code you don't trust at the syscall level (LLM-generated shell, untrusted user-submitted scripts) but a microVM is overkill. Userspace kernel boundary, narrow attack surface, no hypervisor required. Compatible with most Python / Node / Go workloads. Test compatibility for native binaries with unusual syscall patterns.

**Use Docker + Kata (microVM) when** the threat model says "this code may exploit a kernel CVE" and your enterprise security review wants a vendor checkbox that says "microVM." Real guest kernel, real hypervisor, container UX. Requires the host to be able to run a hypervisor.

**Use bare Firecracker when** you're building a serverless agent platform that runs many short-lived microVMs, you want no Docker daemon in the loop, and you accept owning the rootfs / jailer / orchestration. Out of scope for InitRunner v1.

**Use `ssh` when** you want code to run on a specific machine (a build server, a GPU box, a customer-owned environment), not for containment. SSH is *where*, not *how-isolated*.

## Threat models we cover, and what each backend buys you

| Concern | `bwrap` | Docker (`runc`) | Docker + `runsc` | Docker + Kata |
|---|---|---|---|---|
| Filesystem write outside sandbox | blocked | blocked | blocked | blocked |
| Network egress (when `network: none`) | blocked (kernel) | blocked (kernel) | blocked (kernel) | blocked (kernel) |
| Reading host home dir / SSH keys | blocked | blocked | blocked | blocked |
| Resource exhaustion (fork bomb, OOM, runaway CPU) | systemd-run limits | cgroups | cgroups | cgroups |
| Container escape via kernel CVE | host kernel exposed | host kernel exposed | userspace boundary in front | guest kernel + hypervisor in front |
| Spectre-class side channels | host kernel exposed | host kernel exposed | partial mitigation | hypervisor boundary |
| Confused-deputy via shared mounts | mitigated by `read_only_rootfs` and explicit `bind_mounts` | same | same | same |

The rows where `bwrap` and Docker (`runc`) line up are the same kernel-attack-surface story. The interesting deltas are the bottom three rows, which is exactly what gVisor and Kata exist to address.

## What InitRunner adds on top of any of these

The sandbox is one layer. The rest of InitRunner's threat model lives outside the sandbox:

- **HMAC-signed audit chain** ([audit-chain.md](audit-chain.md)) so post-incident review has tamper-evident records of what tools ran with what arguments.
- **ABAC / capability gating** ([agent-policy.md](agent-policy.md)) so a compromised agent can't reach for a tool it was never granted.
- **PEP 578 audit hook sandbox** ([security.md](security.md)) for custom Python tools that run in-process.
- **SSRF guards** for web tools that run outside the sandbox.

For most threat models, layering a real microVM under the same audit/ABAC/SSRF surface is the upgrade path; ripping out the audit chain to chase microVMs is the wrong trade.

## How to verify what you've actually got

```bash
# Provider, daemon, and connectivity checks for a specific role:
initrunner doctor --role path/to/role.yaml --deep

# Schema validation plus a plain-language summary of the sandbox section:
initrunner validate path/to/role.yaml --explain

# For Docker: which runtimes are registered?
docker info --format '{{json .Runtimes}}' | jq 'keys'
```

If a role's `security.sandbox.docker.runtime` isn't in that last list, preflight will fail with a remediation hint at agent startup. That's the loud failure we want; silent fallback to `runc` would be a security regression.

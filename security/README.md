# Security Profiles

This directory contains security profiles for runtime container sandboxing.

## Files

### seccomp-profile.json
**Seccomp (Secure Computing Mode) Security Profile**

Restricts system calls available to containers, allowing only safe operations.

**Usage:**

```bash
# Docker
docker run --security-opt seccomp=security/seccomp-profile.json ...

# Docker Compose
security_opt:
  - seccomp=security/seccomp-profile.json

# Kubernetes
securityContext:
  seccompProfile:
    type: Localhost
    localhostProfile: profiles/seccomp-profile.json
```

**Allowed System Calls:**
- File operations (read, write, open, close)
- Network operations (socket, connect, send, recv)
- Process management (fork, exec, wait)
- Memory management (mmap, munmap, brk)
- Time operations (clock_gettime, nanosleep)
- Signal handling (sigaction, sigreturn)

**Blocked System Calls:**
- Kernel module loading (init_module, delete_module)
- Raw I/O operations (ioperm, iopl)
- Privilege escalation (ptrace, process_vm_readv)
- System administration (reboot, mount, umount)

### apparmor-profile.conf
**AppArmor Mandatory Access Control Profile**

Provides fine-grained access control for files, capabilities, and network.

**Usage:**

```bash
# Load profile
sudo apparmor_parser -r security/apparmor-profile.conf

# Docker with AppArmor
docker run --security-opt apparmor=nija-bot ...

# Docker Compose
security_opt:
  - apparmor=nija-bot
```

**Permissions:**

✅ **Allowed:**
- Read application code (`/app/**`)
- Read/write cache and logs (`/app/cache`, `/app/logs`)
- Network operations (required for API calls)
- Python runtime execution
- SSL/TLS certificates

❌ **Denied:**
- Write to application code
- System administration capabilities
- Access to kernel debug interfaces
- Access to other containers
- Raw device access

## Security Layers

NIJA implements defense-in-depth with multiple security layers:

### Layer 1: User Isolation
- Runs as non-root user (UID 1000)
- No privilege escalation possible
- Minimal user permissions

### Layer 2: Filesystem Security
- Read-only root filesystem
- Writable volumes only for necessary directories
- No code modification at runtime

### Layer 3: System Call Filtering (Seccomp)
- Whitelist-based approach
- Only safe system calls allowed
- Blocks kernel-level operations

### Layer 4: Mandatory Access Control (AppArmor)
- File access restrictions
- Network policy enforcement
- Capability dropping

### Layer 5: Resource Limits
- CPU limits (prevent DoS)
- Memory limits (prevent exhaustion)
- Network bandwidth limits

### Layer 6: Network Isolation
- Bridge network only
- No host network access
- Firewall rules enforced

## Testing Security Profiles

### Test Seccomp Profile

```bash
# Build with seccomp
docker build -t nija-test .

# Run with seccomp profile
docker run --rm \
  --security-opt seccomp=security/seccomp-profile.json \
  nija-test \
  python -c "import os; os.system('ls')"

# Should work (ls uses allowed syscalls)

# Try blocked operation
docker run --rm \
  --security-opt seccomp=security/seccomp-profile.json \
  nija-test \
  python -c "import os; os.mount('/dev/sda1', '/mnt', 'ext4')"

# Should fail (mount is blocked)
```

### Test AppArmor Profile

```bash
# Load profile
sudo apparmor_parser -r security/apparmor-profile.conf

# Run with AppArmor
docker run --rm \
  --security-opt apparmor=nija-bot \
  nija-test \
  cat /app/bot/trading_strategy.py

# Should work (read allowed)

# Try write to code
docker run --rm \
  --security-opt apparmor=nija-bot \
  nija-test \
  bash -c "echo 'malicious code' > /app/bot/trading_strategy.py"

# Should fail (write to code denied)
```

## Kubernetes Integration

### Apply Security Profiles

```bash
# Create seccomp ConfigMap
kubectl create configmap nija-seccomp \
  --from-file=security/seccomp-profile.json \
  -n nija

# Apply Pod Security Policy
kubectl apply -f k8s/security/pod-security-policy.yaml

# Apply Security Context Constraints
kubectl apply -f k8s/security/resource-limits.yaml
```

### Verify Security Context

```bash
# Check pod security context
kubectl get pod -n nija -o jsonpath='{.items[0].spec.securityContext}'

# Check container security context
kubectl get pod -n nija -o jsonpath='{.items[0].spec.containers[0].securityContext}'
```

## Troubleshooting

### Permission Denied Errors

If you see permission errors:

1. Check user/group ownership:
   ```bash
   ls -la /app
   ```

2. Verify writable volumes:
   ```bash
   docker run --rm nija-test touch /app/cache/test.txt
   ```

3. Check AppArmor denials:
   ```bash
   sudo grep DENIED /var/log/syslog
   ```

### Seccomp Violations

If container fails to start with seccomp:

1. Check which syscall was blocked:
   ```bash
   docker logs <container-id>
   ```

2. Add syscall to profile if safe:
   ```json
   "syscalls": [{
     "names": ["new_syscall"],
     "action": "SCMP_ACT_ALLOW"
   }]
   ```

3. Test the change:
   ```bash
   docker run --security-opt seccomp=security/seccomp-profile.json ...
   ```

## Best Practices

1. **Never disable security features** in production
2. **Test profiles** thoroughly in staging
3. **Review audit logs** regularly
4. **Update profiles** when adding new functionality
5. **Document exceptions** when relaxing restrictions

## References

- [Docker Seccomp](https://docs.docker.com/engine/security/seccomp/)
- [AppArmor Documentation](https://gitlab.com/apparmor/apparmor/-/wikis/Documentation)
- [Kubernetes Security Context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/)
- [Container Security Best Practices](https://www.nist.gov/publications/application-container-security-guide)

---

**Last Updated**: January 29, 2026  
**Maintained By**: Security Team

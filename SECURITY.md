# Security Policy

## Supported Versions

turiya is released from `main` and versioned with semantic versioning. Security
fixes are applied to the current `2.x` line.

| Version | Supported |
|---------|-----------|
| `2.x`   | ✅        |
| `< 2.0` | ❌        |

## Reporting a Vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through GitHub's **[private vulnerability reporting](https://github.com/masriamir/turiya/security/advisories/new)**
(the "Report a vulnerability" button under this repository's **Security** tab).
This creates a private advisory visible only to you and the maintainer.

You can expect an acknowledgement within **3 business days**. We will confirm the
issue, agree on a disclosure timeline with you, and credit you in the advisory
unless you prefer to remain anonymous.

## Scope

**In scope** — defects in turiya's own code, including:

- handling of the restic repository password (Keychain access, environment
  passing, and log redaction);
- construction of `restic`, `rclone`, `launchctl`, and other subprocess
  invocations;
- the launchd/pmset scheduling artifacts turiya writes.

**Out of scope** — vulnerabilities in `restic`, `rclone`, the cloud remotes, or
macOS themselves. Please report those to their respective upstream projects.

## Safe Harbor

We consider good-faith security research that respects this policy to be
authorized. We will not pursue or support legal action against researchers who
report vulnerabilities responsibly and avoid privacy violations, data
destruction, or service disruption while investigating.

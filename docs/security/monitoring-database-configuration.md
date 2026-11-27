# Protected database configuration for optional monitoring templates

The Supervisor and systemd monitoring examples no longer supply a public example
database password. They require externally provisioned configuration instead.
These are optional legacy monitoring templates. They are not the existing Render
trading service's startup configuration; do not install or enable them as part
of Kraken collector recovery.

Supervisor expands `%(ENV_DATABASE_URL)s` from the environment of supervisord.
Provision the intended database connection through that process's protected
environment before loading either template. An absent variable causes
configuration loading to fail. An empty or incorrect value is not a valid
database binding and must be rejected during installation review.

The two systemd units require `/etc/nija/monitoring.env`. The path is deliberately
not prefixed with `-`, so an absent file prevents unit startup. Provision it
privately, owned by root with mode 0600, with the intended DATABASE_URL value.
Do not place its contents in GitHub, shell history, screenshots or logs. Do not
overwrite an existing environment file or switch an existing database without
reviewing the effective configuration and preserving existing data.

No database, credential, account, service, environment file or production setting
is created or modified by this repository change. Existing process identities,
monitoring commands, intervals and restart behavior remain unchanged. Database
connectivity, ownership and backup/restore remain installation checks; removing
example credentials does not certify them or authorize trading.

References:
- https://docs.supervisord.org/configuration.html#environment-variables
- https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#EnvironmentFile=

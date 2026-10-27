# Production workflow

The production system runs on Ubuntu VM 192.168.84.121 as user gaohongyuan1.
The authoritative Git working copy is /home/gaohongyuan1/pudu-materials-operation/repo.
Make system code changes in that VM working copy and commit/push them to GitLab.
Do not use or restart the retired Windows material-system runtimes. The separate
PUDU Lead Intake Worker is outside this project's scope and must remain intact.

Deploy immutable Git releases under /home/gaohongyuan1/pudu-materials-operation/releases
and atomically switch source. Keep configuration, database, media and extension
state under shared; never put credentials or private state into Git.

For a formal release increment APP_VERSION with scripts/bump_release_version.py,
run the relevant tests including the isolated PostgreSQL tests, build the frontend
on the VM, commit/push, inspect active queues before restarting, and verify the
public health endpoint and affected business behavior after deployment. A process
being active or a task merely entering a queue is insufficient evidence.

Use isolated restored/test databases for stock changes, deletions, quotas and
notification tests; follow with read-only production verification. Never send
test notifications to employees. PostgreSQL is authoritative for normal frontend
writes, with a transactional Feishu outbox and independent notification effects.
The daily reconciliation at 03:00 Asia/Shanghai adopts Feishu data. Retain the
existing shipping-template and shipping-schedule auxiliary functionality.

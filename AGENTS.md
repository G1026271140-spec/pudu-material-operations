# Production workflow

The production system runs on Ubuntu VM 192.168.84.121 as user gaohongyuan1.
The authoritative Git working copy is /home/gaohongyuan1/pudu-materials-operation/repo.
Make code changes in your own VM workspace under /srv/pudu-materials-workspaces/<account>.
The integration checkout is managed by the release command; commit in your personal workspace,
then use sudo pudu-release to merge, validate, push GitLab and deploy.
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


## Concurrent administrators

gaohongyuan1 and weiwei have independent workspaces under
/srv/pudu-materials-workspaces/<account>, on codex/<account> branches.
Do not edit a shared working tree or the active immutable source release.
The integration repository above remains the authoritative GitLab checkout.
After committing in the personal workspace, run `sudo pudu-release` there.
The entry holds /run/lock/pudu-material-release.lock across integration,
validation, GitLab push and promotion. It performs a three-way merge; the later
submitted workspace wins overlapping text changes, while unrelated changes are
preserved. Structural conflicts or failing checks stop before publishing.
Never force-push or bypass this entry with an ad-hoc source symlink change.
An already tested/pushed revision can use `sudo pudu-release --deploy <sha>`;
it must equal the current GitLab codex/postgres-core head and descend from live.

Browser edits use PUDU_CONCURRENT_EDIT_POLICY=last_commit_wins in production.
The server's successful transaction order decides the final submitted fields;
client clocks and the time an editor opened the page do not decide precedence.
Keep idempotency, row locks, stock/quota transactions, role checks and validation.
Delayed earlier jobs must finish or fail before later jobs in that business lane.
Ordinary material and cultural submissions retain independent business lanes.
Outbox local versions determine Feishu publication order, including across lanes.
The daily 03:00 Feishu-authoritative reconciliation remains unchanged.

## Durable handover and conversation records

Start by reading docs/ops/README.md and docs/ops/02-固定业务规则.md. These describe
the current PostgreSQL VM production system. docs/handover and the commissioning
notes in deployment/ubuntu/README.md are historical; do not install their old units
over live production. Inspect effective systemd units/drop-ins before changing them.

For every completed user task/conversation, create or update a record under
docs/ops/changes using scripts/new_ops_record.py and the supplied template. Preserve
the request, later corrections, decisions, changed files/fields, actual verification,
and explicit remaining work. Include the record in the same code submission.
Update the canonical business rules when an authorized requirement changes them.
Release SHA and final runtime evidence come from shared/release-audit.jsonl and
read-only live checks, never from an expected version written before deployment.

Keep raw/redacted chat archives under shared/handover-archives or a restricted
handover folder, never in Git. scripts/export_conversations.py exports only explicitly
selected user/visible-assistant messages; no hidden reasoning or tool payloads.
It is an explicit export tool, not an automatic listener for future chats.

Do not restore extra administrator success cards for management/allocation/shipping.
Keep applicant/original workflow cards and failure alerts. Both apparel and cultural
partial rejection affect only selected issued lines and must update original cards.
All operation details and superseded decisions are indexed in docs/ops.

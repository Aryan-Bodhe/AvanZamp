"""Fresh pilot schema, intentionally independent of prototype SQLite data.

Revision ID: 0001_pilot
Revises: None
"""
from alembic import op
import sqlalchemy as sa

revision = '0001_pilot'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Freeze the initial schema in this revision; subsequent migrations must not modify it.
    from migrations.schema_0001 import metadata
    metadata.create_all(op.get_bind())
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('''CREATE FUNCTION pilot_no_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN RAISE EXCEPTION 'append-only pilot table'; END; $$''')
        for table in ('artifacts', 'approval_ledger', 'audit_events', 'stage_events', 'commands'):
            op.execute(sa.text(f'CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION pilot_no_mutation()'))


def downgrade():
    raise RuntimeError('Pilot artifacts are append-only. Restore a verified backup instead of destructive downgrade.')

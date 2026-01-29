"""Initial database schema

Revision ID: 001_initial
Revises: 
Create Date: 2026-01-29 13:15:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial schema for NIJA trading platform"""
    
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('subscription_tier', sa.String(length=20), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
        sa.UniqueConstraint('email')
    )
    op.create_index('ix_users_user_id', 'users', ['user_id'])
    op.create_index('ix_users_email', 'users', ['email'])

    # Create broker_credentials table
    op.create_table(
        'broker_credentials',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('broker_name', sa.String(length=50), nullable=False),
        sa.Column('encrypted_api_key', sa.Text(), nullable=False),
        sa.Column('encrypted_api_secret', sa.Text(), nullable=False),
        sa.Column('encrypted_additional_params', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_broker_credentials_user_id', 'broker_credentials', ['user_id'])

    # Create user_permissions table
    op.create_table(
        'user_permissions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('max_position_size_usd', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('max_daily_loss_usd', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('max_positions', sa.Integer(), nullable=True),
        sa.Column('trade_only', sa.Boolean(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )

    # Create trading_instances table
    op.create_table(
        'trading_instances',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('container_id', sa.String(length=255), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('stopped_at', sa.DateTime(), nullable=True),
        sa.Column('last_activity', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )

    # Create positions table
    op.create_table(
        'positions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('pair', sa.String(length=20), nullable=False),
        sa.Column('side', sa.String(length=10), nullable=False),
        sa.Column('size', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('entry_price', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('current_price', sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column('pnl', sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column('pnl_percent', sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column('opened_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_positions_user_id', 'positions', ['user_id'])
    op.create_index('ix_positions_status', 'positions', ['status'])

    # Create trades table
    op.create_table(
        'trades',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('pair', sa.String(length=20), nullable=False),
        sa.Column('side', sa.String(length=10), nullable=False),
        sa.Column('size', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('entry_price', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('exit_price', sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column('pnl', sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column('pnl_percent', sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column('fees', sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column('opened_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_trades_user_id', 'trades', ['user_id'])
    op.create_index('ix_trades_closed_at', 'trades', ['closed_at'])

    # Create daily_statistics table
    op.create_table(
        'daily_statistics',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('total_trades', sa.Integer(), nullable=True),
        sa.Column('winning_trades', sa.Integer(), nullable=True),
        sa.Column('losing_trades', sa.Integer(), nullable=True),
        sa.Column('total_pnl', sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column('total_fees', sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Drop all tables"""
    op.drop_table('daily_statistics')
    op.drop_table('trades')
    op.drop_table('positions')
    op.drop_table('trading_instances')
    op.drop_table('user_permissions')
    op.drop_table('broker_credentials')
    op.drop_table('users')

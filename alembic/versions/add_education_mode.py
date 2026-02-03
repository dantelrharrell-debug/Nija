"""Add education mode fields to users

Revision ID: add_education_mode
Revises: 
Create Date: 2026-02-03 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_education_mode'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Add education_mode and consented_to_live_trading columns to users table"""
    
    # Add education_mode column (default True - start in education mode)
    op.add_column('users', 
        sa.Column('education_mode', sa.Boolean(), nullable=False, server_default='true')
    )
    
    # Add consented_to_live_trading column (default False - requires explicit consent)
    op.add_column('users', 
        sa.Column('consented_to_live_trading', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade():
    """Remove education mode columns"""
    
    op.drop_column('users', 'consented_to_live_trading')
    op.drop_column('users', 'education_mode')

"""Resolve knowledge settings without inheriting an obsolete backend KB selection."""
import os
from pathlib import Path
from dotenv import dotenv_values

KEYS = (
    'WGS_CLAIM_API_URL', 'WGS_CLAIM_API_KNOWLEDGE_BASE_ID',
    'WGS_CLAIM_API_TIMEOUT', 'WGS_CLAIM_API_ASK_HOPS',
    'WGS_KNOWLEDGE_ACQUISITION_SCOPE', 'WGS_KNOWLEDGE_USAGE_INCLUDE_PENDING',
    'WGS_KNOWLEDGE_SNAPSHOT_TTL',
)

def refresh_knowledge_settings(config_file=None):
    root = Path(__file__).resolve().parents[3]
    env_file = Path(config_file) if config_file is not None else root / '.env'
    source = os.environ.get('WGS_KNOWLEDGE_CONFIG_SOURCE', 'project_env')
    if source not in {'project_env', 'environment'}:
        raise ValueError('WGS_KNOWLEDGE_CONFIG_SOURCE must be project_env or environment')
    if source == 'project_env':
        # Only knowledge configuration is refreshed. Authentication values are untouched.
        values = dotenv_values(env_file, interpolate=False)
        for key in KEYS:
            if key in values and values[key] is not None:
                os.environ[key] = values[key]
    return {'config_source': source, 'config_file': str(env_file) if source == 'project_env' else None}

def eligible_for_use(row):
    """A consumption policy; acquisition always retains pending data and all predicates."""
    if os.environ.get('WGS_KNOWLEDGE_USAGE_INCLUDE_PENDING', 'true').lower() in {'1', 'true'}:
        return True
    return not is_pending_review(row)


def is_pending_review(row):
    """Use the same review signals for filtering and ranking claims."""
    claim = row.get('claim_json')
    return bool(
        row.get('audit_pending')
        or row.get('semantic_status') == 'pending'
        or row.get('review_status') == 'pending'
        or (isinstance(claim, dict) and claim.get('semantic_status') == 'pending')
    )

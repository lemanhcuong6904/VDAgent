select config_key, config_value, value_type, semantic_version, approval_status, description
from {{ source('raw', 'semantic_config') }}

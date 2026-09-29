
  
  create view "vgp"."main_staging"."stg_semantic_config__dbt_tmp" as (
    select config_key, config_value, value_type, semantic_version, approval_status, description
from '../data/02_semantic_config.csv'
  );

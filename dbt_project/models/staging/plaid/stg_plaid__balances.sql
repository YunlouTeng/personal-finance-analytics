-- Balance history: one row per account per snapshot. Deliberately NOT
-- deduplicated; the time series is the point, it is what net worth over
-- time will be built from.

select
    payload:account_id::string            as account_id,
    _item_id                              as item_id,
    payload:balances.available::number(18, 2) as available_balance,
    payload:balances.current::number(18, 2)   as current_balance,
    payload:balances."limit"::number(18, 2)   as credit_limit,
    payload:balances.iso_currency_code::string as currency_code,
    _batch_id                             as batch_id,
    _loaded_at                            as snapshot_at
from {{ source('plaid', 'plaid_balances') }}

-- Latest known metadata per account. Snapshots accumulate in raw; only
-- the most recent one per account is current.

with snapshots as (

    select
        payload,
        _item_id,
        _batch_id,
        _loaded_at
    from {{ source('plaid', 'plaid_accounts') }}

),

latest as (

    select *
    from snapshots
    qualify row_number() over (
        partition by payload:account_id::string
        order by _loaded_at desc
    ) = 1

)

select
    payload:account_id::string            as account_id,
    _item_id                              as item_id,
    payload:name::string                  as account_name,
    payload:official_name::string         as official_name,
    payload:type::string                  as account_type,
    payload:subtype::string               as account_subtype,
    payload:mask::string                  as account_mask,
    payload:balances.iso_currency_code::string as currency_code,
    _loaded_at                            as loaded_at
from latest

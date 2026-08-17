-- Current state of every transaction, reduced from the append-only event
-- log in raw. Rename, cast, dedupe, and flag removals; no joins, no
-- business logic.

with events as (

    select
        payload,
        _change_type,
        _item_id,
        _batch_id,
        _loaded_at
    from {{ source('plaid', 'plaid_transactions') }}

),

current_state as (

    select *
    from events
    -- Latest event per transaction wins. The _change_type tiebreak is
    -- deterministic within a batch: alphabetically removed > modified >
    -- added, which is also the correct precedence.
    qualify row_number() over (
        partition by payload:transaction_id::string
        order by _loaded_at desc, _change_type desc
    ) = 1

)

select
    payload:transaction_id::string        as transaction_id,
    payload:account_id::string            as account_id,
    _item_id                              as item_id,

    -- Plaid sign convention: positive = money leaving the account.
    -- Kept as-is; flipping signs would be business logic.
    payload:amount::number(18, 2)         as amount,
    payload:iso_currency_code::string     as currency_code,
    payload:date::date                    as transaction_date,
    payload:authorized_date::date         as authorized_date,

    payload:name::string                  as description,
    payload:merchant_name::string         as merchant_name,
    payload:payment_channel::string       as payment_channel,
    payload:personal_finance_category.primary::string
                                          as category_primary,
    payload:personal_finance_category.detailed::string
                                          as category_detailed,

    payload:pending::boolean              as is_pending,
    payload:pending_transaction_id::string as pending_transaction_id,

    -- Soft delete: removed events carry only a transaction_id, so every
    -- typed column above is null on these rows. Downstream models filter
    -- on this flag; the history stays auditable.
    _change_type = 'removed'              as is_removed,

    _batch_id                             as batch_id,
    _loaded_at                            as loaded_at

from current_state

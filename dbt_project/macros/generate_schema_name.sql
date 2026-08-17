{#
    Use the schema configured on the model (staging, intermediate, marts)
    as the actual schema name. Without this override dbt concatenates the
    target schema and the custom schema, producing STAGING_STAGING, which
    would not match the schemas the setup DDL creates.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}

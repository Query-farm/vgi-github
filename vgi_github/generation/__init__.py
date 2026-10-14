"""Build-time schema compilation for reviewed generated GitHub entities."""

from .schema import SchemaError, compile_contract, compile_graphql_entity, compile_rest_entity

__all__ = ["SchemaError", "compile_contract", "compile_graphql_entity", "compile_rest_entity"]

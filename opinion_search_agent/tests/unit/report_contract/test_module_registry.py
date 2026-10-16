from opinion_search.report_contract.registry import default_module_registry, registry_by_type


def test_default_registry_contains_core_and_extension_modules() -> None:
    contracts = default_module_registry()

    assert len(contracts) == 40
    assert contracts[0].semantic_type == "executive-summary"
    assert "policy-background" in registry_by_type()
    assert "artist-statement" in registry_by_type()


def test_registry_semantic_types_are_unique() -> None:
    contracts = default_module_registry()
    semantic_types = [contract.semantic_type for contract in contracts]

    assert len(semantic_types) == len(set(semantic_types))

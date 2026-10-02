"""Support offline validation without shadowing ChatTFT's runtime utils package."""


def partial_schema(value: object) -> object:
    """Permit partial argument objects while retaining the tool's field contracts.

    Args:
        value: Registered SDK JSON schema or one of its descendants.

    Returns:
        An independent schema retaining names, types and bounds, but not required
        property lists. The trace evaluator treats these objects as subsets.
    """
    if isinstance(value, dict):
        return {key: partial_schema(item) for key, item in value.items() if key != "required"}
    if isinstance(value, list):
        return [partial_schema(item) for item in value]
    return value

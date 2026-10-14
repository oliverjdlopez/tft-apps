"""Offline validation command for the authored resource graph and contents."""

from domain.resources.library import validate_library


def main() -> None:
    """Validate all resources without model calls or database access."""
    library = validate_library()
    print(f'Validated {len(library.entries)} resources and derived views.')


if __name__ == '__main__':
    main()

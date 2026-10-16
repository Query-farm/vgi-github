"""Run the actual generated GitHub worker with the original connected HTTP oracle.

No semantic answers are returned by this fixture: native VGI reads GitHub-shaped
HTTP pages, and Crossfield computes all selected metrics in DuckDB.
"""

import connected_fixture

if __name__ == "__main__":
    connected_fixture.main()

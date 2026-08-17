"""Options for the on-chain suite."""


def pytest_addoption(parser):
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="Also run the test that hits the real GitHub API with no mocks.",
    )

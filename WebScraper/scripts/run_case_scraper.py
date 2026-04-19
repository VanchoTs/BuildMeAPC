import argparse
import asyncio

from pipelines.case_pipeline import run_case_pipeline


def main():
    parser = argparse.ArgumentParser(description="Run PC case scraper pipeline")
    parser.add_argument(
        "--mode",
        choices=("links", "full"),
        default="full",
        help="Run mode: collect links only or full scrape",
    )
    parser.add_argument(
        "--headless", action="store_true", help="Run browser in headless mode"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional limit on number of product pages to process (0 = no limit)",
    )
    args = parser.parse_args()

    collect_only = args.mode == "links"
    page_limit = args.limit if args.limit > 0 else None

    asyncio.run(
        run_case_pipeline(
            headless=args.headless, collect_only=collect_only, page_limit=page_limit
        )
    )


if __name__ == "__main__":
    main()

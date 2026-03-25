import argparse
import asyncio

from pipelines.motherboard_pipeline import run_motherboard_pipeline


def main():
    p = argparse.ArgumentParser(description="Run motherboard scraper pipeline")
    p.add_argument(
        "--mode",
        choices=("links", "full"),
        default="full",
        help="Run mode: collect links only or full scrape",
    )
    p.add_argument(
        "--headless", action="store_true", help="Run browser in headless mode"
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional limit on number of product pages to process (0 = no limit)",
    )
    args = p.parse_args()

    collect_only = args.mode == "links"
    page_limit = args.limit if args.limit > 0 else None

    asyncio.run(
        run_motherboard_pipeline(
            headless=args.headless,
            collect_only=collect_only,
            page_limit=page_limit,
        )
    )


if __name__ == "__main__":
    main()
